"""
Thumbnail extraction for clip-viewer tiles. ffmpeg grabs one frame near the
middle of each clip, cached under data/thumbnails/.
"""

import logging
import subprocess
from pathlib import Path

from config import paths

log = logging.getLogger("thumbnails")

THUMB_DIR = paths.DATA_DIR / "thumbnails"


def get_thumbnail_path(clip_path: Path) -> Path:
    return THUMB_DIR / f"{clip_path.stem}.jpg"


def ensure_thumbnail(clip_path: Path, width: int = 320) -> Path | None:
    """
    Extract a thumbnail for a video clip if not already cached.
    Returns the cached jpg path, or None if extraction failed.
    """
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    thumb = get_thumbnail_path(clip_path)
    if thumb.exists() and thumb.stat().st_size > 0:
        return thumb
    if not clip_path.exists():
        return None

    # Grab the middle frame — more representative than the first.
    cmd = [
        "ffmpeg", "-y",
        "-ss", "00:00:03",        # 3s in — past intro fade-ins
        "-i", str(clip_path),
        "-frames:v", "1",
        "-vf", f"scale={width}:-2",
        "-q:v", "5",
        str(thumb),
    ]
    try:
        subprocess.run(cmd, check=True, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return thumb if thumb.exists() else None
    except subprocess.CalledProcessError as e:
        log.debug(f"thumbnail failed for {clip_path.name}: {e.stderr.decode()[-160:] if e.stderr else ''}")
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
