"""Phase 1 JSON->DB migration: correctness + row-level idempotency.

Each importer is tested against temp JSON fixtures on an in-memory SQLite engine,
so it never touches the real data/heislazi.db or the real metadata files.
"""

import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db import migrate_json
from db.base import DEFAULT_CREATOR_ID
from db.models import Base
from db.repository import (
    ClipCandidateRepo,
    ClipVersionRepo,
    CreatorRepo,
    VodRepo,
    WorkflowEventRepo,
)
from db.state_machine import ClipState


def _session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    s = Session()
    CreatorRepo(s).ensure(DEFAULT_CREATOR_ID, DEFAULT_CREATOR_ID, "HeisLazi")
    s.commit()
    return s


def _write(tmp: Path, name: str, payload: dict) -> Path:
    p = tmp / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


HIGHLIGHTS = {
    "vod": "KOA HARIZZMENT.mp4",
    "highlights": [
        {"start": 10.0, "end": 40.0, "peak_score": 0.92, "peak_text": "the bencho bit",
         "triggers": ["semantic", "repetition"], "clip_id": "KOA_001", "vod_name": "KOA HARIZZMENT.mp4"},
        {"start": 90.0, "end": 120.0, "peak_score": 0.7, "peak_text": "shanyok prank",
         "triggers": ["keyword_spike"], "clip_id": "KOA_002", "vod_name": "KOA HARIZZMENT.mp4"},
    ],
}

# NOTE: results use a DIFFERENT id scheme (GEN_<slug>) than highlights (<vod>_NNN),
# exactly like the real data. The link back to a candidate is by start time, not id.
RESULTS = {
    "vod": "KOA HARIZZMENT.mp4",
    "total_cut": 1,
    "total_failed": 1,
    "clips": [
        {"clip_id": "GEN_0.92_the_bencho_bit", "output": "output/clips/GEN_0.92_the_bencho_bit.mp4",
         "success": True, "start": 10.0, "end": 40.0, "score": 0.92},
        {"clip_id": "GEN_0.70_shanyok_prank", "output": "", "success": False,
         "start": 90.0, "end": 120.0},  # failed cut -> skipped
    ],
}

REVIEWS = {
    "version": 1,
    "reviews": {
        "GEN_x": {"bucket": "negatives", "rating": 1, "verdict": "miss",
                  "notes": "aint a clip", "stem": "GEN_x"},
        "GEN_y": {"bucket": "positives", "rating": 5, "verdict": "keeper",
                  "notes": "tough", "stem": "GEN_y"},
    },
}


class HighlightsImportTests(unittest.TestCase):
    def setUp(self):
        self.s = _session()

    def tearDown(self):
        self.s.close()

    def test_imports_vod_and_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(Path(tmp), "KOA_highlights.json", HIGHLIGHTS)
            res = migrate_json.import_highlights_file(self.s, p)
            self.s.commit()
        self.assertEqual(res["created"], 2)
        self.assertEqual(VodRepo(self.s).count(), 1)
        cands = ClipCandidateRepo(self.s)
        self.assertEqual(cands.count(), 2)
        c1 = cands.get_by_stem("KOA_001")
        self.assertEqual(c1.state, ClipState.DETECTED)
        self.assertEqual(c1.score, 0.92)
        self.assertEqual(c1.hazards, [])  # triggers are NOT hazards
        self.assertIsNotNone(c1.vod_id)

    def test_reimport_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(Path(tmp), "KOA_highlights.json", HIGHLIGHTS)
            migrate_json.import_highlights_file(self.s, p)
            self.s.commit()
            res2 = migrate_json.import_highlights_file(self.s, p)
            self.s.commit()
        self.assertEqual(res2["created"], 0)
        self.assertEqual(res2["skipped"], 2)
        self.assertEqual(ClipCandidateRepo(self.s).count(), 2)  # no duplicates


class ResultsImportTests(unittest.TestCase):
    def setUp(self):
        self.s = _session()

    def tearDown(self):
        self.s.close()

    def test_only_successful_clips_become_versions_and_link_by_start_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            hp = _write(Path(tmp), "KOA_highlights.json", HIGHLIGHTS)
            rp = _write(Path(tmp), "KOA_results.json", RESULTS)
            migrate_json.import_highlights_file(self.s, hp)
            self.s.commit()
            res = migrate_json.import_results_file(self.s, rp)
            self.s.commit()
        self.assertEqual(res["created"], 1)   # the failed cut -> not a version
        self.assertEqual(res["skipped"], 1)
        versions = ClipVersionRepo(self.s)
        self.assertEqual(versions.count(), 1)
        v = versions.list(stem="GEN_0.92_the_bencho_bit")[0]
        self.assertEqual(v.kind, "raw")
        self.assertEqual(v.path, "output/clips/GEN_0.92_the_bencho_bit.mp4")
        # Linked to the candidate by START TIME (10.0) despite mismatched ids.
        cand = ClipCandidateRepo(self.s).get_by_stem("KOA_001")
        self.assertEqual(v.candidate_id, cand.id)

    def test_results_reimport_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            rp = _write(Path(tmp), "KOA_results.json", RESULTS)
            migrate_json.import_results_file(self.s, rp)
            self.s.commit()
            res2 = migrate_json.import_results_file(self.s, rp)
            self.s.commit()
        self.assertEqual(res2["created"], 0)
        self.assertEqual(ClipVersionRepo(self.s).count(), 1)


class ReviewsImportTests(unittest.TestCase):
    def setUp(self):
        self.s = _session()

    def tearDown(self):
        self.s.close()

    def test_reviews_become_append_only_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(Path(tmp), "clip_reviews.json", REVIEWS)
            res = migrate_json.import_reviews(self.s, p)
            self.s.commit()
        self.assertEqual(res["created"], 2)
        events = WorkflowEventRepo(self.s)
        miss = events.for_entity("review", "GEN_x")
        self.assertEqual(len(miss), 1)
        self.assertEqual(miss[0].to_state, "miss")
        self.assertEqual(miss[0].payload["notes"], "aint a clip")  # lossless

    def test_reviews_reimport_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write(Path(tmp), "clip_reviews.json", REVIEWS)
            migrate_json.import_reviews(self.s, p)
            self.s.commit()
            res2 = migrate_json.import_reviews(self.s, p)
            self.s.commit()
        self.assertEqual(res2["created"], 0)
        self.assertEqual(res2["skipped"], 2)
        self.assertEqual(WorkflowEventRepo(self.s).count(), 2)


if __name__ == "__main__":
    unittest.main()
