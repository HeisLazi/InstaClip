"""Phase 2 candidate preview resolution: version / cached / render / no-source.

In-memory SQLite + temp dirs; the ffmpeg cut is stubbed (no media needed).
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.base import DEFAULT_CREATOR_ID
from db.models import Base
from db.repository import ClipCandidateRepo, ClipVersionRepo, CreatorRepo, VodRepo
from modules import clip_preview


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


class ClipPreviewTests(unittest.TestCase):
    def setUp(self):
        self.factory = _factory()

    def _candidate(self, *, vod_path=None, start=10.0, end=40.0):
        with self.factory() as s:
            vod_id = None
            if vod_path is not None:
                vod_id = VodRepo(s).create(stem="KOA", path=vod_path).id
            c = ClipCandidateRepo(s).create(stem="KOA_001", start=start, end=end, vod_id=vod_id)
            s.commit()
            return c.id

    def test_no_candidate(self):
        path, status = clip_preview.get_or_make_preview("nope", factory=self.factory)
        self.assertIsNone(path)
        self.assertEqual(status, clip_preview.NO_CANDIDATE)

    def test_serves_existing_version_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "rendered.mp4"
            real.write_bytes(b"video")
            cid = self._candidate(vod_path="C:/x/fake.mp4")
            with self.factory() as s:
                ClipVersionRepo(s).create(candidate_id=cid, stem="KOA_001", path=str(real))
                s.commit()
            path, status = clip_preview.get_or_make_preview(cid, factory=self.factory)
        self.assertEqual(status, clip_preview.VERSION)
        self.assertEqual(path, real)

    def test_serves_cached_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            cid = self._candidate(vod_path="C:/x/fake.mp4")
            cached = Path(tmp) / f"{cid}.mp4"
            cached.write_bytes(b"cached")
            with patch.object(clip_preview, "PREVIEW_DIR", Path(tmp)):
                path, status = clip_preview.get_or_make_preview(cid, factory=self.factory)
        self.assertEqual(status, clip_preview.CACHED)
        self.assertEqual(path, cached)

    def test_no_source_when_vod_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cid = self._candidate(vod_path="C:/does/not/exist.mp4")
            with patch.object(clip_preview, "PREVIEW_DIR", Path(tmp)):
                path, status = clip_preview.get_or_make_preview(cid, factory=self.factory)
        self.assertIsNone(path)
        self.assertEqual(status, clip_preview.NO_SOURCE)

    def test_cuts_preview_when_source_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            vod = Path(tmp) / "source.mp4"
            vod.write_bytes(b"the whole vod")
            cid = self._candidate(vod_path=str(vod))
            preview_dir = Path(tmp) / "previews"

            def fake_cut(source, start, end, out):
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"preview")

            with patch.object(clip_preview, "PREVIEW_DIR", preview_dir), \
                 patch.object(clip_preview, "_cut_preview", side_effect=fake_cut) as cut:
                path, status = clip_preview.get_or_make_preview(cid, factory=self.factory)

            self.assertEqual(status, clip_preview.RENDERED)
            self.assertTrue(path.exists())
            # Cut with the candidate's window.
            args = cut.call_args.args
            self.assertEqual(args[0], vod)
            self.assertEqual((args[1], args[2]), (10.0, 40.0))


if __name__ == "__main__":
    unittest.main()
