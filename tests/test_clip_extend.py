"""Extend a project's clip (in-asset widening + VOD re-cut remap logic)."""

import unittest
from unittest import mock

from modules import clip_extend


def _project(source_in=10.0, source_out=40.0, duration=60.0, origin="source"):
    return {
        "revision": 1,
        "assets": {"ast": {"id": "ast", "path": "C:/x/HNG_16.mp4",
                           "duration": duration, "origin": origin}},
        "tracks": [{"id": "t", "items": [
            {"id": "i1", "assetId": "ast", "timelineStart": 5.0,
             "sourceIn": source_in, "sourceOut": source_out},
        ]}],
    }


class ExtendTests(unittest.TestCase):
    def test_widens_within_asset_when_room(self):
        p, rep = clip_extend.extend_project(_project(), 5.0, 10.0)
        item = p["tracks"][0]["items"][0]
        self.assertEqual(rep["mode"], "widened_in_asset")
        self.assertEqual(item["sourceIn"], 5.0)
        self.assertEqual(item["sourceOut"], 50.0)
        self.assertEqual(item["timelineStart"], 0.0)     # head grew leftward
        self.assertEqual(p["revision"], 2)

    def test_clamps_to_asset_bounds_without_vod_link(self):
        # No VOD linked → graceful partial widening within the asset.
        with mock.patch.object(clip_extend, "_vod_for_stem", return_value=None):
            p, rep = clip_extend.extend_project(_project(source_in=2, source_out=58), 10.0, 10.0)
        self.assertEqual(rep["mode"], "widened_in_asset")
        self.assertEqual(rep["granted"], {"before": 2.0, "after": 2.0})

    def test_recut_from_vod_remaps_items(self):
        proj = _project(source_in=0.0, source_out=30.0, duration=30.0)  # no room
        with mock.patch.object(clip_extend, "_vod_for_stem",
                               return_value=(clip_extend.Path("D:/vod.mp4"), 100.0, 130.0)), \
             mock.patch.object(clip_extend, "_recut_wider",
                               return_value=clip_extend.Path("C:/x/HNG_16_ext.mp4")), \
             mock.patch("modules.editor.probe",
                        side_effect=lambda p: {"duration": 7200.0 if "vod" in str(p) else 45.0}):
            p, rep = clip_extend.extend_project(proj, 5.0, 10.0)
        self.assertEqual(rep["mode"], "recut_from_vod")
        self.assertEqual(rep["new_source_window"], [95.0, 140.0])
        asset = p["assets"]["ast"]
        from pathlib import Path as _P
        self.assertEqual(_P(asset["path"]), _P("C:/x/HNG_16_ext.mp4"))
        item = p["tracks"][0]["items"][0]
        # old file 0..30 == new file 5..35; head widened to 0, tail to 45
        self.assertEqual(item["sourceIn"], 0.0)
        self.assertEqual(item["sourceOut"], 45.0)

    def test_no_vod_link_is_clear_error(self):
        proj = _project(source_in=0.0, source_out=30.0, duration=30.0)
        with mock.patch.object(clip_extend, "_vod_for_stem", return_value=None):
            with self.assertRaises(clip_extend.ExtendError):
                clip_extend.extend_project(proj, 5.0, 0.0)

    def test_zero_extend_rejected(self):
        with self.assertRaises(clip_extend.ExtendError):
            clip_extend.extend_project(_project(), 0.0, 0.0)


class VodResolutionTests(unittest.TestCase):
    """The reported regression: AI clip files (GEN_…) resolve to their VOD via the
    ClipVersion link, not the mismatched candidate stem."""

    def setUp(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from db.base import DEFAULT_CREATOR_ID
        from db.models import Base
        from db.repository import (ClipCandidateRepo, ClipVersionRepo,
                                   CreatorRepo, VodRepo)
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        self.cid = DEFAULT_CREATOR_ID
        with self.Session() as s:
            CreatorRepo(s).ensure(self.cid, self.cid, "HeisLazi")
            vod = VodRepo(s, self.cid).create(stem="2026-01-21 VOD", path="D:/streams/vod.mp4")
            cand = ClipCandidateRepo(s, self.cid).create(
                stem="2026-01-21 VOD_007", vod_id=vod.id, start=594.9, end=650.0)
            ClipVersionRepo(s, self.cid).create(
                candidate_id=cand.id, stem="GEN_0.68_cheap_ass_dick_bro",
                bucket="output", path="C:/out/GEN_0.68_cheap_ass_dick_bro.mp4")
            s.commit()

    def test_gen_stem_resolves_candidate_via_version(self):
        from db.base import DEFAULT_CREATOR_ID
        with self.Session() as s:
            cand = clip_extend._candidate_for_stem(
                s, DEFAULT_CREATOR_ID, "GEN_0.68_cheap_ass_dick_bro")
            self.assertIsNotNone(cand)
            self.assertEqual(cand.stem, "2026-01-21 VOD_007")   # the linked candidate
            self.assertEqual(cand.start, 594.9)

    def test_candidate_stem_still_resolves_directly(self):
        from db.base import DEFAULT_CREATOR_ID
        with self.Session() as s:
            cand = clip_extend._candidate_for_stem(
                s, DEFAULT_CREATOR_ID, "2026-01-21 VOD_007")
            self.assertIsNotNone(cand)

    def test_path_basename_match_when_stem_field_differs(self):
        from db.base import DEFAULT_CREATOR_ID
        with self.Session() as s:
            # asset stem = file basename, even if the version.stem column differs
            cand = clip_extend._candidate_for_stem(
                s, DEFAULT_CREATOR_ID, "GEN_0.68_cheap_ass_dick_bro")
            self.assertIsNotNone(cand)


if __name__ == "__main__":
    unittest.main()
