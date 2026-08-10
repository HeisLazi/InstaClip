"""Phase 2 render worker: orchestration of clip_room + job_store + (stub) editor.

In-memory SQLite, a stub renderer (no ffmpeg/media), a recording gateway.
"""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.base import DEFAULT_CREATOR_ID
from db.job_store import JobStore
from db.models import Base
from db.repository import ClipCandidateRepo, CreatorRepo, VodRepo
from db.state_machine import ClipState
from modules.clip_room import ClipRoom
from modules.render_worker import RenderWorker


class RecordingGateway:
    def __init__(self):
        self.cards = []
        self.results = []
        self.counter = 0

    def post_candidate_card(self, card):
        self.counter += 1
        return {"message_id": f"msg-{self.counter}", "thread_id": f"thr-{self.counter}"}

    def post_render_result(self, thread_id, version):
        self.results.append((thread_id, version))

    def notify(self, message):
        pass


def _factory():
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


class RenderWorkerTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self.factory = _factory()
        self.gw = RecordingGateway()
        self.room = ClipRoom(session_factory=self.factory, gateway=self.gw)
        self.store = JobStore(session_factory=self.factory)
        # A real on-disk VOD file so resolve_vod_path finds it.
        self._tmp = tempfile.TemporaryDirectory()
        self.vod_path = str(Path(self._tmp.name) / "KOA.mp4")
        Path(self.vod_path).write_bytes(b"fake vod")
        with self.factory() as s:
            vod = VodRepo(s).create(stem="KOA", path=self.vod_path)
            cand = ClipCandidateRepo(s).create(
                stem="KOA_001", state=ClipState.DETECTED, score=1.0,
                start=10.0, end=40.0, reason="the bit", vod_id=vod.id,
            )
            s.commit()
            self.cid = cand.id

    def tearDown(self):
        self._tmp.cleanup()

    def _worker(self, renderer):
        return RenderWorker(room=self.room, store=self.store, renderer=renderer,
                            session_factory=self.factory)

    def _to_raw(self):
        self.room.promote(self.cid)
        self.room.send_to_discord(self.cid)
        self.room.claim(self.cid, actor="dave")
        self.room.request_raw(self.cid, actor="dave")

    def _to_edit(self, edit):
        self.room.promote(self.cid)
        self.room.send_to_discord(self.cid)
        self.room.claim(self.cid, actor="dave")
        self.room.request_edit(self.cid, edit, actor="dave")

    def _state(self):
        with self.factory() as s:
            return ClipCandidateRepo(s).get(self.cid).state

    # -- success -----------------------------------------------------------
    def test_raw_render_success_creates_version_and_marks_ready(self):
        self._to_raw()
        calls = []

        def renderer(plan):
            calls.append(plan)
            return {"path": "output/clips/KOA_001.mp4", "stem": "KOA_001", "bucket": "output"}

        out = self._worker(renderer).render_candidate(self.cid, actor="worker")

        self.assertEqual(out["state"], ClipState.READY_FOR_REVIEW)
        # The renderer received a raw plan with the source VOD, stem, and window.
        self.assertEqual(calls[0]["kind"], "raw")
        self.assertEqual(calls[0]["source"], self.vod_path)
        self.assertEqual(calls[0]["stem"], "KOA_001")
        self.assertEqual(calls[0]["spec"]["trim"], {"start": 10.0, "end": 40.0})
        # A ClipVersion was recorded + linked, and the thread was notified.
        with self.factory() as s:
            versions = ClipCandidateRepo(s).get(self.cid).versions
            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0].path, "output/clips/KOA_001.mp4")
            self.assertEqual(versions[0].bucket, "output")  # raw -> output/clips
        self.assertEqual(len(self.gw.results), 1)
        # Durable job recorded as done.
        self.assertEqual(len(self.store.list(status="done", kind="render_clip")), 1)

    def test_edit_render_uses_the_validated_edit_spec(self):
        self._to_edit({"layout": "reaction", "audio_normalize": True})
        captured = {}

        def renderer(plan):
            captured.update(plan["spec"])
            captured["_kind"] = plan["kind"]
            return {"path": "output/edited/e.mp4", "stem": "e", "bucket": "edited"}

        out = self._worker(renderer).render_candidate(self.cid)
        self.assertEqual(out["state"], ClipState.READY_FOR_REVIEW)
        self.assertEqual(captured["_kind"], "edit")
        self.assertEqual(captured["layout"], "reaction")
        self.assertTrue(captured["audio_normalize"])
        self.assertEqual(captured["trim"], {"start": 10.0, "end": 40.0})  # window defaulted in

    # -- failure + retry ---------------------------------------------------
    def test_render_failure_rolls_back_to_request_state(self):
        self._to_raw()

        def renderer(plan):
            raise RuntimeError("ffmpeg boom")

        out = self._worker(renderer).render_candidate(self.cid)
        self.assertEqual(out["state"], ClipState.RAW_REQUESTED)  # rolled back
        with self.factory() as s:
            self.assertEqual(len(ClipCandidateRepo(s).get(self.cid).versions), 0)
        self.assertEqual(len(self.store.list(status="failed", kind="render_clip")), 1)

    def test_retry_after_failure_renders_again(self):
        self._to_raw()
        attempts = {"n": 0}

        def flaky(plan):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("transient")
            return {"path": "output/clips/x.mp4", "stem": "x", "bucket": "output"}

        worker = self._worker(flaky)
        first = worker.render_candidate(self.cid)
        self.assertEqual(first["state"], ClipState.RAW_REQUESTED)   # failed -> back
        second = worker.render_candidate(self.cid)
        self.assertEqual(second["state"], ClipState.READY_FOR_REVIEW)  # retried OK
        self.assertEqual(attempts["n"], 2)

    # -- plan building -----------------------------------------------------
    def test_pending_lists_candidates_awaiting_render(self):
        self._to_raw()
        pending = self._worker(lambda plan: {}).pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["id"], self.cid)

    def test_render_rejects_candidate_not_awaiting_render(self):
        # Still DETECTED — not a renderable state.
        from modules.clip_room import ClipRoomError
        with self.assertRaises(ClipRoomError):
            self._worker(lambda plan: {}).render_candidate(self.cid)


if __name__ == "__main__":
    unittest.main()
