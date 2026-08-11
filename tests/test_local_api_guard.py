"""F1 local-API guard: Host allowlist (DNS-rebinding kill) + foreign-Origin rejection.

CORS only protects response *reads*; these tests prove the requests themselves are
refused. Uses the FastAPI TestClient so no live server or port is needed.
"""

import unittest

from fastapi.testclient import TestClient

from backend.main import app


class LocalApiGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # raise_server_exceptions off: we only care about status codes.
        cls.client = TestClient(app, raise_server_exceptions=False)

    def test_normal_local_request_passes(self):
        r = self.client.get("/")  # TestClient sends Host: testserver (allowlisted)
        self.assertEqual(r.status_code, 200)

    def test_dns_rebinding_host_is_refused(self):
        # A rebound page's requests carry the attacker hostname in Host.
        r = self.client.get("/", headers={"Host": "attacker.evil.com"})
        self.assertEqual(r.status_code, 403)

    def test_rebinding_refused_even_with_port(self):
        r = self.client.get("/", headers={"Host": "attacker.evil.com:8765"})
        self.assertEqual(r.status_code, 403)

    def test_localhost_and_loopback_hosts_pass(self):
        for host in ("127.0.0.1:8765", "localhost:8765", "127.0.0.1", "localhost"):
            r = self.client.get("/", headers={"Host": host})
            self.assertEqual(r.status_code, 200, f"host {host} should be allowed")

    def test_foreign_origin_post_is_refused(self):
        # A cross-site "simple request" POST would execute despite CORS — the
        # guard must refuse it before any route runs.
        r = self.client.post("/pipeline/run", headers={"Origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)

    def test_foreign_origin_get_is_tolerated(self):
        # Reads are already protected by CORS (response is unreadable cross-site);
        # blocking GETs would break nothing but is not required. Guard permits it.
        r = self.client.get("/", headers={"Origin": "https://evil.example"})
        self.assertEqual(r.status_code, 200)

    def test_app_origin_post_passes_guard(self):
        # The Tauri webview origin must NOT be blocked (404/422 fine — route-level
        # outcome — just not the guard's 403).
        r = self.client.post("/chat/provider", json={"provider": "auto"},
                             headers={"Origin": "http://tauri.localhost"})
        self.assertNotEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
