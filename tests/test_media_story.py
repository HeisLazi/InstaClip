from __future__ import annotations

import unittest

from modules.media_story import _parse_ffmpeg_output


class MediaStoryTests(unittest.TestCase):
    def test_parses_scene_scores_and_black_ranges(self):
        output = """
frame:0 pts:100 pts_time:10.5
lavfi.scene_score=0.321
[blackdetect] black_start:20 black_end:21.5 black_duration:1.5
frame:1 pts:200 pts_time:30.25
lavfi.scene_score=0.55
"""
        parsed = _parse_ffmpeg_output(output)
        self.assertEqual(parsed["sceneCuts"], [
            {"at": 10.5, "score": 0.321},
            {"at": 30.25, "score": 0.55},
        ])
        self.assertEqual(parsed["blackSegments"][0]["duration"], 1.5)


if __name__ == "__main__":
    unittest.main()
