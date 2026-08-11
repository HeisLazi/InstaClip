"""Clip sort/folder tags: taxonomy + store (set/get/preserve/index).

Patches the review-store path to a temp file; no real data touched.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules import clip_reviews


class ClipTagsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / "clip_reviews.json"
        self._patch = patch.object(clip_reviews.paths, "CLIP_REVIEWS_FILE", self.file)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmp.cleanup()

    def test_taxonomy_has_good_and_bad(self):
        self.assertIn("posting these", clip_reviews.TAG_TAXONOMY["good"])
        self.assertIn("compilation clip", clip_reviews.TAG_TAXONOMY["good"])
        self.assertIn("complete miss", clip_reviews.TAG_TAXONOMY["bad"])
        self.assertIn("micro clip", clip_reviews.TAG_TAXONOMY["bad"])

    def test_set_and_get_tags_normalised(self):
        clip_reviews.set_clip_tags("CLIP1", "positives", ["Posting These", "Compilation Clip"])
        self.assertEqual(clip_reviews.get_clip_tags("CLIP1"), ["posting these", "compilation clip"])

    def test_set_tags_preserves_existing_review_fields(self):
        clip_reviews.save_review(
            "CLIP1", "negatives",
            {"verdict": "miss", "reasons": ["dead air"], "notes": "meh"},
        )
        clip_reviews.set_clip_tags("CLIP1", "negatives", ["micro clip"])
        r = clip_reviews.get_review("CLIP1")
        self.assertEqual(r["verdict"], "miss")
        self.assertEqual(r["reasons"], ["dead air"])
        self.assertEqual(r["notes"], "meh")
        self.assertEqual(r["tags"], ["micro clip"])

    def test_save_review_preserves_existing_tags(self):
        clip_reviews.set_clip_tags("CLIP1", "positives", ["posting these"])
        clip_reviews.save_review("CLIP1", "positives", {"verdict": "keeper"})  # no tags in payload
        self.assertEqual(clip_reviews.get_clip_tags("CLIP1"), ["posting these"])

    def test_save_review_sets_tags_from_payload(self):
        clip_reviews.save_review("CLIP1", "positives", {"verdict": "keeper", "tags": ["lwk good clip"]})
        self.assertEqual(clip_reviews.get_clip_tags("CLIP1"), ["lwk good clip"])

    def test_tags_index_only_includes_tagged_clips(self):
        clip_reviews.set_clip_tags("A", "positives", ["standalone"])
        clip_reviews.save_review("B", "negatives", {"verdict": "miss"})  # no tags
        idx = clip_reviews.tags_index()
        self.assertEqual(idx.get("A"), ["standalone"])
        self.assertNotIn("B", idx)

    def test_tags_deduped(self):
        clip_reviews.set_clip_tags("C", "positives", ["x", "X", "x"])
        self.assertEqual(clip_reviews.get_clip_tags("C"), ["x"])

    def test_get_tags_for_unknown_clip_is_empty(self):
        self.assertEqual(clip_reviews.get_clip_tags("nope"), [])


if __name__ == "__main__":
    unittest.main()
