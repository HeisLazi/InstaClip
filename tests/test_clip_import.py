"""Clip import helper: streams a file into a bucket (+ optional group) and tags it.

Patches bucket dirs + the review-store path to temp; no real data touched.
"""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from backend.routes import clips
from modules import clip_reviews


class ClipImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.positives = root / "positives"
        self.positives.mkdir()
        self._buckets = patch.object(clips, "_BUCKET_DIRS", {"positives": self.positives})
        self._buckets.start()
        self.reviews_file = root / "clip_reviews.json"
        self._reviews = patch.object(clip_reviews.paths, "CLIP_REVIEWS_FILE", self.reviews_file)
        self._reviews.start()

    def tearDown(self):
        self._buckets.stop()
        self._reviews.stop()
        self.tmp.cleanup()

    def test_imports_file_and_tags_it(self):
        data = io.BytesIO(b"fake mp4 bytes")
        res = clips._save_imported_clip(data, "my clip.mp4", "positives", tags=["raw example"])
        self.assertEqual(res["bucket"], "positives")
        self.assertEqual(res["tags"], ["raw example"])
        self.assertTrue((self.positives / "my clip.mp4").exists())
        self.assertEqual(clip_reviews.get_clip_tags("my clip"), ["raw example"])

    def test_places_into_a_stream_group_subfolder(self):
        res = clips._save_imported_clip(io.BytesIO(b"x"), "c.mp4", "positives", group="austria stream")
        self.assertEqual(res["group"], "austria stream")
        self.assertTrue((self.positives / "austria stream" / "c.mp4").exists())

    def test_auto_suffixes_on_collision(self):
        clips._save_imported_clip(io.BytesIO(b"a"), "dup.mp4", "positives")
        res2 = clips._save_imported_clip(io.BytesIO(b"b"), "dup.mp4", "positives")
        self.assertEqual(res2["name"], "dup_1.mp4")  # didn't clobber the first

    def test_rejects_non_video(self):
        with self.assertRaises(HTTPException) as ctx:
            clips._save_imported_clip(io.BytesIO(b"x"), "evil.exe", "positives")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_rejects_unknown_bucket(self):
        with self.assertRaises(HTTPException) as ctx:
            clips._save_imported_clip(io.BytesIO(b"x"), "c.mp4", "nope")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_rejects_too_large(self):
        with self.assertRaises(HTTPException) as ctx:
            clips._save_imported_clip(io.BytesIO(b"abcdefghij"), "big.mp4", "positives", max_bytes=4)
        self.assertEqual(ctx.exception.status_code, 413)
        self.assertFalse((self.positives / "big.mp4").exists())  # partial cleaned up


if __name__ == "__main__":
    unittest.main()
