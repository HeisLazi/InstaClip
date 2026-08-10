"""Durable, persistent jobs (blueprint Phase 1, milestone #3).

`backend/job_manager.py` is the *runtime* executor: it runs work in threads and
streams live progress to the desktop UI over WebSockets. It is intentionally
in-memory — when the backend restarts, those jobs are gone.

This module is the *durable* counterpart. A `Job` row in the database carries
everything needed to survive a restart: kind, a self-describing `payload`,
attempt counters, and an idempotency key. The two layers are complementary:
use the JobManager for live UX, the JobStore for correctness.

Guarantees:
- **Idempotency** — `enqueue(..., idempotency_key=k)` returns the existing job
  for a key that was already seen; `run()` short-circuits if that job is `done`,
  so the same unit of work is never executed twice.
- **Retry** — `fail()` re-queues while attempts remain, then marks `failed`.
- **Crash recovery** — `recover_interrupted()` reconciles jobs left `running`
  by a hard restart (re-queue if attempts remain, else fail). Call it on boot.
- **Auditability** — every lifecycle change appends a `WorkflowEvent`
  (`entity_type="job"`), the same append-only log the clip state machine uses.

Typical use (durable wrapper around a unit of work):

    from db.job_store import job_store

    snap = job_store.run(
        "render_clip",
        lambda: render_the_clip(candidate),
        idempotency_key=f"render:{candidate.id}",
        payload={"candidate_id": candidate.id},
    )
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from db.base import DEFAULT_CREATOR_ID, SessionLocal
from db.models import Job
from db.repository import JobRepo, WorkflowEventRepo, session_scope

log = logging.getLogger("db.jobs")

JOB_ENTITY = "job"

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"

TERMINAL_STATUSES = frozenset({DONE, FAILED, CANCELLED})


def _job_dict(job: Job) -> dict[str, Any]:
    """Detached snapshot — safe to read after the session closes."""
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "idempotency_key": job.idempotency_key,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "payload": job.payload,
        "progress": job.progress,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _as_result(value: Any) -> Optional[dict]:
    if value is None or isinstance(value, dict):
        return value
    return {"value": value}


class JobError(RuntimeError):
    pass


class JobStore:
    """DB-backed job lifecycle. Each operation runs in its own short transaction
    so state is durable the instant it changes (a crash mid-`run()` leaves a
    recoverable `running` row, not a lost job)."""

    def __init__(self, session_factory=SessionLocal, creator_id: str = DEFAULT_CREATOR_ID) -> None:
        self._factory = session_factory
        self.creator_id = creator_id

    def _repos(self, session):
        return JobRepo(session, self.creator_id), WorkflowEventRepo(session, self.creator_id)

    def _require(self, jobs: JobRepo, job_id: str) -> Job:
        job = jobs.get(job_id)
        if job is None:
            raise JobError(f"job {job_id} not found")
        return job

    # -- enqueue -----------------------------------------------------------
    def enqueue(
        self,
        kind: str,
        *,
        idempotency_key: Optional[str] = None,
        payload: Optional[dict] = None,
        max_attempts: int = 3,
        actor: str = "system",
    ) -> dict:
        with session_scope(self._factory) as s:
            jobs, events = self._repos(s)
            if idempotency_key:
                existing = jobs.by_idempotency(idempotency_key)
                if existing is not None:
                    return _job_dict(existing)
            job = jobs.create(
                kind=kind,
                status=QUEUED,
                idempotency_key=idempotency_key,
                payload=payload,
                max_attempts=max_attempts,
            )
            events.append(
                entity_type=JOB_ENTITY, entity_id=job.id, actor=actor,
                to_state=QUEUED, reason="enqueued",
            )
            return _job_dict(job)

    # -- lifecycle ---------------------------------------------------------
    def start(self, job_id: str, *, actor: str = "system") -> dict:
        with session_scope(self._factory) as s:
            jobs, events = self._repos(s)
            job = self._require(jobs, job_id)
            if job.status != QUEUED:
                raise JobError(f"job {job_id} is {job.status!r}, cannot start")
            jobs.update(job, status=RUNNING, attempts=job.attempts + 1, error=None)
            events.append(
                entity_type=JOB_ENTITY, entity_id=job.id, actor=actor,
                from_state=QUEUED, to_state=RUNNING,
                reason=f"attempt {job.attempts}/{job.max_attempts}",
            )
            return _job_dict(job)

    def complete(self, job_id: str, result: Any = None, *, actor: str = "system") -> dict:
        with session_scope(self._factory) as s:
            jobs, events = self._repos(s)
            job = self._require(jobs, job_id)
            if job.status != RUNNING:
                raise JobError(f"job {job_id} is {job.status!r}, cannot complete")
            jobs.update(job, status=DONE, result=_as_result(result))
            events.append(
                entity_type=JOB_ENTITY, entity_id=job.id, actor=actor,
                from_state=RUNNING, to_state=DONE, reason="completed",
            )
            return _job_dict(job)

    def fail(self, job_id: str, error: str, *, actor: str = "system") -> dict:
        """Record a failure. Re-queues for another attempt while attempts remain,
        otherwise marks the job terminally failed."""
        with session_scope(self._factory) as s:
            jobs, events = self._repos(s)
            job = self._require(jobs, job_id)
            if job.status != RUNNING:
                raise JobError(f"job {job_id} is {job.status!r}, cannot fail")
            retrying = job.attempts < job.max_attempts
            new_status = QUEUED if retrying else FAILED
            jobs.update(job, status=new_status, error=error)
            events.append(
                entity_type=JOB_ENTITY, entity_id=job.id, actor=actor,
                from_state=RUNNING, to_state=new_status,
                reason=("retry scheduled" if retrying else "max attempts reached"),
                payload={"error": error},
            )
            return _job_dict(job)

    def cancel(self, job_id: str, *, actor: str = "system", reason: str = "") -> dict:
        with session_scope(self._factory) as s:
            jobs, events = self._repos(s)
            job = self._require(jobs, job_id)
            if job.status in TERMINAL_STATUSES:
                return _job_dict(job)  # already finished — no-op
            from_state = job.status
            jobs.update(job, status=CANCELLED)
            events.append(
                entity_type=JOB_ENTITY, entity_id=job.id, actor=actor,
                from_state=from_state, to_state=CANCELLED, reason=reason or "cancelled",
            )
            return _job_dict(job)

    def request_cancel(self, job_id: str, *, actor: str = "system", reason: str = "") -> dict:
        """Request cancellation WITHOUT terminating the job.

        A RUNNING job is flagged (a `cancel_requested` marker in progress) but
        stays RUNNING — it's *stopping*, not *stopped*. Only its worker writes the
        terminal CANCELLED (via `cancel()`) once it actually exits at a checkpoint.
        A QUEUED job has no worker to reach a checkpoint, so it's cancelled now.
        Terminal jobs are a no-op.

        This is what lets the API/UI distinguish "Stopping…" from "Stopped" instead
        of the card vanishing while the worker is still running.
        """
        with session_scope(self._factory) as s:
            jobs, events = self._repos(s)
            job = self._require(jobs, job_id)
            if job.status in TERMINAL_STATUSES:
                return _job_dict(job)  # already finished — no-op
            if job.status == QUEUED:
                jobs.update(job, status=CANCELLED)
                events.append(
                    entity_type=JOB_ENTITY, entity_id=job.id, actor=actor,
                    from_state=QUEUED, to_state=CANCELLED,
                    reason=reason or "cancelled before start",
                )
                return _job_dict(job)
            # RUNNING: record the non-terminal request; the worker finalizes.
            merged = dict(job.progress or {})
            merged["cancel_requested"] = True
            merged["cancel_requested_at"] = time.time()
            jobs.update(job, progress=merged)
            events.append(
                entity_type=JOB_ENTITY, entity_id=job.id, actor=actor,
                from_state=job.status, to_state=job.status,
                reason=reason or "cancellation requested",
            )
            return _job_dict(job)

    def retry(self, job_id: str, *, actor: str = "system") -> dict:
        """Explicitly re-queue a terminally failed/cancelled job."""
        with session_scope(self._factory) as s:
            jobs, events = self._repos(s)
            job = self._require(jobs, job_id)
            if job.status not in {FAILED, CANCELLED}:
                return _job_dict(job)
            from_state = job.status
            # Clear any stale cancel-request marker — otherwise the freshly queued
            # job would run while the API/UI still reports "Stopping" and disables Stop.
            progress = dict(job.progress or {})
            progress.pop("cancel_requested", None)
            progress.pop("cancel_requested_at", None)
            jobs.update(job, status=QUEUED, attempts=0, error=None, result=None, progress=progress)
            events.append(
                entity_type=JOB_ENTITY, entity_id=job.id, actor=actor,
                from_state=from_state, to_state=QUEUED, reason="manual retry",
            )
            return _job_dict(job)

    def progress(self, job_id: str, **fields: Any) -> dict:
        """Merge `fields` into the job's progress json (last-write-wins per key)."""
        with session_scope(self._factory) as s:
            jobs, _ = self._repos(s)
            job = self._require(jobs, job_id)
            merged = dict(job.progress or {})
            merged.update(fields)
            jobs.update(job, progress=merged)  # reassign so SQLAlchemy sees the change
            return _job_dict(job)

    # -- queries -----------------------------------------------------------
    def get(self, job_id: str) -> Optional[dict]:
        with session_scope(self._factory) as s:
            jobs, _ = self._repos(s)
            job = jobs.get(job_id)
            return _job_dict(job) if job is not None else None

    def list(self, *, status: Optional[str] = None, kind: Optional[str] = None) -> list[dict]:
        with session_scope(self._factory) as s:
            jobs, _ = self._repos(s)
            filters: dict[str, Any] = {}
            if status is not None:
                filters["status"] = status
            if kind is not None:
                filters["kind"] = kind
            return [_job_dict(j) for j in jobs.list(**filters)]

    # -- recovery ----------------------------------------------------------
    def recover_interrupted(self, *, actor: str = "system") -> list[dict]:
        """Reconcile jobs left `running` by a hard restart. Re-queue those with
        attempts remaining, terminally fail the rest. Returns the affected jobs.
        Call this once on backend startup."""
        recovered: list[dict] = []
        with session_scope(self._factory) as s:
            jobs, events = self._repos(s)
            for job in jobs.list(status=RUNNING):
                # If the user requested cancellation before the crash, honor it —
                # do NOT restart work they explicitly cancelled.
                if (job.progress or {}).get("cancel_requested"):
                    jobs.update(job, status=CANCELLED)
                    events.append(
                        entity_type=JOB_ENTITY, entity_id=job.id, actor=actor,
                        from_state=RUNNING, to_state=CANCELLED,
                        reason="cancellation honored after restart",
                    )
                    recovered.append(_job_dict(job))
                    continue
                retrying = job.attempts < job.max_attempts
                new_status = QUEUED if retrying else FAILED
                error = None if retrying else "interrupted by restart; max attempts reached"
                jobs.update(job, status=new_status, error=error or job.error)
                events.append(
                    entity_type=JOB_ENTITY, entity_id=job.id, actor=actor,
                    from_state=RUNNING, to_state=new_status,
                    reason="recovered after restart",
                )
                recovered.append(_job_dict(job))
        if recovered:
            log.info("recovered %d interrupted job(s) after restart", len(recovered))
        return recovered

    # -- durable execution -------------------------------------------------
    def run(
        self,
        kind: str,
        fn,
        *,
        idempotency_key: Optional[str] = None,
        payload: Optional[dict] = None,
        max_attempts: int = 3,
        actor: str = "system",
    ) -> dict:
        """Execute `fn()` inside the durable lifecycle, synchronously.

        Idempotent: if a job with the same key already completed, returns it
        without re-running. Retries `fn` up to `max_attempts` on exception,
        recording each attempt. Returns the final job snapshot.
        """
        snap = self.enqueue(
            kind, idempotency_key=idempotency_key, payload=payload,
            max_attempts=max_attempts, actor=actor,
        )
        if snap["status"] != QUEUED:
            # done (idempotent hit), running (in-flight elsewhere), or terminal —
            # never execute again under the same key.
            return snap

        job_id = snap["id"]
        while True:
            self.start(job_id, actor=actor)
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001 — failure is recorded, not swallowed
                snap = self.fail(job_id, f"{type(exc).__name__}: {exc}", actor=actor)
                if snap["status"] != QUEUED:
                    log.warning("job %s (%s) failed after %d attempts", job_id, kind, snap["attempts"])
                    return snap
                continue  # re-queued — try again
            return self.complete(job_id, _as_result(result), actor=actor)


# Module-level singleton mirrors `jobs = JobManager()` in backend/job_manager.py.
job_store = JobStore()


__all__ = [
    "JobStore",
    "JobError",
    "job_store",
    "JOB_ENTITY",
    "QUEUED",
    "RUNNING",
    "DONE",
    "FAILED",
    "CANCELLED",
    "TERMINAL_STATUSES",
]
