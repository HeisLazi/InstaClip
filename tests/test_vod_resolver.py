"""Resolve a stored VOD value (often a bare filename) to a real file on disk."""

import tempfile
import unittest
from pathlib import Path

from modules.vod_resolver import resolve_vod_path


class VodResolverTests(unittest.TestCase):
    def test_existing_full_path_returned_as_is(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "v.mp4"
            f.write_bytes(b"x")
            self.assertEqual(resolve_vod_path(str(f)), f)

    def test_finds_bare_filename_in_search_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "stream.mp4").write_bytes(b"x")
            self.assertEqual(resolve_vod_path("stream.mp4", search_dirs=[d]), d / "stream.mp4")

    def test_finds_in_subfolder(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = Path(tmp) / "sub"
            sub.mkdir()
            (sub / "s.mp4").write_bytes(b"x")
            self.assertEqual(resolve_vod_path("s.mp4", search_dirs=[Path(tmp)]), sub / "s.mp4")

    def test_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(resolve_vod_path("nope.mp4", search_dirs=[Path(tmp)]))

    def test_empty_returns_none(self):
        self.assertIsNone(resolve_vod_path(""))
        self.assertIsNone(resolve_vod_path(None))


if __name__ == "__main__":
    unittest.main()
