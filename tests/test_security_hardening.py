"""WS1 security hardening regressions: clipper credential gate, support-bundle
redaction, CORS origin list.
"""

import os
import unittest
from unittest import mock

from backend.routes.tester import _redact
from modules import clip_judge


class ClipperCredentialGateTests(unittest.TestCase):
    def test_clipper_edition_never_reads_local_keys(self):
        with mock.patch.dict(os.environ, {"INSTACLIP_EDITION": "clipper",
                                          "GEMINI_API_KEY": "should-not-be-used"}):
            self.assertEqual(clip_judge._load_gemini_keys(), [])
            keys = clip_judge._load_keys()
            self.assertEqual(keys["anthropic"], "")
            self.assertEqual(keys["gemini"], "")

    def test_full_edition_still_reads_env(self):
        with mock.patch.dict(os.environ, {"INSTACLIP_EDITION": "full",
                                          "GEMINI_API_KEY": "env-key-1"}):
            self.assertIn("env-key-1", clip_judge._load_gemini_keys())


class RedactionTests(unittest.TestCase):
    def test_redacts_google_key(self):
        self.assertNotIn("AIzaSyFAKEFAKEFAKEFAKEFAKEFAKE",
                         _redact("key=AIzaSyFAKEFAKEFAKEFAKEFAKEFAKE"))

    def test_redacts_sk_key(self):
        self.assertIn("[REDACTED_SK_KEY]", _redact("sk-abcdefghijklmnop1234"))

    def test_redacts_meta_token(self):
        self.assertIn("[REDACTED_META_TOKEN]",
                      _redact("IGAAxyzABCDEFGHIJKLMNOPQRSTUV123"))

    def test_redacts_discord_token(self):
        tok = "A" * 26 + "." + "B" * 6 + "." + "C" * 30  # synthetic Discord-shaped; no token literal
        self.assertIn("[REDACTED_DISCORD_TOKEN]", _redact(f"token file holds {tok}"))

    def test_redacts_tunnel_url(self):
        self.assertIn("[REDACTED_TUNNEL_URL]",
                      _redact("serving at https://some-random-words.trycloudflare.com/abc123"))

    def test_redacts_cloudflare_token(self):
        fake = "cfut_" + "X" * 40
        out = _redact(f"CLOUDFLARE_API_TOKEN={fake}")
        self.assertIn("[REDACTED_CF_TOKEN]", out)
        self.assertNotIn(fake, out)

    def test_redacts_tiktok_token(self):
        fake = "act." + "y" * 40
        self.assertIn("[REDACTED_TIKTOK_TOKEN]", _redact(f"access_token {fake}"))

    def test_redacts_generic_password(self):
        self.assertNotIn("hunter2", _redact('password="hunter2"'))


class CorsConfigTests(unittest.TestCase):
    def test_no_wildcard_origin(self):
        import backend.main as bm
        self.assertNotIn("*", bm._ALLOWED_ORIGINS)
        self.assertIn("http://localhost:5173", bm._ALLOWED_ORIGINS)
        self.assertTrue(any(o.startswith(("tauri://", "http://tauri.", "https://tauri."))
                            for o in bm._ALLOWED_ORIGINS))


if __name__ == "__main__":
    unittest.main()
