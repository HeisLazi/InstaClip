# Privacy and Security

## Local-first privacy model

InstaClip is built around the principle that the creator's raw media and transcripts stay on their own machine:

- Video files, audio proxies, transcripts, and thumbnails are stored under the local `data/` directory.
- The database is a local SQLite file.
- No analytics, telemetry, or crash reporter is included in this edition.
- No cloud account is required to run the core pipeline.

## Network exposure

- The FastAPI backend binds to `127.0.0.1:8765` only. It is not reachable from the LAN or the public internet by default.
- The backend has no authentication layer: callers are trusted because they must already be on the same machine.
- To change the bind address you must edit the source or pass `--host`; this is not recommended without adding authentication.

## CORS and origin protection

CORS alone does not fully protect a local API from malicious web pages. The backend therefore layers three defenses:

1. **CORS allowlist** — only Tauri webview origins (`tauri://localhost`, `https://tauri.localhost`, `http://tauri.localhost`), the Vite dev server (`localhost:5173`, `127.0.0.1:5173`), and the Tauri dev server (`localhost:1420`, `127.0.0.1:1420`) are allowed. No wildcard (`*`) origin.
2. **Host allowlist** — requests whose `Host` header is not `127.0.0.1`, `localhost`, or `testserver` are rejected with `403`. This blocks DNS-rebinding attacks that repoint a malicious hostname to `127.0.0.1`.
3. **Foreign-Origin POST guard** — CORS blocks reading cross-origin responses, but simple POSTs can still execute server-side. State-changing methods (`POST`, `PUT`, `PATCH`, `DELETE`) whose `Origin` header is not in the allowlist are rejected with `403`.

These behaviors are verified in `tests/test_local_api_guard.py` and `tests/test_security_hardening.py`.

## Credentials and secrets

- No API keys, tokens, or certificates are committed to this repository.
- `.env.example` contains only placeholder comments and example values.
- `.gitignore` excludes `.env`, `*.env.*`, credential files (`*credential*`), certificates (`*.pem`, `*.key`, `*.p12`, `*.pfx`), and model weights (`models/`).
- The clipper edition explicitly does not read local API keys (verified in `tests/test_security_hardening.py`).

## Support bundle redaction

The `/tester` route can export a redacted support bundle. The redaction pass removes:

- Google API keys
- OpenAI / Anthropic-style keys
- Meta (Facebook/Instagram) tokens
- Discord-shaped tokens
- TikTok tokens
- Cloudflare tokens
- Cloudflare tunnel URLs
- Generic passwords

Tests in `tests/test_security_hardening.py` assert these patterns are removed.

## Optional cloud judge

A cloud LLM-judge gateway is **opt-in** and disabled by default:

- No requests are made unless `CLIPPER_GATEWAY_URL` is explicitly configured.
- When configured, the `tester_gateway` module routes a subset of selection/review calls to the gateway.
- When not configured, the app falls back to local engines and mocked paths; it never crashes due to a missing gateway.

## What the commercial edition adds

The private commercial edition adds authenticated cloud surfaces:

- Discord Clip Room bot and delivery integration.
- Cloud gateway with user auth, refresh tokens, and quota accounting.
- Publishing integrations with third-party platforms (Instagram, TikTok, YouTube).
- Creator OS chat and memory sync.

These surfaces require tokens, service accounts, and external infrastructure, so they are excluded from the public edition.
