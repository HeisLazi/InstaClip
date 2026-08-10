"""On-demand candidate previews (blueprint Phase 2 — Codex viewer follow-up).

Most migrated candidates are metadata-only: they have a source VOD + start/end but
no rendered file in `output/clips`, so the gallery/viewer video endpoint 404s and
the Discord card has nothing to preview.

This makes a preview on demand:
  1. if the candidate already has a rendered version file -> serve that;
  2. else if a cached preview exists -> serve it;
  3. else if the source VOD is on disk -> cut a short, downscaled preview, cache it;
  4. else -> no preview possible (source unavailable).

Previews are intentionally cheap (downscaled, duration-capped) and cached under
`data/previews/<candidate_id>.mp4`. The actual ffmpeg cut (`_cut_preview`) needs
media so it isn't unit-tested; the resolution logic around it is.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

from config import paths
from db.base import DEFAULT_CREATOR_ID, SessionLocal
from db.repository import ClipCandidateRepo, VodRepo, session_scope

log = logging.getLogger("clip_preview")

PREVIEW_DIR = paths.DATA_DIR / "previews"
PREVIEW_MAX_SECONDS = 60.0
PREVIEW_HEIGHT = 480

# Resolution outcomes (also surfaced to the API so it can pick a status code).
VERSION = "version"      # served an existing rendered version
CACHED = "cached"        # served a previously-made preview
RENDERED = "rendered"    # cut a fresh preview just now
NO_SOURCE = "no_source"  # source VOD not on disk — can't preview
NO_CANDIDATE = "no_candidate"
FAILED = "failed"        # ffmpeg failed


def preview_path_for(candidate_id: str) -> Path:
    return PREVIEW_DIR / f"{candidate_id}.mp4"


def _cut_preview(source: Path, start: float, end: float, out: Path) -> None:
    """ffmpeg: a downscaled, duration-capped cut for quick preview/seeking."""
    duration = (end - start) if end > start else PREVIEW_MAX_SECONDS
    duration = max(0.5, min(PREVIEW_MAX_SECONDS, duration))
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(round(max(0.0, start), 3)),
        "-t", str(round(duration, 3)),
        "-i", str(source),
        "-vf", f"scale=-2:{PREVIEW_HEIGHT}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart",
        str(out),
    ]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"preview ffmpeg failed: {r.stderr.decode()[-300:]}")


def _downscale_file(source: Path, out: Path) -> None:
    """Re-encode a whole clip small (for a Discord attachment ≤ ~24MB)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-i", str(source),
        "-t", str(PREVIEW_MAX_SECONDS),
        "-vf", f"scale=-2:{PREVIEW_HEIGHT}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
        "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
        str(out),
    ]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"downscale ffmpeg failed: {r.stderr.decode()[-300:]}")


def make_discord_preview(
    candidate_id: str, *, factory=SessionLocal, creator_id: str = DEFAULT_CREATOR_ID,
) -> tuple[Optional[Path], str]:
    """A downscaled, duration-capped preview small enough to attach to a Discord
    card (unlike get_or_make_preview, which may return a full-size version file).
    Cuts from the source VOD window if resolvable, else downscales an existing
    rendered clip. Cached at data/previews/<id>_discord.mp4."""
    with session_scope(factory) as s:
        candidate = ClipCandidateRepo(s, creator_id).get(candidate_id)
        if candidate is None:
            return None, NO_CANDIDATE
        start = candidate.start or 0.0
        end = candidate.end or 0.0
        vod_stored = None
        if candidate.vod_id:
            vod = VodRepo(s, creator_id).get(candidate.vod_id)
            vod_stored = vod.path if (vod and vod.path) else None
        version_path = next(
            (v.path for v in candidate.versions if v.path and Path(v.path).exists()), None
        )

    cached = PREVIEW_DIR / f"{candidate_id}_discord.mp4"
    if cached.exists() and cached.stat().st_size > 0:
        return cached, CACHED

    from modules.vod_resolver import resolve_vod_path
    vod_path = resolve_vod_path(vod_stored)
    try:
        if vod_path is not None:
            _cut_preview(vod_path, start, end, cached)  # from the VOD window, downscaled
        elif version_path:
            _downscale_file(Path(version_path), cached)  # shrink an existing clip
        else:
            return None, NO_SOURCE
        return cached, RENDERED
    except Exception as exc:  # noqa: BLE001
        log.warning("discord preview failed for %s: %s", candidate_id, exc)
        return None, FAILED


def get_or_make_preview(
    candidate_id: str, *, factory=SessionLocal, creator_id: str = DEFAULT_CREATOR_ID,
) -> tuple[Optional[Path], str]:
    """Return (path, status). path is None when no preview can be produced."""
    with session_scope(factory) as s:
        candidate = ClipCandidateRepo(s, creator_id).get(candidate_id)
        if candidate is None:
            return None, NO_CANDIDATE
        # 1. An already-rendered version file is the best preview.
        for v in candidate.versions:
            if v.path and Path(v.path).exists():
                return Path(v.path), VERSION
        start = candidate.start or 0.0
        end = candidate.end or 0.0
        vod_stored = None
        if candidate.vod_id:
            vod = VodRepo(s, creator_id).get(candidate.vod_id)
            vod_stored = vod.path if (vod and vod.path) else None

    # 2. A cached preview from a previous request.
    cached = preview_path_for(candidate_id)
    if cached.exists() and cached.stat().st_size > 0:
        return cached, CACHED

    # 3. Need the source VOD on disk — resolve the stored filename to a real file.
    from modules.vod_resolver import resolve_vod_path
    vod_path = resolve_vod_path(vod_stored)
    if vod_path is None:
        return None, NO_SOURCE

    # 4. Cut + cache.
    try:
        _cut_preview(vod_path, start, end, cached)
        return cached, RENDERED
    except Exception as exc:  # noqa: BLE001
        log.warning("preview cut failed for %s: %s", candidate_id, exc)
        return None, FAILED


__all__ = [
    "get_or_make_preview",
    "preview_path_for",
    "PREVIEW_DIR",
    "VERSION", "CACHED", "RENDERED", "NO_SOURCE", "NO_CANDIDATE", "FAILED",
]
