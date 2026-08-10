"""Phase 1 durable jobs: idempotency, retry, crash recovery, audit log.

In-memory SQLite only — never touches the real data/heislazi.db.
"""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.base import DEFAULT_CREATOR_ID
from db.job_store import (
    CANCELLED,
    DONE,
    FAILED,
    QUEUED,
    RUNNING,
    JobError,
    JobStore,
)
from db.models import Base
from db.repository import CreatorRepo, WorkflowEventRepo


def _fresh_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    s = Session()
    CreatorRepo(s).ensure(DEFAULT_CREATOR_ID, DEFAULT_CREATOR_ID, "HeisLazi")
    s.commit()
    s.close()
    return Session


class RequestCancelTests(unittest.TestCase):
    """Cancellation must distinguish STOPPING (requested, worker still exiting)
    from STOPPED (terminal). Regression for the 'card vanishes mid-work' bug."""

    def setUp(self):
        self.factory = _fresh_factory()
        self.store = JobStore(session_factory=self.factory)

    def test_request_cancel_on_running_job_is_non_terminal(self):
        snap = self.store.enqueue("pipeline", payload={"source": "KOA"})
        self.store.start(snap["id"])
        stopping = self.store.request_cancel(snap["id"], actor="desktop")
        # STOPPING: still running, but flagged. Not terminal.
        self.assertEqual(stopping["status"], RUNNING)
        self.assertTrue(stopping["progress"].get("cancel_requested"))
        self.assertNotEqual(stopping["status"], CANCELLED)

    def test_worker_finalizes_to_cancelled_after_request(self):
        snap = self.store.enqueue("pipeline", payload={"source": "KOA"})
        self.store.start(snap["id"])
        self.store.request_cancel(snap["id"], actor="desktop")   # request (stopping)
        stopped = self.store.cancel(snap["id"], actor="worker")  # worker exits (stopped)
        self.assertEqual(stopped["status"], CANCELLED)
        # the request marker is preserved through finalization
        self.assertTrue(stopped["progress"].get("cancel_requested"))

    def test_public_snapshot_reports_stopping_then_stopped(self):
        from backend.durable_pipeline import public_snapshot
        snap = self.store.enqueue("pipeline", payload={"source": "KOA"})
        self.store.start(snap["id"])
        self.store.request_cancel(snap["id"], actor="desktop")
        stopping = public_snapshot(self.store.get(snap["id"]))
        self.assertEqual(stopping["status"], RUNNING)      # card stays visible
        self.assertTrue(stopping["cancel_requested"])      # UI shows "Stopping…"
        self.assertEqual(stopping["finished_at"], 0.0)     # not finished yet
        self.store.cancel(snap["id"], actor="worker")
        stopped = public_snapshot(self.store.get(snap["id"]))
        self.assertEqual(stopped["status"], CANCELLED)     # now "Stopped"
        self.assertGreater(stopped["finished_at"], 0.0)

    def test_request_cancel_on_queued_job_finalizes_immediately(self):
        # No worker will ever reach a checkpoint, so a queued cancel is terminal now.
        snap = self.store.enqueue("pipeline", payload={"source": "KOA"})
        result = self.store.request_cancel(snap["id"], actor="desktop")
        self.assertEqual(result["status"], CANCELLED)

    def test_request_cancel_on_terminal_job_is_noop(self):
        snap = self.store.enqueue("pipeline", payload={"source": "KOA"})
        self.store.start(snap["id"])
        self.store.complete(snap["id"], {"ok": True})
        result = self.store.request_cancel(snap["id"])
        self.assertEqual(result["status"], DONE)  # unchanged

    def test_retry_clears_cancel_marker(self):
        # A retried job must NOT start life flagged as stopping.
        snap = self.store.enqueue("pipeline", payload={"source": "KOA"})
        self.store.start(snap["id"])
        self.store.request_cancel(snap["id"])
        self.store.cancel(snap["id"], actor="worker")   # now terminally cancelled
        retried = self.store.retry(snap["id"])
        self.assertEqual(retried["status"], QUEUED)
        self.assertNotIn("cancel_requested", retried["progress"])

    def test_recover_honors_cancellation_instead_of_restarting(self):
        # App closed mid-"stopping": recovery must finalize CANCELLED, not requeue.
        snap = self.store.enqueue("pipeline", payload={"source": "KOA"})
        self.store.start(snap["id"])
        self.store.request_cancel(snap["id"])   # RUNNING + marker, worker never exited
        recovered = self.store.recover_interrupted()
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["status"], CANCELLED)

    def test_recover_requeues_normal_running_job(self):
        # A plain interrupted RUNNING job (no cancel) still recovers to QUEUED.
        snap = self.store.enqueue("pipeline", payload={"source": "KOA"})
        self.store.start(snap["id"])
        recovered = self.store.recover_interrupted()
        self.assertEqual(recovered[0]["status"], QUEUED)


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        self.factory = _fresh_factory()
        self.store = JobStore(session_factory=self.factory)

    def _events(self, job_id):
        with self.factory() as s:
            return WorkflowEventRepo(s).for_entity("job", job_id)

    # -- enqueue / idempotency --------------------------------------------
    def test_enqueue_creates_queued_job_and_logs_event(self):
        snap = self.store.enqueue("transcribe", payload={"vod": "KOA"})
        self.assertEqual(snap["status"], QUEUED)
        self.assertEqual(snap["payload"], {"vod": "KOA"})
        events = self._events(snap["id"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].to_state, QUEUED)

    def test_enqueue_is_idempotent_on_key(self):
        a = self.store.enqueue("render", idempotency_key="render:HNG_16")
        b = self.store.enqueue("render", idempotency_key="render:HNG_16")
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(len(self.store.list(kind="render")), 1)

    # -- happy path --------------------------------------------------------
    def test_start_complete_lifecycle(self):
        job = self.store.enqueue("render")
        self.store.start(job["id"])
        done = self.store.complete(job["id"], {"path": "output/edited/x.mp4"})
        self.assertEqual(done["status"], DONE)
        self.assertEqual(done["attempts"], 1)
        self.assertEqual(done["result"], {"path": "output/edited/x.mp4"})
        states = [e.to_state for e in self._events(job["id"])]
        self.assertEqual(states, [QUEUED, RUNNING, DONE])

    def test_cannot_complete_a_job_that_is_not_running(self):
        job = self.store.enqueue("render")
        with self.assertRaises(JobError):
            self.store.complete(job["id"])

    # -- retry / failure ---------------------------------------------------
    def test_fail_requeues_while_attempts_remain_then_fails(self):
        job = self.store.enqueue("render", max_attempts=2)
        self.store.start(job["id"])
        first = self.store.fail(job["id"], "boom")
        self.assertEqual(first["status"], QUEUED)  # attempt 1 of 2 -> retry
        self.store.start(job["id"])
        second = self.store.fail(job["id"], "boom again")
        self.assertEqual(second["status"], FAILED)  # attempt 2 of 2 -> terminal
        self.assertEqual(second["attempts"], 2)
        self.assertEqual(second["error"], "boom again")

    # -- progress ----------------------------------------------------------
    def test_progress_merges_fields(self):
        job = self.store.enqueue("transcribe")
        self.store.progress(job["id"], pct=10)
        snap = self.store.progress(job["id"], pct=55, stage="whisper")
        self.assertEqual(snap["progress"], {"pct": 55, "stage": "whisper"})

    # -- cancel ------------------------------------------------------------
    def test_cancel_then_cancel_is_noop(self):
        job = self.store.enqueue("render")
        c1 = self.store.cancel(job["id"], reason="user stopped it")
        self.assertEqual(c1["status"], CANCELLED)
        c2 = self.store.cancel(job["id"])  # already terminal
        self.assertEqual(c2["status"], CANCELLED)
        # Only one cancel event recorded (second was a no-op).
        cancel_events = [e for e in self._events(job["id"]) if e.to_state == CANCELLED]
        self.assertEqual(len(cancel_events), 1)

    # -- durable run() -----------------------------------------------------
    def test_run_executes_and_completes(self):
        snap = self.store.run("render", lambda: {"path": "x.mp4"})
        self.assertEqual(snap["status"], DONE)
        self.assertEqual(snap["result"], {"path": "x.mp4"})

    def test_run_retries_until_success(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ValueError("not yet")
            return "ok"

        snap = self.store.run("render", flaky, max_attempts=3)
        self.assertEqual(snap["status"], DONE)
        self.assertEqual(calls["n"], 3)
        self.assertEqual(snap["result"], {"value": "ok"})

    def test_run_gives_up_after_max_attempts(self):
        calls = {"n": 0}

        def always_fails():
            calls["n"] += 1
            raise RuntimeError("nope")

        snap = self.store.run("render", always_fails, max_attempts=2)
        self.assertEqual(snap["status"], FAILED)
        self.assertEqual(calls["n"], 2)
        self.assertIn("nope", snap["error"])

    def test_run_is_idempotent_after_success(self):
        calls = {"n": 0}

        def work():
            calls["n"] += 1
            return {"done": True}

        a = self.store.run("render", work, idempotency_key="k1")
        b = self.store.run("render", work, idempotency_key="k1")
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(calls["n"], 1)  # second call short-circuited — no re-run
        self.assertEqual(b["status"], DONE)

    # -- crash recovery ----------------------------------------------------
    def test_recover_interrupted_requeues_when_attempts_remain(self):
        job = self.store.enqueue("render", max_attempts=3)
        self.store.start(job["id"])  # now RUNNING, attempts=1 — simulate a crash here
        recovered = self.store.recover_interrupted()
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["status"], QUEUED)
        self.assertEqual(self.store.get(job["id"])["status"], QUEUED)

    def test_recover_interrupted_fails_when_attempts_exhausted(self):
        job = self.store.enqueue("render", max_attempts=1)
        self.store.start(job["id"])  # attempts=1 == max — a crash here is unrecoverable
        recovered = self.store.recover_interrupted()
        self.assertEqual(recovered[0]["status"], FAILED)
        self.assertIn("interrupted by restart", self.store.get(job["id"])["error"])

    def test_recover_is_noop_when_nothing_running(self):
        self.store.enqueue("render")  # queued, not running
        self.assertEqual(self.store.recover_interrupted(), [])


if __name__ == "__main__":
    unittest.main()
