"""Clip state machine (blueprint Phase 2 foundation, built on the Phase 1 log).

Every clip candidate moves through a validated lifecycle. Transitions are not
free-form: only edges defined in `TRANSITIONS` are allowed, and each accepted
transition appends a `WorkflowEvent` recording actor, source state, target state,
reason, payload, model version, correlation id, and time. That append-only trail
is the auditability guarantee the blueprint requires (non-negotiable rule #10).

The graph mirrors the blueprint's Discord Clip Room flow:

    DETECTED -> CANDIDATE -> SENT_TO_DISCORD -> CLAIMED
      -> RAW_REQUESTED | EDIT_REQUESTED -> RENDERING -> READY_FOR_REVIEW
      -> APPROVED | REVISION_REQUESTED
      APPROVED -> SCHEDULED -> PUBLISHED -> MEASURED -> LEARNING_COMPLETE

`REJECTED` is the terminal "Reject" outcome reachable from any pre-publish review
state. `LEARNING_COMPLETE` and `REJECTED` are terminal.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from db.models import ClipCandidate, WorkflowEvent
from db.repository import WorkflowEventRepo


class ClipState:
    DETECTED = "DETECTED"
    CANDIDATE = "CANDIDATE"
    SENT_TO_DISCORD = "SENT_TO_DISCORD"
    CLAIMED = "CLAIMED"
    RAW_REQUESTED = "RAW_REQUESTED"
    EDIT_REQUESTED = "EDIT_REQUESTED"
    RENDERING = "RENDERING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    MEASURED = "MEASURED"
    LEARNING_COMPLETE = "LEARNING_COMPLETE"
    REJECTED = "REJECTED"


# A "Reject" can end most pre-publish review/claim states.
_REJECTABLE_FROM = {
    ClipState.CANDIDATE,
    ClipState.SENT_TO_DISCORD,
    ClipState.CLAIMED,
    ClipState.RAW_REQUESTED,
    ClipState.EDIT_REQUESTED,
    ClipState.READY_FOR_REVIEW,
    ClipState.REVISION_REQUESTED,
}

TRANSITIONS: dict[str, frozenset[str]] = {
    ClipState.DETECTED: frozenset({ClipState.CANDIDATE, ClipState.REJECTED}),
    ClipState.CANDIDATE: frozenset({ClipState.SENT_TO_DISCORD, ClipState.REJECTED}),
    ClipState.SENT_TO_DISCORD: frozenset({ClipState.CLAIMED, ClipState.REJECTED}),
    ClipState.CLAIMED: frozenset(
        {ClipState.RAW_REQUESTED, ClipState.EDIT_REQUESTED, ClipState.REJECTED}
    ),
    ClipState.RAW_REQUESTED: frozenset({ClipState.RENDERING, ClipState.REJECTED}),
    ClipState.EDIT_REQUESTED: frozenset({ClipState.RENDERING, ClipState.REJECTED}),
    # Rendering can fail back to its request for a retry, or succeed to review.
    ClipState.RENDERING: frozenset(
        {ClipState.READY_FOR_REVIEW, ClipState.EDIT_REQUESTED, ClipState.RAW_REQUESTED}
    ),
    ClipState.READY_FOR_REVIEW: frozenset(
        {ClipState.APPROVED, ClipState.REVISION_REQUESTED, ClipState.REJECTED}
    ),
    # A revision goes back to the editor (re-cut) or straight to a re-render.
    ClipState.REVISION_REQUESTED: frozenset(
        {ClipState.EDIT_REQUESTED, ClipState.RENDERING, ClipState.REJECTED}
    ),
    ClipState.APPROVED: frozenset({ClipState.SCHEDULED, ClipState.PUBLISHED}),
    ClipState.SCHEDULED: frozenset({ClipState.PUBLISHED, ClipState.APPROVED}),
    ClipState.PUBLISHED: frozenset({ClipState.MEASURED}),
    ClipState.MEASURED: frozenset({ClipState.LEARNING_COMPLETE}),
    ClipState.LEARNING_COMPLETE: frozenset(),
    ClipState.REJECTED: frozenset(),
}

TERMINAL_STATES = frozenset({ClipState.LEARNING_COMPLETE, ClipState.REJECTED})
ALL_STATES = frozenset(TRANSITIONS.keys())

ENTITY_TYPE = "clip_candidate"


class InvalidTransition(ValueError):
    """Raised when a state change is not a defined edge in `TRANSITIONS`."""


def can_transition(from_state: str, to_state: str) -> bool:
    return to_state in TRANSITIONS.get(from_state, frozenset())


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def transition(
    session: Session,
    candidate: ClipCandidate,
    to_state: str,
    *,
    actor: str = "system",
    reason: str = "",
    payload: Optional[dict] = None,
    model_version: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> WorkflowEvent:
    """Validate and apply a state change, appending a WorkflowEvent.

    Flushes (so the event gets an id and the candidate update is staged) but does
    NOT commit — the caller's `session_scope()` owns the transaction boundary.

    Raises `InvalidTransition` if the edge is undefined. A no-op self-transition
    is also rejected to keep the audit log meaningful.
    """
    from_state = candidate.state
    if to_state not in ALL_STATES:
        raise InvalidTransition(f"unknown target state {to_state!r}")
    if not can_transition(from_state, to_state):
        raise InvalidTransition(
            f"{from_state} -> {to_state} is not a valid transition for candidate {candidate.id}"
        )

    candidate.state = to_state
    events = WorkflowEventRepo(session, creator_id=candidate.creator_id)
    return events.append(
        entity_type=ENTITY_TYPE,
        entity_id=candidate.id,
        actor=actor,
        from_state=from_state,
        to_state=to_state,
        reason=reason,
        payload=payload,
        model_version=model_version,
        correlation_id=correlation_id,
    )


__all__ = [
    "ClipState",
    "TRANSITIONS",
    "TERMINAL_STATES",
    "ALL_STATES",
    "InvalidTransition",
    "can_transition",
    "is_terminal",
    "transition",
]
