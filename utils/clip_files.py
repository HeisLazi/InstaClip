"""Shared helpers for nested clip libraries."""

from __future__ import annotations

import re
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".flv", ".webm"}


def safe_folder_name(value: str, fallback: str = "unsorted") -> str:
    stem = Path(value).stem
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .")
    return cleaned or fallback


def iter_video_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS),
        key=lambda path: path.name.lower(),
    )


def find_clip_file(root: Path, stem: str) -> Path | None:
    if not stem or Path(stem).name != stem:
        return None
    direct = root / f"{stem}.mp4"
    if direct.exists():
        return direct
    matches = list(root.rglob(f"{stem}.mp4")) if root.exists() else []
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def relative_group(root: Path, clip: Path) -> str | None:
    try:
        relative_parent = clip.parent.relative_to(root)
    except ValueError:
        return None
    if relative_parent == Path("."):
        return None
    return relative_parent.as_posix()
