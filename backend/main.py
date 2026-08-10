"""
InstaClip FastAPI backend.

Launch (dev):
    python -m backend.main

Launch (prod, bundled with Tauri):
    uvicorn backend.main:app --host 127.0.0.1 --port 8765 --workers 1
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Trigger config init (logging, paths) before anything else logs.
from config import paths  # noqa: F401

from backend import log_bus
from backend.job_manager import jobs
from backend.routes import (
    clip_room,
    clips,
    edit,
    editor_v2,
    language,
    pipeline,
    profile,
    reviews,
    settings,
    status,
    stream,
    tester,
)

log = logging.getLogger("backend")
APP_EDITION = os.environ.get("INSTACLIP_EDITION", "clipper").strip().lower()
if APP_EDITION not in {"full", "clipper"}:
    APP_EDITION = "clipper"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    log_bus.install()
    loop = asyncio.get_running_loop()
    log_bus.bus.attach_loop(loop)
    jobs.attach_loop(loop)
    try:
        from db import init_db
        init_db()
        # Reconcile any jobs left 'running' by a hard restart (Phase 1 durable jobs).
        from db.job_store import job_store
        recovered = job_store.recover_interrupted()
        from backend.durable_pipeline import durable_pipeline
        durable_pipeline.resume_queued()
    except Exception as exc:  # noqa: BLE001 — DB must not block the app booting
        log.warning("DB init skipped: %s", exc)
    log.info("InstaClip backend ready on the event loop.")
    try:
        yield
    finally:
        pass
    log.info("InstaClip backend shutting down.")


app = FastAPI(
    title="InstaClip backend",
    version="0.1.0",
    lifespan=_lifespan,
)

# CORS is locked to the app's own origins (WS1 security hardening). The API binds
# to 127.0.0.1 only, but wide-open CORS would still let any webpage the user
# visits script this API from the browser. Tauri's webview origin on Windows is
# http(s)://tauri.localhost; dev uses the Vite server on 5173. Extra origins can
# be granted via INSTACLIP_ALLOWED_ORIGINS (comma-separated).
_ALLOWED_ORIGINS = [
    "tauri://localhost",
    "https://tauri.localhost",
    "http://tauri.localhost",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:1420",   # tauri dev server default
    "http://127.0.0.1:1420",
]
_ALLOWED_ORIGINS += [
    o.strip() for o in os.environ.get("INSTACLIP_ALLOWED_ORIGINS", "").split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CORS alone is not a lock (sellable-v1 F1). Two gaps it leaves open on a
# customer machine:
#   1. DNS rebinding — a malicious page re-points its own hostname at
#      127.0.0.1:8765, becomes "same-origin", and gets full read/write access.
#      The browser then sends THAT hostname in the Host header, so a strict
#      Host allowlist kills the technique outright.
#   2. Cross-site side effects — CORS blocks *reading* responses, but a
#      form-encoded "simple request" POST still executes server-side. Rejecting
#      state-changing methods whose Origin is foreign closes that.
# Requests without an Origin header (the Tauri shell's native fetches, curl,
# PowerShell, media tags) are unaffected.
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "testserver"}
_ALLOWED_HOSTS |= {
    h.strip().lower() for h in os.environ.get("INSTACLIP_ALLOWED_HOSTS", "").split(",") if h.strip()
}


@app.middleware("http")
async def _local_api_guard(request, call_next):
    host = (request.headers.get("host") or "").split(":")[0].strip().lower()
    if host not in _ALLOWED_HOSTS:
        return JSONResponse({"detail": "invalid host"}, status_code=403)
    origin = request.headers.get("origin")
    if (origin and origin not in _ALLOWED_ORIGINS
            and request.method not in ("GET", "HEAD", "OPTIONS")):
        return JSONResponse({"detail": "invalid origin"}, status_code=403)
    return await call_next(request)

CLIPPER_ROUTERS = [
    pipeline.router,
    clips.router,
    clip_room.router,
    edit.router,
    editor_v2.router,
    language.router,
    reviews.router,
    profile.router,
    settings.router,
    status.router,
    stream.router,
    tester.router,
]

if APP_EDITION == "full":
    log.warning(
        "APP_EDITION='full' requested, but owner-only modules are not part of this "
        "public edition. Continuing with the clipper router set."
    )

for configured_router in CLIPPER_ROUTERS:
    app.include_router(configured_router)


@app.get("/")
def root():
    return {
        "name":    "InstaClip backend",
        "version": "0.1.0",
        "status":  "ok",
        "edition": APP_EDITION,
        "capabilities": ["pipeline", "clips", "clip-room", "editor", "reviews", "profile"],
    }


if __name__ == "__main__":
    import uvicorn

    # Bind loopback only: the API has no authentication (callers are trusted as
    # the local desktop app), so it must not be reachable from the LAN. The CORS
    # comment above assumes this. Override with --host only if you add auth.
    host = "127.0.0.1"
    port = 8765
    if "--host" in sys.argv:
        host = sys.argv[sys.argv.index("--host") + 1]
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])

    uvicorn.run(
        "backend.main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )
