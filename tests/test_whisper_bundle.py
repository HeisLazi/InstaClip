"""Pre-bundled Whisper model resolution (clean-machine first-run fix).

A bundled model must load in place (no download); otherwise we fall back to a
by-name download cached inside the app's own data dir.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from config import paths
from utils import whisper_utils


class ResolveModelSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bundle = Path(self.tmp.name) / "bundle"
        self.data_dl = Path(self.tmp.name) / "data" / "models" / "whisper"

    def test_bundled_model_loads_in_place_no_download(self):
        model_dir = self.bundle / "models" / "whisper-medium"
        model_dir.mkdir(parents=True)
        (model_dir / "model.bin").write_bytes(b"fake ct2 model")
        with mock.patch.object(paths, "bundled_whisper_dir", return_value=model_dir):
            source, download_root = whisper_utils.resolve_model_source("medium")
        self.assertEqual(source, str(model_dir))   # a path, not the size name
        self.assertIsNone(download_root)            # never downloads

    def test_missing_bundle_falls_back_to_named_download_in_app_dir(self):
        empty = self.bundle / "models" / "whisper-medium"  # does not exist
        with mock.patch.object(paths, "bundled_whisper_dir", return_value=empty), \
             mock.patch.object(paths, "WHISPER_DOWNLOAD_DIR", self.data_dl):
            source, download_root = whisper_utils.resolve_model_source("medium")
        self.assertEqual(source, "medium")               # download by name
        self.assertEqual(download_root, str(self.data_dl))  # cached in app data
        self.assertTrue(self.data_dl.exists())            # dir was created

    def test_partial_bundle_without_model_bin_is_not_used(self):
        model_dir = self.bundle / "models" / "whisper-medium"
        model_dir.mkdir(parents=True)  # dir exists but no model.bin
        with mock.patch.object(paths, "bundled_whisper_dir", return_value=model_dir), \
             mock.patch.object(paths, "WHISPER_DOWNLOAD_DIR", self.data_dl):
            source, download_root = whisper_utils.resolve_model_source("medium")
        self.assertEqual(source, "medium")  # not trusted without weights
        self.assertEqual(download_root, str(self.data_dl))


class PlanWhisperBundleTests(unittest.TestCase):
    """Packaging fail-closed decision — success AND failure paths."""

    def setUp(self):
        from utils.whisper_bundle import MIN_MODEL_BIN_BYTES
        self.MIN = MIN_MODEL_BIN_BYTES
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.models = Path(self.tmp.name) / "models"
        self.models.mkdir()

    def _make_model(self, size_name, nbytes):
        d = self.models / f"whisper-{size_name}"
        d.mkdir()
        (d / "model.bin").write_bytes(b"\0" * nbytes)
        return d

    def test_valid_configured_model_is_bundled(self):
        from utils.whisper_bundle import plan_whisper_bundle
        self._make_model("medium", self.MIN + 1)
        plan = plan_whisper_bundle(self.models, "medium", None)
        self.assertTrue(plan["ok"])
        self.assertEqual(len(plan["datas"]), 1)
        self.assertEqual(plan["datas"][0][1], "models/whisper-medium")

    def test_truncated_model_bin_fails_closed(self):
        from utils.whisper_bundle import plan_whisper_bundle
        self._make_model("medium", 1024)  # 1 KB — truncated/partial
        plan = plan_whisper_bundle(self.models, "medium", None)
        self.assertFalse(plan["ok"])
        self.assertEqual(plan["datas"], [])

    def test_missing_model_fails_closed(self):
        from utils.whisper_bundle import plan_whisper_bundle
        plan = plan_whisper_bundle(self.models, "large-v3", None)
        self.assertFalse(plan["ok"])

    def test_only_configured_model_is_bundled_not_others(self):
        from utils.whisper_bundle import plan_whisper_bundle
        self._make_model("small", self.MIN + 1)   # a valid but NON-configured model
        self._make_model("medium", self.MIN + 1)  # the configured one
        plan = plan_whisper_bundle(self.models, "medium", None)
        self.assertEqual([d[1] for d in plan["datas"]], ["models/whisper-medium"])

    def test_false_optout_does_not_bypass(self):
        from utils.whisper_bundle import plan_whisper_bundle
        for falsey in ("false", "0", "no", "", "off"):
            plan = plan_whisper_bundle(self.models, "medium", falsey)
            self.assertFalse(plan["ok"], f"{falsey!r} must NOT bypass")

    def test_truthy_optout_allows_download_fallback(self):
        from utils.whisper_bundle import plan_whisper_bundle
        for truthy in ("1", "true", "YES", "on"):
            plan = plan_whisper_bundle(self.models, "medium", truthy)
            self.assertTrue(plan["ok"], f"{truthy!r} should allow fallback")
            self.assertEqual(plan["datas"], [])  # nothing bundled, downloads at runtime


if __name__ == "__main__":
    unittest.main()
