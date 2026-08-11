"""Durable execution wrapper for long-running VOD pipeline jobs."""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from backend.job_manager import JobHandle, jobs
from db.job_store import CANCELLED, DONE, QUEUED, RUNNING, job_store

log = logging.getLogger("backend.durable_pipeline")

DURABLE_KINDS = frozenset({"pipeline", "batch"})


def _source_fingerprint(source: str) -> str:
    path = Path(source)
    if path.is_file():
        stat = path.stat()
        identity = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
    else:
        identity = source
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def public_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    created = float(snapshot.get("created_at") or 0.0)
    updated = float(snapshot.get("updated_at") or created)
    status = str(snapshot.get("status") or QUEUED)
    progress = snapshot.get("progress") or {}
    # A running job with the marker set is STOPPING (worker still exiting), not
    # STOPPED. `status` stays "running" and finished_at stays 0 until the worker
    # actually writes the terminal CANCELLED — that's what lets the UI show
    # "Stopping…" and keep the card visible instead of dropping it mid-work.
    # Only surface cancel_requested for RUNNING (stopping) or CANCELLED (stopped);
    # a QUEUED/DONE/FAILED job must never read as stopping (e.g. a stale marker).
    if status == CANCELLED:
        cancel_requested = True
    elif status == RUNNING:
        cancel_requested = bool(progress.get("cancel_requested"))
    else:
        cancel_requested = False
    return {
        "id": snapshot["id"],
        "kind": snapshot["kind"],
        "status": status,
        "progress": progress,
        "result": snapshot.get("result"),
        "error": snapshot.get("error"),
        "started_at": created,
        "finished_at": updated if status in {DONE, "failed", CANCELLED} else 0.0,
        "cancel_requested": cancel_requested,
        "attempts": int(snapshot.get("attempts") or 0),
        "max_attempts": int(snapshot.get("max_attempts") or 0),
        "recoverable": status == QUEUED,
        "durable": True,
    }


class DurablePipelineService:
    def submit(self, source: str, *, force: bool = False) -> dict[str, Any]:
        suffix = uuid.uuid4().hex if force else _source_fingerprint(source)
        snapshot = job_store.enqueue(
            "pipeline",
            idempotency_key=f"pipeline:v2:{suffix}",
            payload={"source": source, "submitted_at": time.time()},
            max_attempts=3,
            actor="desktop",
        )
        if snapshot["status"] == QUEUED:
            self.launch(snapshot["id"])
        return public_snapshot(snapshot)

    def launch(self, job_id: str) -> Optional[dict[str, Any]]:
        snapshot = job_store.get(job_id)
        if snapshot is None or snapshot["kind"] not in DURABLE_KINDS:
            return None
        if snapshot["status"] != QUEUED:
            return public_snapshot(snapshot)

        jobs.submit(
            snapshot["kind"],
            lambda handle: self._execute(job_id, handle),
            job_id=job_id,
            progress_hook=lambda progress: self._persist_progress(job_id, progress),
        )
        return public_snapshot(snapshot)

    def _persist_progress(self, job_id: str, progress: dict[str, Any]) -> None:
        snapshot = job_store.get(job_id)
        if snapshot and snapshot["status"] == RUNNING:
            job_store.progress(job_id, **progress)

    def _execute(self, job_id: str, handle: JobHandle) -> dict[str, Any]:
        initial = job_store.get(job_id) or {}
        payload = initial.get("payload") or {}
        source = str(payload.get("source") or "")
        if not source:
            raise RuntimeError("missing durable pipeline source")

        from main import run_pipeline
        from utils.progress_events import JobCancelled

        while True:
            snapshot = job_store.start(job_id, actor="worker")
            try:
                handle.progress(stage="starting", source=source, durable=True, attempt=snapshot["attempts"])
                result = run_pipeline(source=source, interactive=False) or {}
                if not result.get("success"):
                    raise RuntimeError(str(result.get("error") or "pipeline did not complete"))
                job_store.complete(job_id, result, actor="worker")
                return result
            except JobCancelled:
                job_store.cancel(job_id, actor="worker", reason="cancelled during execution")
                raise
            except Exception as exc:
                failed = job_store.fail(job_id, f"{type(exc).__name__}: {exc}", actor="worker")
                if failed["status"] == QUEUED:
                    handle.progress(stage="retrying", source=source, durable=True, attempt=failed["attempts"] + 1)
                    continue
                raise

    def resume_queued(self) -> list[str]:
        launched: list[str] = []
        for snapshot in job_store.list(status=QUEUED):
            if snapshot["kind"] in DURABLE_KINDS and self.launch(snapshot["id"]):
                launched.append(snapshot["id"])
        if launched:
            log.info("Resumed %d durable pipeline job(s)", len(launched))
        return launched

    def get(self, job_id: str) -> Optional[dict[str, Any]]:
        snapshot = job_store.get(job_id)
        return public_snapshot(snapshot) if snapshot else None

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        snapshots = [public_snapshot(item) for item in job_store.list() if item["kind"] in DURABLE_KINDS]
        return sorted(snapshots, key=lambda item: item["started_at"], reverse=True)[:limit]

    def cancel(self, job_id: str) -> bool:
        snapshot = job_store.get(job_id)
        if snapshot is None:
            return False
        jobs.cancel(job_id)  # trip the runtime flag → check_cancelled() raises at the next checkpoint
        if snapshot["status"] not in {DONE, "failed", CANCELLED}:
            # Non-terminal REQUEST only. The worker writes terminal CANCELLED from
            # its `except JobCancelled` path when it actually exits (see _execute).
            job_store.request_cancel(job_id, actor="desktop")
        return True

    def retry(self, job_id: str) -> Optional[dict[str, Any]]:
        snapshot = job_store.get(job_id)
        if snapshot is None:
            return None
        if snapshot["status"] in {"failed", CANCELLED}:
            snapshot = job_store.retry(job_id, actor="desktop")
        if snapshot["status"] != QUEUED:
            return public_snapshot(snapshot)
        return self.launch(job_id)


durable_pipeline = DurablePipelineService()
