"""Discord Clip Room — the first HeisLazi OS vertical slice (blueprint Phase 2).

This is the domain core that drives a clip from a detected candidate, out to the
Discord `#clips` channel as a review card, through an editor's claim/edit/approve
actions, to a rendered, approved result — every step a validated state-machine
transition recorded in the append-only audit log.

It is deliberately decoupled from the live Discord connection: all Discord IO goes
through the `DiscordGateway` protocol, with a `NullDiscordGateway` that logs and
returns synthetic ids. The whole workflow is therefore testable with no network,
and wiring a real discord.py bot later is just supplying a gateway + token.

Action surface (maps to the blueprint's Discord actions):
    promote -> send_to_discord -> claim
      -> request_raw | request_edit | extend_before | extend_after | different_crop
      -> start_render -> complete_render
      -> approve | request_revision | reject

Role-gating (only the Discord `edits` role may claim/approve) is enforced at the
bot interaction layer before these methods are called; the service records the
actor and trusts the caller to have checked the role.
"""

from __future__ import annotations

import logging
import re
import base64
from pathlib import Path
from typing import Any, Optional, Protocol

from sqlalchemy import update

from db.base import DEFAULT_CREATOR_ID, SessionLocal, new_id
from db.models import ClipCandidate
from db.repository import (
    ClipCandidateRepo,
    ClipVersionRepo,
    WorkflowEventRepo,
    session_scope,
)
from db.state_machine import ClipState, InvalidTransition, transition

log = logging.getLogger("clip_room")

# Mirrors the layouts modules/editor.py knows how to render. Kept as a local
# whitelist so an edit request can never smuggle in an arbitrary value.
_ALLOWED_LAYOUTS = frozenset({"reaction", "crop", "fullcam", "passthrough"})
_BOX_FIELDS = ("cam_box", "content_box", "crop_box")
_MAX_FX_GAIN = 10.0
# Characters Windows (and our shell-free ffmpeg pipeline) reject in a filename.
_INVALID_STEM = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# A rendered version must declare a known kind + bucket (mirrors editor buckets).
_VALID_KINDS = frozenset({"raw", "edit", "compilation"})
_VALID_BUCKETS = frozenset({"output", "edited", "positives", "negatives"})


class ClipRoomError(RuntimeError):
    pass


class EditValidationError(ValueError):
    """Raised when an edit request fails validation (non-negotiable rule #3:
    we accept validated edit plans, never raw ffmpeg)."""


# -----------------------------------------------------------------------------
# Edit-request validation: NL/loose dict -> a safe, whitelisted editor spec.
# -----------------------------------------------------------------------------

def _num(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise EditValidationError(f"{field} must be a number, got {value!r}")


def _validate_box(value: Any, field: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise EditValidationError(f"{field} must be [x, y, w, h]")
    x, y, w, h = (_num(v, field) for v in value)
    if x < 0 or y < 0:
        raise EditValidationError(f"{field} x/y must be >= 0")
    if w <= 0 or h <= 0:
        raise EditValidationError(f"{field} width/height must be > 0")
    return [x, y, w, h]


def validate_render_output(path: str, kind: str, bucket: str) -> None:
    """Guard a render-completion record: a real path + known kind/bucket."""
    if not path or not isinstance(path, str):
        raise EditValidationError("render path is required")
    if kind not in _VALID_KINDS:
        raise EditValidationError(f"kind must be one of {sorted(_VALID_KINDS)}")
    if bucket not in _VALID_BUCKETS:
        raise EditValidationError(f"bucket must be one of {sorted(_VALID_BUCKETS)}")


def validate_edit_request(raw: dict[str, Any]) -> dict[str, Any]:
    """Whitelist a loose edit request into an editor spec. Unknown keys are
    rejected; every value is type/range checked. Returns a clean spec dict."""
    if not isinstance(raw, dict):
        raise EditValidationError("edit request must be an object")

    allowed = {"trim", "layout", "audio_boost_db", "audio_normalize", "sound_fx", "output_stem", *_BOX_FIELDS}
    unknown = set(raw) - allowed
    if unknown:
        raise EditValidationError(f"unknown edit fields: {sorted(unknown)}")

    spec: dict[str, Any] = {}

    if "trim" in raw:
        trim = raw["trim"]
        if not isinstance(trim, dict):
            raise EditValidationError("trim must be {start, end}")
        start = _num(trim.get("start", 0.0), "trim.start")
        end = _num(trim.get("end", 0.0), "trim.end")
        if start < 0:
            raise EditValidationError("trim.start must be >= 0")
        if end <= start:
            raise EditValidationError("trim.end must be > trim.start")
        spec["trim"] = {"start": start, "end": end}

    if "layout" in raw:
        if raw["layout"] not in _ALLOWED_LAYOUTS:
            raise EditValidationError(f"layout must be one of {sorted(_ALLOWED_LAYOUTS)}")
        spec["layout"] = raw["layout"]

    for box in _BOX_FIELDS:
        if box in raw:
            spec[box] = _validate_box(raw[box], box)

    if "audio_boost_db" in raw:
        db = _num(raw["audio_boost_db"], "audio_boost_db")
        if not -30.0 <= db <= 30.0:
            raise EditValidationError("audio_boost_db must be within [-30, 30]")
        spec["audio_boost_db"] = db

    if "audio_normalize" in raw:
        # Must be a real bool — bool("false") is True, a classic footgun.
        if not isinstance(raw["audio_normalize"], bool):
            raise EditValidationError("audio_normalize must be true or false (boolean)")
        spec["audio_normalize"] = raw["audio_normalize"]

    if "sound_fx" in raw:
        fx_in = raw["sound_fx"]
        if not isinstance(fx_in, list):
            raise EditValidationError("sound_fx must be a list")
        fx_out = []
        for i, fx in enumerate(fx_in):
            if not isinstance(fx, dict) or not fx.get("name"):
                raise EditValidationError(f"sound_fx[{i}] must be {{name, at, gain}}")
            at = _num(fx.get("at", 0.0), f"sound_fx[{i}].at")
            if at < 0:
                raise EditValidationError(f"sound_fx[{i}].at must be >= 0")
            gain = _num(fx.get("gain", 1.0), f"sound_fx[{i}].gain")
            if not 0.0 <= gain <= _MAX_FX_GAIN:
                raise EditValidationError(f"sound_fx[{i}].gain must be within [0, {_MAX_FX_GAIN}]")
            fx_out.append({"name": str(fx["name"]), "at": at, "gain": gain})
        spec["sound_fx"] = fx_out

    if "output_stem" in raw:
        stem = str(raw["output_stem"]).strip()
        if not stem or stem in (".", "..") or _INVALID_STEM.search(stem):
            raise EditValidationError("output_stem must be a safe bare filename")
        spec["output_stem"] = stem

    if not spec:
        raise EditValidationError("edit request is empty — nothing to change")
    return spec


# -----------------------------------------------------------------------------
# Candidate card + Discord gateway
# -----------------------------------------------------------------------------

def build_candidate_card(candidate) -> dict[str, Any]:
    """The review card posted to #clips: reason, score, duration, hazards."""
    start = candidate.start or 0.0
    end = candidate.end or 0.0
    return {
        "candidate_id": candidate.id,
        "title": (candidate.reason or candidate.stem or "clip")[:120],
        "stem": candidate.stem,
        "score": round(candidate.score or 0.0, 3),
        "duration": round(end - start, 1),
        "start": start,
        "end": end,
        "hazards": list(candidate.hazards or []),
        "state": candidate.state,
    }


class DiscordGateway(Protocol):
    """The only surface that touches Discord. Swap in a real discord.py-backed
    implementation when a bot token is available."""

    def post_candidate_card(self, card: dict) -> dict: ...
    def post_render_result(self, thread_id: Optional[str], version: dict) -> None: ...
    def notify(self, message: str) -> None: ...


class NullDiscordGateway:
    """No-network gateway: logs intent, returns synthetic ids. Lets the whole
    Clip Room run and be tested before the bot is connected."""

    def post_candidate_card(self, card: dict) -> dict:
        mid = "null-" + new_id()[:12]
        log.info("[null discord] candidate card: %s (score %s)", card.get("title"), card.get("score"))
        return {"message_id": mid, "thread_id": "thread-" + mid}

    def post_render_result(self, thread_id: Optional[str], version: dict) -> None:
        log.info("[null discord] render result -> thread %s: %s", thread_id, version.get("path"))

    def notify(self, message: str) -> None:
        log.info("[null discord] %s", message)


def _candidate_dict(c) -> dict[str, Any]:
    review = None
    try:
        from modules.clip_reviews import get_review
        review = get_review(c.stem)
    except Exception:
        review = None
    return {
        "id": c.id,
        "stem": c.stem,
        "state": c.state,
        "score": c.score,
        "start": c.start,
        "end": c.end,
        "reason": c.reason,
        "hazards": c.hazards,
        "claimed_by": c.claimed_by,
        "discord_message_id": c.discord_message_id,
        "discord_thread_id": c.discord_thread_id,
        "vod_id": c.vod_id,
        "vod_stem": c.vod.stem if c.vod is not None else None,
        "vod_path": c.vod.path if c.vod is not None else None,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
        "has_render": bool(c.versions),
        "tags": list((review or {}).get("tags") or []),
    }


def _cursor_offset(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii") + b"===").decode("ascii")
        return max(0, int(decoded))
    except (ValueError, UnicodeError):
        raise EditValidationError("invalid candidate cursor")


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii").rstrip("=")


# -----------------------------------------------------------------------------
# The service
# -----------------------------------------------------------------------------

class ClipRoom:
    def __init__(self, session_factory=SessionLocal, gateway: Optional[DiscordGateway] = None,
                 creator_id: str = DEFAULT_CREATOR_ID) -> None:
        self._factory = session_factory
        self.gateway: DiscordGateway = gateway or NullDiscordGateway()
        self.creator_id = creator_id

    def _require(self, session, candidate_id: str):
        c = ClipCandidateRepo(session, self.creator_id).get(candidate_id)
        if c is None:
            raise ClipRoomError(f"candidate {candidate_id} not found")
        return c

    # -- intake ------------------------------------------------------------
    def promote(self, candidate_id: str, *, actor: str = "director") -> dict:
        with session_scope(self._factory) as s:
            c = self._require(s, candidate_id)
            transition(s, c, ClipState.CANDIDATE, actor=actor, reason="promoted")
            return _candidate_dict(c)

    def prepare_card(self, candidate_id: str) -> dict:
        with session_scope(self._factory) as s:
            return build_candidate_card(self._require(s, candidate_id))

    def mark_sent(self, candidate_id: str, *, message_id: str, thread_id: Optional[str] = None,
                  actor: str = "director") -> dict:
        """Record that the candidate card has been posted to Discord."""
        with session_scope(self._factory) as s:
            c = self._require(s, candidate_id)
            c.discord_message_id = message_id
            c.discord_thread_id = thread_id
            transition(s, c, ClipState.SENT_TO_DISCORD, actor=actor,
                       reason="posted to discord", payload={"message_id": message_id})
            return _candidate_dict(c)

    def send_to_discord(self, candidate_id: str, *, actor: str = "director") -> dict:
        """Build the card, post it via the gateway, record the refs — as a
        transactional outbox so a card is posted at most once.

        The Discord post is a network call that can't join the DB transaction, so
        we split it into three durable steps:
          1. RESERVE: one atomic conditional UPDATE moves CANDIDATE ->
             SENT_TO_DISCORD (with no message id yet). A second caller — an
             overlapping `dispatch_candidates` pass, a retry, a double-click —
             matches 0 rows and posts nothing, so the card can never duplicate.
          2. POST: send the card outside the committed reservation.
          3. RECORD: write the returned message/thread ids onto the reserved row.
        If the post throws, the reservation is released back to CANDIDATE for a
        clean retry. If the process dies between RESERVE and RECORD, the row is
        left SENT_TO_DISCORD with a null message id — `recover_stuck_sends()`
        (run at startup) resets those so the dispatcher retries.
        """
        with session_scope(self._factory) as s:
            c = self._require(s, candidate_id)
            if c.discord_message_id:
                return _candidate_dict(c)  # already fully sent — no-op
            reserved = s.execute(
                update(ClipCandidate)
                .where(
                    ClipCandidate.id == candidate_id,
                    ClipCandidate.creator_id == self.creator_id,
                    ClipCandidate.state == ClipState.CANDIDATE,
                )
                .values(state=ClipState.SENT_TO_DISCORD)
            )
            if reserved.rowcount == 0:
                # Not CANDIDATE anymore: another caller reserved it (in-flight) or
                # it already advanced. Return current state; never post twice.
                s.refresh(c)
                return _candidate_dict(c)
            s.refresh(c)
            WorkflowEventRepo(s, self.creator_id).append(
                entity_type="clip_candidate", entity_id=candidate_id, actor=actor,
                from_state=ClipState.CANDIDATE, to_state=ClipState.SENT_TO_DISCORD,
                reason="posted to discord",
            )
            card = build_candidate_card(c)

        try:
            posted = self.gateway.post_candidate_card(card)  # network, outside the txn
        except Exception:
            self._release_send_reservation(candidate_id, actor=actor)
            raise

        with session_scope(self._factory) as s:
            c = self._require(s, candidate_id)
            c.discord_message_id = posted["message_id"]
            c.discord_thread_id = posted.get("thread_id")
            s.flush()
            return _candidate_dict(c)

    def _release_send_reservation(self, candidate_id: str, *, actor: str = "director") -> None:
        """Undo a send reservation whose network post failed, so the dispatcher can
        retry it. Only touches a row still reserved-but-unposted (no message id)."""
        with session_scope(self._factory) as s:
            released = s.execute(
                update(ClipCandidate)
                .where(
                    ClipCandidate.id == candidate_id,
                    ClipCandidate.creator_id == self.creator_id,
                    ClipCandidate.state == ClipState.SENT_TO_DISCORD,
                    ClipCandidate.discord_message_id.is_(None),
                )
                .values(state=ClipState.CANDIDATE)
            )
            if released.rowcount:
                WorkflowEventRepo(s, self.creator_id).append(
                    entity_type="clip_candidate", entity_id=candidate_id, actor=actor,
                    from_state=ClipState.SENT_TO_DISCORD, to_state=ClipState.CANDIDATE,
                    reason="discord post failed — released for retry",
                )

    def recover_stuck_sends(self) -> int:
        """Reset candidates reserved for a send that never completed (no message id)
        back to CANDIDATE so the dispatcher retries them.

        Safe to call at STARTUP ONLY: while the app is running, a genuine in-flight
        send is momentarily in exactly this state, so a mid-run sweep could race a
        live post and cause the duplicate this whole mechanism prevents.
        """
        with session_scope(self._factory) as s:
            recovered = s.execute(
                update(ClipCandidate)
                .where(
                    ClipCandidate.creator_id == self.creator_id,
                    ClipCandidate.state == ClipState.SENT_TO_DISCORD,
                    ClipCandidate.discord_message_id.is_(None),
                )
                .values(state=ClipState.CANDIDATE)
            )
            n = int(recovered.rowcount or 0)
            if n:
                log.info("recovered %d stuck discord send(s) back to CANDIDATE", n)
            return n

    # -- claim + edit requests --------------------------------------------
    def claim(self, candidate_id: str, *, actor: str) -> dict:
        """Claim a candidate for editing. Race-safe: the SENT_TO_DISCORD ->
        CLAIMED transition is a single conditional UPDATE, so only one editor
        can win even if two click Claim at the same instant."""
        with session_scope(self._factory) as s:
            c = self._require(s, candidate_id)  # 404 if it doesn't exist
            res = s.execute(
                update(ClipCandidate)
                .where(
                    ClipCandidate.id == candidate_id,
                    ClipCandidate.creator_id == self.creator_id,
                    ClipCandidate.state == ClipState.SENT_TO_DISCORD,
                )
                .values(state=ClipState.CLAIMED, claimed_by=actor)
            )
            if res.rowcount == 0:
                raise InvalidTransition(
                    f"candidate {candidate_id} is {c.state}, cannot claim "
                    f"(already claimed by {c.claimed_by})" if c.claimed_by
                    else f"candidate {candidate_id} is {c.state}, cannot claim"
                )
            s.refresh(c)
            WorkflowEventRepo(s, self.creator_id).append(
                entity_type="clip_candidate", entity_id=candidate_id, actor=actor,
                from_state=ClipState.SENT_TO_DISCORD, to_state=ClipState.CLAIMED, reason="claimed",
            )
            return _candidate_dict(c)

    def request_raw(self, candidate_id: str, *, actor: str) -> dict:
        with session_scope(self._factory) as s:
            c = self._require(s, candidate_id)
            transition(s, c, ClipState.RAW_REQUESTED, actor=actor, reason="raw cut requested")
            return _candidate_dict(c)

    def request_edit(self, candidate_id: str, edit_request: dict, *, actor: str) -> dict:
        spec = validate_edit_request(edit_request)  # raises EditValidationError on bad input
        with session_scope(self._factory) as s:
            c = self._require(s, candidate_id)
            transition(s, c, ClipState.EDIT_REQUESTED, actor=actor,
                       reason="edit requested", payload={"edit": spec})
            return _candidate_dict(c)

    def extend_before(self, candidate_id: str, seconds: float, *, actor: str) -> dict:
        if float(seconds) <= 0:
            raise EditValidationError("extend seconds must be > 0")
        return self._extend(candidate_id, before=float(seconds), after=0.0, actor=actor)

    def extend_after(self, candidate_id: str, seconds: float, *, actor: str) -> dict:
        if float(seconds) <= 0:
            raise EditValidationError("extend seconds must be > 0")
        return self._extend(candidate_id, before=0.0, after=float(seconds), actor=actor)

    def _extend(self, candidate_id: str, *, before: float, after: float, actor: str) -> dict:
        with session_scope(self._factory) as s:
            c = self._require(s, candidate_id)
            c.start = max(0.0, (c.start or 0.0) - before)
            c.end = (c.end or 0.0) + after
            transition(s, c, ClipState.EDIT_REQUESTED, actor=actor,
                       reason=f"extend before={before}s after={after}s",
                       payload={"start": c.start, "end": c.end})
            return _candidate_dict(c)

    def different_crop(self, candidate_id: str, crop_box: list, *, actor: str) -> dict:
        return self.request_edit(candidate_id, {"crop_box": crop_box, "layout": "crop"}, actor=actor)

    # -- render + review --------------------------------------------------
    def start_render(self, candidate_id: str, *, actor: str = "worker") -> dict:
        with session_scope(self._factory) as s:
            c = self._require(s, candidate_id)
            transition(s, c, ClipState.RENDERING, actor=actor, reason="render started")
            return _candidate_dict(c)

    def complete_render(self, candidate_id: str, *, path: str, kind: str = "edit",
                        bucket: str = "edited", edit_plan: Optional[dict] = None,
                        actor: str = "worker") -> dict:
        validate_render_output(path, kind, bucket)
        with session_scope(self._factory) as s:
            c = self._require(s, candidate_id)
            version = ClipVersionRepo(s, self.creator_id).create(
                candidate_id=c.id, stem=c.stem, kind=kind, bucket=bucket,
                path=path, edit_plan=edit_plan,
            )
            transition(s, c, ClipState.READY_FOR_REVIEW, actor=actor,
                       reason="render complete", payload={"version_id": version.id, "path": path})
            result = _candidate_dict(c)
            thread_id = c.discord_thread_id
            version_id = version.id
        # Deliver AFTER the transaction commits, so Discord never references a
        # version that a rolled-back transaction never actually created. Delivery
        # auto-attaches small files and posts a temporary download link for big
        # ones; a Discord hiccup must never lose the completed render.
        try:
            from modules.clip_delivery import deliver_clip
            deliver_clip(path, thread_id=thread_id, version_id=version_id, kind=kind,
                         gateway=self.gateway)
        except Exception as exc:  # noqa: BLE001
            log.warning("render delivery to Discord failed for %s: %s", candidate_id, exc)
        return result

    def mark_render_failed(self, candidate_id: str, *, back_to: str, reason: str = "",
                           actor: str = "worker") -> dict:
        """Roll a failed render back to its request state for another attempt."""
        with session_scope(self._factory) as s:
            c = self._require(s, candidate_id)
            transition(s, c, back_to, actor=actor, reason=f"render failed: {reason}"[:300])
            return _candidate_dict(c)

    # -- review → learning ------------------------------------------------
    def _review_target(self, session, candidate) -> tuple[str, str]:
        """(stem, bucket) the learning signal attaches to — the rendered version's
        file if any, else the candidate itself."""
        versions = ClipVersionRepo(session, self.creator_id).for_candidate(candidate.id)
        if versions:
            v = max(versions, key=lambda x: x.created_at or 0)
            stem = Path(v.path).stem if v.path else v.stem
            return stem, (v.bucket or "output")
        return candidate.stem, "output"

    def _learn(self, stem: str, bucket: str, *, verdict: str,
               tags: Optional[list[str]] = None, notes: str = "") -> None:
        """Turn a clip-room outcome into a review signal so it feeds the learning
        loop (profiler/classifier read clip_reviews.classify_review_signal).
        Non-fatal: a learning hiccup must never break the workflow."""
        try:
            from modules.clip_reviews import save_review
            payload: dict[str, Any] = {"verdict": verdict, "notes": (notes or "")[:1000]}
            if tags:
                payload["tags"] = tags
            save_review(stem, bucket, payload)
        except Exception as exc:  # noqa: BLE001
            log.warning("review-learning record failed for %s: %s", stem, exc)

    def approve(self, candidate_id: str, *, actor: str) -> dict:
        with session_scope(self._factory) as s:
            c = self._require(s, candidate_id)
            transition(s, c, ClipState.APPROVED, actor=actor, reason="approved")
            stem, bucket = self._review_target(s, c)
            result = _candidate_dict(c)
        # Approve = a keeper (positive taste evidence).
        self._learn(stem, bucket, verdict="keeper", notes=f"approved in clip room by {actor}")
        return result

    def request_revision(self, candidate_id: str, notes: str, *, actor: str) -> dict:
        with session_scope(self._factory) as s:
            c = self._require(s, candidate_id)
            transition(s, c, ClipState.REVISION_REQUESTED, actor=actor,
                       reason="revision requested", payload={"notes": notes})
            stem, bucket = self._review_target(s, c)
            result = _candidate_dict(c)
        # Revision = the moment is good but the cut is wrong = BOUNDARY, NOT a bad
        # pick (so it must not become negative training evidence).
        self._learn(stem, bucket, verdict="maybe", tags=["bad trim good clip"], notes=notes)
        return result

    def reject(self, candidate_id: str, *, actor: str, reason: str = "") -> dict:
        with session_scope(self._factory) as s:
            c = self._require(s, candidate_id)
            transition(s, c, ClipState.REJECTED, actor=actor, reason=reason or "rejected")
            stem, bucket = self._review_target(s, c)
            result = _candidate_dict(c)
        # Reject = a miss; the classifier still reads the reason, so a boundary-ish
        # reason is treated as boundary, not a true negative.
        self._learn(stem, bucket, verdict="miss", notes=reason)
        return result

    # -- queries (for the desktop Clip Room viewer) ------------------------
    def get(self, candidate_id: str) -> Optional[dict]:
        with session_scope(self._factory) as s:
            c = ClipCandidateRepo(s, self.creator_id).get(candidate_id)
            return _candidate_dict(c) if c is not None else None

    def by_state(self, state: str, *, limit: Optional[int] = None) -> list[dict]:
        with session_scope(self._factory) as s:
            repo = ClipCandidateRepo(s, self.creator_id)
            return [_candidate_dict(c) for c in repo.by_state(state, limit=limit)]

    def query_candidates(
        self,
        *,
        states: Optional[list[str]] = None,
        q: str = "",
        vod_id: Optional[str] = None,
        min_score: Optional[float] = None,
        max_score: Optional[float] = None,
        min_duration: Optional[float] = None,
        max_duration: Optional[float] = None,
        claimed_by: Optional[str] = None,
        hazard: Optional[bool] = None,
        render_status: str = "any",
        tag: Optional[str] = None,
        sort: str = "score_desc",
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        valid_sorts = {
            "score_desc", "newest", "oldest", "duration_asc",
            "duration_desc", "stream_position", "updated",
        }
        if sort not in valid_sorts:
            raise EditValidationError(f"unknown candidate sort {sort!r}")
        if render_status not in {"any", "rendered", "unrendered"}:
            raise EditValidationError("render_status must be any, rendered, or unrendered")

        wanted_states = {state.strip().upper() for state in (states or []) if state.strip()}
        needle = q.strip().lower()
        wanted_tag = (tag or "").strip().lower()
        wanted_claim = (claimed_by or "").strip().lower()

        with session_scope(self._factory) as session:
            rows = ClipCandidateRepo(session, self.creator_id).list()
            candidates = [_candidate_dict(row) for row in rows]

        def matches(candidate: dict[str, Any]) -> bool:
            duration = max(0.0, float(candidate.get("end") or 0) - float(candidate.get("start") or 0))
            score_value = float(candidate.get("score") or 0)
            if wanted_states and candidate["state"] not in wanted_states:
                return False
            if vod_id and candidate.get("vod_id") != vod_id:
                return False
            if min_score is not None and score_value < min_score:
                return False
            if max_score is not None and score_value > max_score:
                return False
            if min_duration is not None and duration < min_duration:
                return False
            if max_duration is not None and duration > max_duration:
                return False
            if wanted_claim == "__unclaimed__" and candidate.get("claimed_by"):
                return False
            if wanted_claim and wanted_claim != "__unclaimed__" and wanted_claim not in str(candidate.get("claimed_by") or "").lower():
                return False
            if hazard is not None and bool(candidate.get("hazards")) != hazard:
                return False
            if render_status == "rendered" and not candidate.get("has_render"):
                return False
            if render_status == "unrendered" and candidate.get("has_render"):
                return False
            if wanted_tag and wanted_tag not in {str(item).lower() for item in candidate.get("tags") or []}:
                return False
            if needle:
                haystack = " ".join(str(value or "") for value in (
                    candidate.get("stem"), candidate.get("reason"), candidate.get("claimed_by"),
                    candidate.get("vod_stem"), " ".join(candidate.get("hazards") or []),
                    " ".join(candidate.get("tags") or []),
                )).lower()
                if needle not in haystack:
                    return False
            return True

        filtered = [candidate for candidate in candidates if matches(candidate)]
        duration_of = lambda candidate: max(0.0, float(candidate.get("end") or 0) - float(candidate.get("start") or 0))
        sorters = {
            "score_desc": (lambda candidate: (-float(candidate.get("score") or 0), -float(candidate.get("updated_at") or 0))),
            "newest": (lambda candidate: -float(candidate.get("created_at") or 0)),
            "oldest": (lambda candidate: float(candidate.get("created_at") or 0)),
            "duration_asc": duration_of,
            "duration_desc": (lambda candidate: -duration_of(candidate)),
            "stream_position": (lambda candidate: (str(candidate.get("vod_stem") or ""), float(candidate.get("start") or 0))),
            "updated": (lambda candidate: -float(candidate.get("updated_at") or 0)),
        }
        filtered.sort(key=sorters[sort])

        offset = _cursor_offset(cursor)
        page = filtered[offset:offset + limit]
        next_offset = offset + len(page)
        next_cursor = _encode_cursor(next_offset) if next_offset < len(filtered) else None
        state_counts: dict[str, int] = {}
        for candidate in filtered:
            state_counts[candidate["state"]] = state_counts.get(candidate["state"], 0) + 1
        vods = sorted({
            (candidate.get("vod_id"), candidate.get("vod_stem"))
            for candidate in candidates if candidate.get("vod_id") and candidate.get("vod_stem")
        }, key=lambda item: str(item[1]).lower())
        assignees = sorted({str(candidate["claimed_by"]) for candidate in candidates if candidate.get("claimed_by")})
        tags = sorted({str(item) for candidate in candidates for item in candidate.get("tags") or []})
        return {
            "candidates": page,
            "total": len(filtered),
            "next_cursor": next_cursor,
            "facets": {
                "states": state_counts,
                "vods": [{"id": item[0], "stem": item[1]} for item in vods],
                "assignees": assignees,
                "tags": tags,
            },
        }

    def audit_trail(self, candidate_id: str) -> list[dict]:
        with session_scope(self._factory) as s:
            events = WorkflowEventRepo(s, self.creator_id).for_entity("clip_candidate", candidate_id)
            return [
                {
                    "actor": e.actor, "from": e.from_state, "to": e.to_state,
                    "reason": e.reason, "payload": e.payload, "ts": e.ts,
                }
                for e in events
            ]


clip_room = ClipRoom()


__all__ = [
    "ClipRoom",
    "ClipRoomError",
    "EditValidationError",
    "DiscordGateway",
    "NullDiscordGateway",
    "validate_edit_request",
    "build_candidate_card",
    "clip_room",
]
