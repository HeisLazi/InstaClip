from typing import Any
import json
import re
import shutil
import time
import zipfile
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from modules import tester_profile
from config import paths

router = APIRouter(prefix="/tester", tags=["tester"])


class ProfileBody(BaseModel):
    preset: str = "general"
    traits: list[str] = Field(default_factory=list)
    preferred_duration: list[float] = Field(default_factory=lambda: [15, 60])
    notes: str = ""
    examples: list[dict[str, Any]] = Field(default_factory=list)
    onboarding_complete: bool = False


class FeedbackBody(BaseModel):
    candidate_id: str
    signal: str
    notes: str = ""
    start: float | None = None
    end: float | None = None


class CloudSessionBody(BaseModel):
    gateway_url: str
    access_token: str
    refresh_token: str
    user_id: str


CLOUD_SESSION_DISABLED = {
    "detail": "Cloud session attach is disabled in the public edition. "
              "Set CLIPPER_GATEWAY_URL in your environment to enable gateway selection."
}


def _user(value: str | None) -> str:
    return (value or "local-tester").strip()[:80] or "local-tester"


@router.get("/profile/presets")
def profile_presets():
    return {"presets": tester_profile.presets()}


@router.post("/cloud-session")
def cloud_session(body: CloudSessionBody):
    import os

    if not os.environ.get("CLIPPER_GATEWAY_URL"):
        raise HTTPException(501, **CLOUD_SESSION_DISABLED)
    from modules.tester_gateway import attach_session, status
    try:
        attach_session(**body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return status()


@router.delete("/cloud-session")
def delete_cloud_session():
    import os

    if not os.environ.get("CLIPPER_GATEWAY_URL"):
        raise HTTPException(501, **CLOUD_SESSION_DISABLED)
    from modules.tester_gateway import clear_session
    clear_session()
    return {"ok": True}


@router.get("/cloud-session")
def cloud_session_status():
    from modules.tester_gateway import status
    return status()


@router.get("/profile")
def profile(x_tester_id: str | None = Header(default=None)):
    return {"profile": tester_profile.load_profile(_user(x_tester_id))}


@router.put("/profile")
def update_profile(body: ProfileBody, x_tester_id: str | None = Header(default=None)):
    try:
        return {"profile": tester_profile.save_profile(_user(x_tester_id), body.model_dump())}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/profile/reset")
def reset_profile(body: dict[str, Any], x_tester_id: str | None = Header(default=None)):
    try:
        return {"profile": tester_profile.reset_profile(_user(x_tester_id), str(body.get("preset") or "general"))}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/profile/feedback")
def profile_feedback(body: FeedbackBody, x_tester_id: str | None = Header(default=None)):
    try:
        return {"profile": tester_profile.add_feedback(_user(x_tester_id), body.model_dump())}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/preflight")
def preflight():
    usage = shutil.disk_usage(paths.ROOT_DIR)
    writable = True
    probe = paths.DATA_DIR / ".write-test"
    try:
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError:
        writable = False
    # Models are downloaded on first use (Whisper → HF cache, face landmarker →
    # data/models). On a clean machine they are absent until the first job — that
    # is expected, NOT an error, so it must not gate `ready`; we just report it so
    # the UI can warn "first run downloads models (~once)" instead of looking hung.
    face_model = paths.DATA_DIR / "models" / "face_landmarker.task"
    try:
        from config import cfg
        whisper_size = str(getattr(cfg.whisper, "model_size", "") or "")
    except Exception:  # noqa: BLE001
        whisper_size = ""
    whisper_bundled = bool(whisper_size) and (paths.bundled_whisper_dir(whisper_size) / "model.bin").exists()
    models = {
        "face_landmarker_present": face_model.exists(),
        "whisper_model": whisper_size,
        "whisper_bundled": whisper_bundled,
        "note": ("Speech model ships with the app — first run is instant." if whisper_bundled
                 else "Speech model downloads once on the first job; first run is slower."),
    }
    return {
        "workspace": str(paths.ROOT_DIR),
        "workspace_writable": writable,
        "free_disk_gb": round(usage.free / 1024 ** 3, 2),
        "ffmpeg": shutil.which("ffmpeg") or "",
        "ffprobe": shutil.which("ffprobe") or "",
        "transcript_checkpoints": str(paths.TRANSCRIPT_CHECKPOINTS_DIR),
        "models": models,
        "ready": writable and bool(shutil.which("ffmpeg")) and bool(shutil.which("ffprobe")) and usage.free >= 5 * 1024 ** 3,
    }


def _redact(value: str) -> str:
    home = str(Path.home())
    cleaned = value.replace(home, "%USERPROFILE%")
    # Provider key formats (WS1: expanded for sellable-product support bundles).
    cleaned = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED_GOOGLE_KEY]", cleaned)
    cleaned = re.sub(r"sk-[A-Za-z0-9_-]{16,}", "[REDACTED_SK_KEY]", cleaned)          # Anthropic/OpenAI-style
    cleaned = re.sub(r"(?:IGAA|EAA)[0-9A-Za-z]{20,}", "[REDACTED_META_TOKEN]", cleaned)  # Instagram/Facebook
    # Cloudflare API tokens (cfut_/v1.0- prefixes) and TikTok act.* tokens.
    cleaned = re.sub(r"cfut_[A-Za-z0-9_-]{20,}", "[REDACTED_CF_TOKEN]", cleaned)
    cleaned = re.sub(r"\bact\.[A-Za-z0-9_-]{20,}", "[REDACTED_TIKTOK_TOKEN]", cleaned)
    # Discord bot tokens: three dot-separated base64ish blocks starting with the bot-id block.
    cleaned = re.sub(r"[A-Za-z0-9_-]{23,28}\.[A-Za-z0-9_-]{6,7}\.[A-Za-z0-9_-]{25,}", "[REDACTED_DISCORD_TOKEN]", cleaned)
    # Cloudflare/trycloudflare tunnel URLs reveal live public endpoints.
    cleaned = re.sub(r"https://[a-z0-9-]+\.trycloudflare\.com[^\s\"']*", "[REDACTED_TUNNEL_URL]", cleaned)
    # Generic keyword=value catch-all, LAST. The (?!\[REDACTED) lookahead stops it
    # from clobbering a more-specific placeholder set above (e.g. [REDACTED_CF_TOKEN]).
    cleaned = re.sub(r"(?i)(bearer|token|secret|password|api[_-]?key)([\s\"':=]+)(?!\[REDACTED)[^\s\",}]+", r"\1\2[REDACTED]", cleaned)
    return cleaned


@router.get("/support-bundle")
def support_bundle():
    from fastapi.responses import FileResponse

    output = paths.OUTPUT_DIR / "support"
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"instaclip-support-{int(time.time())}.zip"
    status = preflight()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("preflight.json", json.dumps(status, indent=2))
        if paths.SETTINGS_FILE.exists():
            archive.writestr("settings.json", _redact(paths.SETTINGS_FILE.read_text(encoding="utf-8")))
        if paths.LOG_FILE.exists():
            lines = paths.LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]
            archive.writestr("pipeline.log", _redact("\n".join(lines)))
        archive.writestr("privacy.txt", "No source video, transcript, credential file, or editor media is included.\n")
    return FileResponse(target, media_type="application/zip", filename=target.name)
