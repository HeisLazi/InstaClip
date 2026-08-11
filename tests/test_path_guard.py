"""WS1 security: media-path allowlist for client-supplied file paths.

Covers the guard itself plus the exfil regressions: credentials/DB files must be
unreachable via /clip-room/deliver-style paths even when inside data/.
"""

import tempfile
import unittest
from pathlib import Path

from config import paths
from utils import path_guard


class PathGuardTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        path_guard.extra_roots = [self.tmp]

    def tearDown(self):
        path_guard.extra_roots = []
        self._tmp.cleanup()

    def _mk(self, rel: str) -> Path:
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    def test_allows_video_in_allowed_root(self):
        p = self._mk("clip.mp4")
        self.assertEqual(path_guard.require_media_path(str(p)), p)

    def test_rejects_path_outside_roots(self):
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / "clip.mp4"
            outside.write_bytes(b"x")
            with self.assertRaises(path_guard.PathNotAllowed):
                path_guard.require_media_path(str(outside))

    def test_rejects_traversal_escape(self):
        # <allowed>/../outside.mp4 resolves outside the root and must be rejected.
        outside = self.tmp.parent / "outside.mp4"
        outside.write_bytes(b"x")
        try:
            with self.assertRaises(path_guard.PathNotAllowed):
                path_guard.require_media_path(str(self.tmp / ".." / "outside.mp4"))
        finally:
            outside.unlink()

    def test_rejects_non_media_extension_even_in_allowed_root(self):
        # Exfil regression: a credentials/db file inside an allowed root is still
        # blocked by the extension check.
        p = self._mk("ai_credentials.json")
        with self.assertRaises(path_guard.PathNotAllowed):
            path_guard.require_media_path(str(p))
        db = self._mk("heislazi.db")
        with self.assertRaises(path_guard.PathNotAllowed):
            path_guard.require_media_path(str(db))

    def test_rejects_missing_file(self):
        with self.assertRaises(path_guard.PathNotAllowed):
            path_guard.require_media_path(str(self.tmp / "nope.mp4"))

    def test_kind_selection(self):
        wav = self._mk("sound.wav")
        with self.assertRaises(path_guard.PathNotAllowed):
            path_guard.require_media_path(str(wav), kinds=("video",))
        self.assertEqual(path_guard.require_media_path(str(wav), kinds=("audio",)), wav)

    def test_data_dir_itself_is_not_an_allowed_root(self):
        # DATA_DIR holds credentials + the DB; only specific media subdirs are allowed.
        roots = path_guard.allowed_media_roots()
        self.assertNotIn(paths.DATA_DIR.resolve(), roots)
        self.assertIn(paths.OUTPUT_DIR.resolve(), roots)


if __name__ == "__main__":
    unittest.main()
