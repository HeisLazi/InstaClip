"""
Tracks long-running background jobs the user kicked off via the API.
Each job is a Python function run in a worker thread; the manager
broadcasts progress events to subscribers (WebSocket /stream/job/{id}).

A job has:
  - id (uuid4 short)
  - kind (pipeline / batch / train / sync / caption_all / ...)
  - status (queued | running | done | failed | cancelled)
  - progress dict (free-form, last-write-wins)
  - result dict (on done)
  - error string (on failed)
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger("backend.jobs")


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"
    progress: dict = field(default_factory=dict)
    result: Optional[dict] = None
    error: Optional[str] = None
    started_at: float = 0.0
    finished_at: float = 0.0
    cancel_requested: bool = False
    progress_hook: Optional[Callable[[dict], None]] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "kind":             self.kind,
            "status":           self.status,
            "progress":         self.progress,
            "result":           self.result,
            "error":            self.error,
            "started_at":       self.started_at,
            "finished_at":      self.finished_at,
            "cancel_requested": self.cancel_requested,
        }


class JobManager:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._subs: dict[str, set[asyncio.Queue]] = {}
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ---- lifecycle --------------------------------------------------------

    def submit(
        self,
        kind: str,
        fn: Callable[["JobHandle"], dict],
        *,
        job_id: Optional[str] = None,
        progress_hook: Optional[Callable[[dict], None]] = None,
    ) -> Job:
        """
        Submit a job. `fn` receives a JobHandle it can use to publish
        progress and must return a dict (the final result) or raise.
        """
        job_id = job_id or uuid.uuid4().hex[:12]
        job = Job(
            id=job_id,
            kind=kind,
            status="running",
            started_at=time.time(),
            progress_hook=progress_hook,
        )
        with self._lock:
            existing = self._jobs.get(job_id)
            if existing is not None and existing.status == "running":
                return existing
            self._jobs[job_id] = job

        handle = JobHandle(self, job)
        threading.Thread(
            target=self._run, args=(job, handle, fn),
            daemon=True, name=f"job-{kind}-{job_id}",
        ).start()
        return job

    def _run(self, job: Job, handle: "JobHandle", fn: Callable):
        # Make `progress_events.emit(...)` from any deep module route to
        # this job's progress channel, and `check_cancelled()` to this job.
        from utils import progress_events
        progress_events._set_publisher(handle.progress)
        progress_events._set_cancel_checker(lambda: job.cancel_requested)
        try:
            result = fn(handle)
            job.result = result if isinstance(result, dict) else {"value": result}
            job.status = "done"
        except progress_events.JobCancelled:
            log.info(f"Job {job.id} ({job.kind}) cancelled by user.")
            job.status = "cancelled"
        except Exception as e:
            log.error(f"Job {job.id} ({job.kind}) crashed: {e}")
            log.error(traceback.format_exc())
            job.error = str(e)
            job.status = "failed"
        finally:
            progress_events._set_publisher(None)
            progress_events._set_cancel_checker(None)
            job.finished_at = time.time()
            self._broadcast(job, terminal=True)

    def cancel(self, job_id: str) -> bool:
        """
        Request cancellation. The job runner will raise JobCancelled at
        the next emit() checkpoint. Returns False if no such job, True if
        cancel was requested (or already terminal).
        """
        job = self._jobs.get(job_id)
        if job is None:
            return False
        if job.status not in ("running", "queued"):
            return True
        job.cancel_requested = True
        log.info(f"Cancel requested for job {job_id} ({job.kind}).")
        self._broadcast(job)
        return True

    # ---- progress + subscribers ------------------------------------------

    def update_progress(self, job: Job, **fields):
        job.progress.update(fields)
        if job.progress_hook is not None:
            try:
                job.progress_hook(dict(job.progress))
            except Exception as exc:  # persistence must not crash live work
                log.warning("Job %s progress persistence failed: %s", job.id, exc)
        self._broadcast(job)

    def _broadcast(self, job: Job, terminal: bool = False) -> None:
        with self._lock:
            subs = tuple(self._subs.get(job.id, ()))
        if not subs or self._loop is None:
            return
        payload = job.to_dict()
        for q in subs:
            try:
                self._loop.call_soon_threadsafe(q.put_nowait, payload)
            except RuntimeError:
                pass

    def subscribe(self, job_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        with self._lock:
            self._subs.setdefault(job_id, set()).add(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue) -> None:
        with self._lock:
            subs = self._subs.get(job_id)
            if subs:
                subs.discard(q)

    # ---- query ------------------------------------------------------------

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def list_active(self) -> list[Job]:
        return [j for j in self._jobs.values() if j.status == "running"]

    def list_recent(self, n: int = 50) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.started_at, reverse=True)[:n]


class JobHandle:
    """Passed to job functions so they can report progress without
    importing the global manager."""

    def __init__(self, manager: JobManager, job: Job):
        self._m = manager
        self._j = job

    @property
    def id(self) -> str:
        return self._j.id

    def progress(self, **fields: Any) -> None:
        self._m.update_progress(self._j, **fields)


jobs = JobManager()
