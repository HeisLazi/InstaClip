from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.base import Base
from db.job_store import JobStore
from db.repository import ClipCandidateRepo, VodRepo
from modules import tester_profile
from modules.clip_room import ClipRoom
from modules.listener import listener


def _factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


class DurablePipelineTests(unittest.TestCase):
    def test_pipeline_progress_and_result_are_durable(self):
        from backend import durable_pipeline as module

        store = JobStore(session_factory=_factory())
        snapshot = store.enqueue("pipeline", payload={"source": "vod.mp4"}, max_attempts=3)
        service = module.DurablePipelineService()

        class Handle:
            def progress(self, **fields):
                store.progress(snapshot["id"], **fields)

        with (
            patch.object(module, "job_store", store),
            patch("main.run_pipeline", return_value={"success": True, "clips_cut": 2}),
        ):
            result = service._execute(snapshot["id"], Handle())
        self.assertEqual(result["clips_cut"], 2)
        final = store.get(snapshot["id"])
        self.assertEqual(final["status"], "done")

    def test_recovered_pipeline_stays_retryable(self):
        store = JobStore(session_factory=_factory())
        snapshot = store.enqueue("pipeline", payload={"source": "vod.mp4"}, max_attempts=3)
        store.start(snapshot["id"])
        recovered = store.recover_interrupted()
        self.assertEqual(recovered[0]["status"], "queued")

    def test_pipeline_retries_immediately_and_manual_retry_resets_attempts(self):
        from backend import durable_pipeline as module

        store = JobStore(session_factory=_factory())
        snapshot = store.enqueue("pipeline", payload={"source": "vod.mp4"}, max_attempts=2)
        service = module.DurablePipelineService()
        attempts = 0

        class Handle:
            def progress(self, **_fields):
                return None

        def flaky(**_kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary failure")
            return {"success": True, "clips_cut": 1}

        with patch.object(module, "job_store", store), patch("main.run_pipeline", side_effect=flaky):
            result = service._execute(snapshot["id"], Handle())
        self.assertEqual(result["clips_cut"], 1)
        self.assertEqual(attempts, 2)
        self.assertEqual(store.get(snapshot["id"])["status"], "done")


class TranscriptCheckpointTests(unittest.TestCase):
    def test_long_transcript_resumes_completed_chunks(self):
        class Segment:
            start = 1.0
            end = 3.0
            text = " hello "
            words = []

        info = SimpleNamespace(language="en", language_probability=0.9)

        class Model:
            def __init__(self):
                self.calls = 0

            def transcribe(self, *_args, **_kwargs):
                self.calls += 1
                return iter([Segment()]), info

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audio = root / "vod.wav"
            audio.write_bytes(b"audio")
            vod = root / "vod.mp4"
            model = Model()

            def fake_extract(_source, target, _start, _duration):
                target.write_bytes(b"chunk")

            with (
                patch.object(listener.paths, "TRANSCRIPT_CHECKPOINTS_DIR", root / "checkpoints"),
                patch.object(listener, "_audio_duration", return_value=1250.0),
                patch.object(listener, "_extract_checkpoint_chunk", side_effect=fake_extract),
                patch.object(listener.cfg.listener, "checkpoint_seconds", 600),
            ):
                first = listener.transcribe_vod_audio(model, audio, vod)
                calls = model.calls
                second = listener.transcribe_vod_audio(model, audio, vod)
            self.assertTrue(first["checkpointed"])
            self.assertEqual(first["segment_count"], 3)
            self.assertEqual(second["segment_count"], 3)
            self.assertEqual(model.calls, calls)


class ClipRoomQueryTests(unittest.TestCase):
    def test_filters_sorts_facets_and_paginates(self):
        factory = _factory()
        with factory() as session:
            vod = VodRepo(session).create(stem="rocomamas", path="C:/vod.mp4")
            for index, duration in enumerate((2.0, 20.0, 50.0)):
                ClipCandidateRepo(session).create(
                    stem=f"clip_{index}", vod_id=vod.id, state="CANDIDATE",
                    score=0.5 + index / 10, start=index * 60, end=index * 60 + duration,
                    reason="payoff" if index else "filler", hazards=[] if index != 2 else ["rights"],
                )
            session.commit()
        room = ClipRoom(session_factory=factory)
        page = room.query_candidates(states=["CANDIDATE"], min_duration=10, sort="duration_desc", limit=1)
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["candidates"][0]["stem"], "clip_2")
        self.assertIsNotNone(page["next_cursor"])
        next_page = room.query_candidates(states=["CANDIDATE"], min_duration=10, sort="duration_desc", limit=1, cursor=page["next_cursor"])
        self.assertEqual(next_page["candidates"][0]["stem"], "clip_1")
        self.assertEqual(page["facets"]["vods"][0]["stem"], "rocomamas")


class TesterProfileTests(unittest.TestCase):
    def test_profiles_are_isolated_and_boundary_is_not_negative(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(tester_profile, "PROFILE_DIR", Path(temp)):
            first = tester_profile.save_profile("tester-a", {"preset": "default", "traits": ["dry humor"], "preferred_duration": [10, 45]})
            tester_profile.add_feedback("tester-a", {"candidate_id": "one", "signal": "boundary", "notes": "ends early"})
            second = tester_profile.load_profile("tester-b")
            restored = tester_profile.load_profile("tester-a")
        self.assertEqual(first["preset"], "default")
        self.assertEqual(second["preset"], "general")
        self.assertEqual(restored["calibration_feedback"][0]["signal"], "boundary")


if __name__ == "__main__":
    unittest.main()
