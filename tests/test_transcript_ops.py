"""WS3.2 transcript-text editing ops + scene layout detection.

Pure-function tests: no ffmpeg (silences/scene times injected), fake projects.
"""

import unittest
from pathlib import Path

from modules import scene_layout, transcript_ops


def _project(source_out=60.0):
    return {
        "schemaVersion": 1, "id": "prj_t", "revision": 3,
        "assets": {"ast_1": {"id": "ast_1", "path": "C:/fake/clip.mp4", "duration": source_out}},
        "tracks": [
            {"id": "trk_v1", "kind": "video", "items": [
                {"id": "itm_v", "assetId": "ast_1", "trackId": "trk_v1",
                 "timelineStart": 0.0, "sourceIn": 0.0, "sourceOut": source_out, "speed": 1},
            ]},
            {"id": "trk_a1", "kind": "audio", "items": [
                {"id": "itm_a", "assetId": "ast_1", "trackId": "trk_a1",
                 "timelineStart": 0.0, "sourceIn": 0.0, "sourceOut": source_out, "speed": 1},
            ]},
        ],
    }


class CutRangesTests(unittest.TestCase):
    def test_cut_splits_and_ripples(self):
        p, report = transcript_ops.apply_ops(
            _project(), [{"type": "cut_ranges", "ranges": [{"start": 10, "end": 15}]}]
        )
        video = p["tracks"][0]["items"]
        self.assertEqual(len(video), 2)
        self.assertEqual((video[0]["sourceIn"], video[0]["sourceOut"]), (0.0, 10.0))
        self.assertEqual((video[1]["sourceIn"], video[1]["sourceOut"]), (15.0, 60.0))
        self.assertAlmostEqual(video[1]["timelineStart"], 10.0)  # rippled left
        self.assertEqual(report["items_split"], 2)  # video + linked audio
        self.assertAlmostEqual(report["removed_seconds"], 5.0)

    def test_multiple_overlapping_ranges_merge(self):
        p, report = transcript_ops.apply_ops(
            _project(), [{"type": "cut_ranges",
                          "ranges": [{"start": 10, "end": 14}, {"start": 12, "end": 18},
                                     {"start": 30, "end": 31}]}]
        )
        self.assertEqual(report["cut_ranges_applied"], [[10.0, 18.0], [30.0, 31.0]])
        video = p["tracks"][0]["items"]
        self.assertEqual(len(video), 3)
        self.assertAlmostEqual(sum(i["sourceOut"] - i["sourceIn"] for i in video), 51.0)

    def test_speed_items_are_skipped_not_broken(self):
        proj = _project()
        proj["tracks"][0]["items"][0]["speed"] = 2
        p, report = transcript_ops.apply_ops(
            proj, [{"type": "cut_ranges", "ranges": [{"start": 10, "end": 15}]}]
        )
        self.assertIn("itm_v", report["skipped_items"])
        self.assertEqual(len(p["tracks"][0]["items"]), 1)  # untouched

    def test_revision_bumps_once_per_mutation(self):
        # Stale-client regression (Codex V&V): rev must advance so a second client
        # sending the OLD expected_revision gets a 409 at the route.
        p, _ = transcript_ops.apply_ops(
            _project(), [{"type": "cut_ranges", "ranges": [{"start": 10, "end": 15}]}]
        )
        self.assertEqual(p["revision"], 4)  # was 3
        p2, _ = transcript_ops.apply_ops(
            p, [{"type": "cut_ranges", "ranges": [{"start": 20, "end": 21}]}]
        )
        self.assertEqual(p2["revision"], 5)

    def test_invalid_range_rejected(self):
        with self.assertRaises(transcript_ops.TranscriptOpsError):
            transcript_ops.apply_ops(
                _project(), [{"type": "cut_ranges", "ranges": [{"start": 5, "end": 5}]}]
            )

    def test_unknown_op_rejected(self):
        with self.assertRaises(transcript_ops.TranscriptOpsError):
            transcript_ops.apply_ops(_project(), [{"type": "explode"}])

    def test_remove_silences_uses_detector(self):
        orig = transcript_ops.detect_silences
        orig_isfile = Path.is_file
        transcript_ops.detect_silences = lambda src, **k: [(20.0, 22.0)]
        Path.is_file = lambda self: True
        try:
            p, report = transcript_ops.apply_ops(
                _project(), [{"type": "remove_silences", "min_gap": 0.8, "pad": 0.5}]
            )
        finally:
            transcript_ops.detect_silences = orig
            Path.is_file = orig_isfile
        self.assertEqual(report["cut_ranges_applied"], [[20.5, 21.5]])  # padded
        self.assertEqual(len(p["tracks"][0]["items"]), 2)


class SceneLayoutTests(unittest.TestCase):
    def test_segments_from_injected_scene_times(self):
        out = scene_layout.detect_layout_segments(
            "C:/fake/clip.mp4", 0.0, 30.0, classify=False,
            scene_times=[12.0, 21.5],
        )
        self.assertTrue(out["has_layout_switch"])
        self.assertEqual(out["switches"], [12.0, 21.5])
        segs = [(s["start"], s["end"]) for s in out["segments"]]
        self.assertEqual(segs, [(0.0, 12.0), (12.0, 21.5), (21.5, 30.0)])

    def test_no_switch_single_segment(self):
        out = scene_layout.detect_layout_segments(
            "C:/fake/clip.mp4", 5.0, 35.0, classify=False, scene_times=[],
        )
        self.assertFalse(out["has_layout_switch"])
        self.assertEqual(len(out["segments"]), 1)

    def test_out_of_window_times_ignored(self):
        out = scene_layout.detect_layout_segments(
            "C:/fake/clip.mp4", 10.0, 20.0, classify=False,
            scene_times=[5.0, 15.0, 25.0],
        )
        self.assertEqual(out["switches"], [15.0])


if __name__ == "__main__":
    unittest.main()
