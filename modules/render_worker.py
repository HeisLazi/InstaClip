"""Render worker — turns a requested clip into a rendered version (Phase 2).

This is the integration point the blueprint's milestone #7 ("render callback into
the correct thread") needs. It ties three existing pieces together:

    clip_room  — the lifecycle/state (RAW_REQUESTED / EDIT_REQUESTED -> RENDERING
                 -> READY_FOR_REVIEW, and the Discord thread notification)
    job_store  — durable execution of the actual render (audited, retryable)
    editor     — the real ffmpeg render

Flow for one candidate awaiting render:
    1. Build a render plan from the candidate (window + edit spec + source VOD).
    2. clip_room.start_render -> RENDERING.
    3. job_store.run("render_clip", renderer) — durable, recorded.
    4. on success -> clip_room.complete_render (creates the ClipVersion, notifies
       the thread). on failure -> clip_room.mark_render_failed (rolls back to the
       request state for another attempt).

The actual ffmpeg call is injected as `renderer(source, spec) -> {"path": ...}`,
so the orchestration is fully testable without ffmpeg or real media; the default
renderer calls modules/editor.render_edit.

No `idempotency_key` is used on the render job on purpose: the state machine
already serialises renders per candidate (you can only `start_render` from a
request state), and keying on the request would block a legitimate retry after a
failure. Durability + audit come from the job record itself.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from db.base import DEFAULT_CREATOR_ID, SessionLocal
from db.repository import ClipCandidateRepo, VodRepo, WorkflowEventRepo, session_scope
from db.state_machine import ClipState
from modules.clip_room import ClipRoom, ClipRoomError, clip_room

log = logging.getLogger("render_worker")

Renderer = Callable[[dict], dict]

_RENDERABLE = {ClipState.RAW_REQUESTED, ClipState.EDIT_REQUESTED}


def _default_render(plan: dict) -> dict:
    """Default renderer — dispatches by kind:
      raw  -> cutter.cut_clip   -> output/clips   (a plain trimmed cut)
      edit -> editor.render_edit -> output/edited (layout/captions/audio/fx)
    Not unit-tested (needs media/ffmpeg); the worker injects a stub in tests."""
    source = plan.get("source")
    if not source:
        raise FileNotFoundError("candidate has no source VOD path to render from")
    spec = plan.get("spec") or {}
    src = Path(source)

    if plan.get("kind") == "raw":
        from config import paths
        from modules.cutter.cutter import cut_clip

        trim = spec.get("trim") or {}
        out = paths.CLIPS_DIR / f"{plan['stem']}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        ok = cut_clip(vod_path=src, start=float(trim.get("start", 0.0)),
                      end=float(trim.get("end", 0.0)), output_path=out)
        if not ok:
            raise RuntimeError("raw cut failed")
        return {"path": str(out), "stem": plan["stem"], "bucket": "output"}

    from modules import editor

    out = editor.render_edit(src, spec)
    return {"path": str(out), "stem": out.stem, "bucket": "edited"}


class RenderWorker:
    def __init__(self, room: Optional[ClipRoom] = None, store=None,
                 renderer: Optional[Renderer] = None,
                 session_factory=SessionLocal, creator_id: str = DEFAULT_CREATOR_ID) -> None:
        self.room = room or clip_room
        self._store = store
        self.renderer: Renderer = renderer or _default_render
        self._factory = session_factory
        self.creator_id = creator_id

    @property
    def store(self):
        # Lazy so tests can run without importing the global job_store singleton.
        if self._store is None:
            from db.job_store import job_store
            self._store = job_store
        return self._store

    # -- plan building -----------------------------------------------------
    def _latest_edit_spec(self, session, candidate_id: str) -> dict:
        """The edit spec from the most recent EDIT_REQUESTED event, if any."""
        events = WorkflowEventRepo(session, self.creator_id).for_entity("clip_candidate", candidate_id)
        for ev in reversed(events):
            if ev.to_state == ClipState.EDIT_REQUESTED and ev.payload and "edit" in ev.payload:
                return dict(ev.payload["edit"])
        return {}

    def _resolve_source(self, session, candidate) -> Optional[str]:
        if not candidate.vod_id:
            return None
        vod = VodRepo(session, self.creator_id).get(candidate.vod_id)
        if not (vod and vod.path):
            return None
        # The stored value may be a bare filename — find the real file on disk.
        from modules.vod_resolver import resolve_vod_path
        resolved = resolve_vod_path(vod.path)
        return str(resolved) if resolved else None

    def build_render_plan(self, session, candidate) -> dict:
        state = candidate.state
        if state not in _RENDERABLE:
            raise ClipRoomError(f"candidate {candidate.id} is {state}, not awaiting render")

        window = {"start": candidate.start or 0.0, "end": candidate.end or 0.0}
        if state == ClipState.RAW_REQUESTED:
            kind = "raw"
            spec: dict[str, Any] = {"trim": window}
        else:  # EDIT_REQUESTED
            kind = "edit"
            spec = self._latest_edit_spec(session, candidate.id)
            spec.setdefault("trim", window)  # default the window if the edit omitted it

        return {
            "kind": kind,
            "spec": spec,
            "stem": candidate.stem,
            "source": self._resolve_source(session, candidate),
            "from_state": state,
        }

    # -- orchestration -----------------------------------------------------
    def render_candidate(self, candidate_id: str, *, actor: str = "worker") -> dict:
        with session_scope(self._factory) as s:
            candidate = ClipCandidateRepo(s, self.creator_id).get(candidate_id)
            if candidate is None:
                raise ClipRoomError(f"candidate {candidate_id} not found")
            if candidate.state == ClipState.RENDERING:
                # A render is already in flight (double-click / bot auto-render +
                # manual Render overlapping). Idempotent no-op beats a crash.
                log.info("render_candidate(%s): already RENDERING — skipping duplicate", candidate_id)
                return {"id": candidate.id, "state": candidate.state, "stem": candidate.stem,
                        "duplicate": True}
            plan = self.build_render_plan(s, candidate)

        # REQUEST -> RENDERING (state machine guards against double/concurrent renders).
        self.room.start_render(candidate_id, actor=actor)

        snap = self.store.run(
            "render_clip",
            lambda: self.renderer(plan),
            payload={"candidate_id": candidate_id, "kind": plan["kind"], "source": plan["source"]},
            max_attempts=1,  # render failures are usually deterministic (bad source/spec)
        )

        if snap["status"] == "done":
            result = snap.get("result") or {}
            return self.room.complete_render(
                candidate_id, path=result.get("path", ""), kind=plan["kind"],
                bucket=result.get("bucket", "edited"), edit_plan=plan["spec"], actor=actor,
            )

        # Render failed — roll the candidate back to its request state to retry.
        log.warning("render of %s failed: %s", candidate_id, snap.get("error"))
        return self.room.mark_render_failed(
            candidate_id, back_to=plan["from_state"],
            reason=snap.get("error") or "render failed", actor=actor,
        )

    def pending(self, *, limit: Optional[int] = None) -> list[dict]:
        """Candidates awaiting a render (for a worker poll loop / the UI)."""
        out: list[dict] = []
        for state in (ClipState.RAW_REQUESTED, ClipState.EDIT_REQUESTED):
            out.extend(self.room.by_state(state, limit=limit))
        return out


render_worker = RenderWorker()


__all__ = ["RenderWorker", "render_worker", "Renderer"]
