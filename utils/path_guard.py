"""Media-path allowlist for endpoints that read local files by client-supplied
path (productization security hardening, WS1).

The backend trusts loopback callers, but "any local path" endpoints are still an
exfiltration lever: a malicious local page could POST `data/ai_credentials.json`
to /clip-room/deliver and have it publicly tunneled/posted to Discord. Every
endpoint that serves or ingests a client-named file must resolve it through this
guard: the file has to live under a known media root AND carry a media extension
(so credentials/DBs are unreachable even if someone drops them into a media dir).

Extra roots can be granted explicitly via the INSTACLIP_EXTRA_MEDIA_DIRS env var
(os.pathsep-separated), and tests may monkeypatch `extra_roots`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional

from config import paths

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".gif", ".ts"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_KIND_EXTS = {"video": VIDEO_EXTS, "audio": AUDIO_EXTS, "image": IMAGE_EXTS}

# Overridable in tests: extra allowed roots (list[Path]).
extra_roots: list[Path] = []


class PathNotAllowed(ValueError):
    """The client-supplied path is outside the allowed media roots/types."""


def _configured_vod_dir() -> Optional[Path]:
    try:
        from config import cfg
        raw = str(getattr(cfg.fetcher, "local_vod_dir", "") or "")
        return Path(raw).resolve() if raw else None
    except Exception:  # noqa: BLE001 — config missing must not break the guard
        return None


def allowed_media_roots() -> list[Path]:
    """Every directory the app legitimately reads media from. Deliberately NOT
    DATA_DIR itself — credentials and the DB live there."""
    roots = [
        paths.OUTPUT_DIR,             # clips / edited / notclips / metadata / packages
        paths.RAW_VODS_DIR,
        paths.OLD_CLIPS_DIR,
        paths.DATA_DIR / "editor_media",
        paths.EDITOR_VIDEO_PROXIES_DIR,
        paths.EDITOR_AUDIO_PROXIES_DIR,
    ]
    vod_dir = _configured_vod_dir()
    if vod_dir is not None:
        roots.append(vod_dir)
    for raw in os.environ.get("INSTACLIP_EXTRA_MEDIA_DIRS", "").split(os.pathsep):
        raw = raw.strip()
        if raw:
            roots.append(Path(raw))
    roots.extend(extra_roots)
    out = []
    for r in roots:
        try:
            out.append(Path(r).resolve())
        except OSError:
            continue
    return out


def _under(child: Path, root: Path) -> bool:
    try:
        child.relative_to(root)
        return True
    except ValueError:
        return False


def require_media_path(raw: str | Path, *, kinds: Iterable[str] = ("video",)) -> Path:
    """Resolve `raw` and require it to be an existing file of an allowed media
    type inside an allowed root. Returns the resolved Path or raises
    PathNotAllowed. Resolution happens BEFORE the root check, so `..` segments
    and symlinks/junctions can't escape."""
    try:
        p = Path(str(raw)).expanduser().resolve()
    except OSError as exc:
        raise PathNotAllowed(f"unresolvable path: {raw!r}") from exc

    allowed_exts: set[str] = set()
    for kind in kinds:
        allowed_exts |= _KIND_EXTS.get(kind, set())
    if p.suffix.lower() not in allowed_exts:
        raise PathNotAllowed(f"file type {p.suffix!r} is not an allowed media type")

    if not p.is_file():
        raise PathNotAllowed(f"no file at {p}")

    if not any(_under(p, root) for root in allowed_media_roots()):
        raise PathNotAllowed(f"path is outside the allowed media folders: {p}")
    return p


__all__ = ["require_media_path", "allowed_media_roots", "PathNotAllowed",
           "VIDEO_EXTS", "AUDIO_EXTS", "IMAGE_EXTS", "extra_roots"]
