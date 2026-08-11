"""Phase 2 pipeline -> Clip Room sync: ingest + auto-promote top-N.

In-memory SQLite + temp metadata files. No real pipeline / ffmpeg.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.base import DEFAULT_CREATOR_ID
from db.models import Base
from db.repository import ClipCandidateRepo, CreatorRepo, VodRepo
from db.state_machine import ClipState
from modules import pipeline_sync


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


def _write_meta(tmp: Path, stem: str, n_highlights: int):
    highlights = {
        "vod": f"{stem}.mp4",
        "highlights": [
            {"start": float(i * 100), "end": float(i * 100 + 30),
             "peak_score": round(0.5 + i * 0.05, 2), "peak_text": f"moment {i}",
             "triggers": ["x"], "clip_id": f"{stem}_{i:03d}", "vod_name": f"{stem}.mp4"}
            for i in range(n_highlights)
        ],
    }
    (tmp / f"{stem}_highlights.json").write_text(json.dumps(highlights), encoding="utf-8")
    # Cut results for the first two, using GEN_-style ids (different from clip_id).
    results = {
        "vod": f"{stem}.mp4", "total_cut": 2, "total_failed": 0,
        "clips": [
            {"clip_id": f"GEN_{stem}_a", "output": f"output/clips/GEN_{stem}_a.mp4",
             "success": True, "start": 0.0, "end": 30.0},
            {"clip_id": f"GEN_{stem}_b", "output": f"output/clips/GEN_{stem}_b.mp4",
             "success": True, "start": 100.0, "end": 130.0},
        ],
    }
    (tmp / f"{stem}_results.json").write_text(json.dumps(results), encoding="utf-8")


class PipelineSyncTests(unittest.TestCase):
    def setUp(self):
        self.factory = _factory()

    def test_sync_ingests_and_promotes_top_n(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            _write_meta(tmpdir, "KOA", n_highlights=10)
            report = pipeline_sync.sync_vod(
                "KOA.mp4", auto_promote_top=3, metadata_dir=tmpdir, factory=self.factory,
            )

        self.assertEqual(report["candidates"], 10)
        self.assertEqual(report["versions"], 2)
        self.assertEqual(report["promoted"], 3)

        with self.factory() as s:
            cands = ClipCandidateRepo(s)
            promoted = cands.by_state(ClipState.CANDIDATE)
            self.assertEqual(len(promoted), 3)
            # The promoted ones are the three highest-scoring (last indices).
            promoted_scores = sorted((c.score for c in promoted), reverse=True)
            self.assertEqual(promoted_scores, [0.95, 0.90, 0.85])
            self.assertEqual(len(cands.by_state(ClipState.DETECTED)), 7)

    def test_sync_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            _write_meta(tmpdir, "KOA", n_highlights=5)
            pipeline_sync.sync_vod("KOA.mp4", auto_promote_top=2,
                                   metadata_dir=tmpdir, factory=self.factory)
            second = pipeline_sync.sync_vod("KOA.mp4", auto_promote_top=2,
                                            metadata_dir=tmpdir, factory=self.factory)

        self.assertEqual(second["candidates"], 0)  # nothing new
        self.assertEqual(second["versions"], 0)
        self.assertEqual(second["promoted"], 0)  # top-N already promoted, no creep
        with self.factory() as s:
            self.assertEqual(ClipCandidateRepo(s).count(), 5)  # no duplicates
            self.assertEqual(VodRepo(s).count(), 1)
            # Exactly the top-2 are promoted — not 4 from re-running.
            self.assertEqual(len(ClipCandidateRepo(s).by_state(ClipState.CANDIDATE)), 2)

    def test_promoted_versions_link_to_candidates_by_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            _write_meta(tmpdir, "KOA", n_highlights=5)
            pipeline_sync.sync_vod("KOA.mp4", auto_promote_top=2,
                                   metadata_dir=tmpdir, factory=self.factory)
        with self.factory() as s:
            cands = ClipCandidateRepo(s)
            c0 = cands.get_by_stem("KOA_000")  # start 0.0 -> GEN_KOA_a
            self.assertEqual(len(c0.versions), 1)
            self.assertEqual(c0.versions[0].path, "output/clips/GEN_KOA_a.mp4")

    def test_sync_stores_full_vod_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            _write_meta(tmpdir, "KOA", n_highlights=2)
            pipeline_sync.sync_vod(
                "KOA.mp4", vod_path=r"D:/streams/KOA.mp4",
                metadata_dir=tmpdir, factory=self.factory, auto_promote_top=0,
            )
        with self.factory() as s:
            self.assertEqual(VodRepo(s).get_by_stem("KOA").path, r"D:/streams/KOA.mp4")

    def test_backfill_resolves_bare_filenames(self):
        from db.migrate_json import backfill_vod_paths
        from modules import vod_resolver

        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "KOA.mp4"
            real.write_bytes(b"v")
            with self.factory() as s:
                VodRepo(s).create(stem="KOA", path="KOA.mp4")  # bare filename
                s.commit()
            with patch.object(vod_resolver, "_search_dirs", return_value=[Path(tmp)]):
                res = backfill_vod_paths(factory=self.factory)
            self.assertEqual(res["fixed"], 1)
            with self.factory() as s:
                self.assertEqual(VodRepo(s).get_by_stem("KOA").path, str(real))

    def test_missing_highlights_file_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = pipeline_sync.sync_vod(
                "NOPE.mp4", metadata_dir=Path(tmp), factory=self.factory,
            )
        self.assertEqual(report, {"vod": "NOPE", "candidates": 0, "versions": 0, "promoted": 0})


if __name__ == "__main__":
    unittest.main()
