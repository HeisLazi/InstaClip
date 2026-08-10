"""Resolve a candidate's source VOD to a real file on disk.

The JSON→DB migration stored each candidate's VOD as the bare *filename*
(e.g. "stream.mp4"), not a full path. So preview/render code that did
`Path(vod.path)` couldn't find the file even when it sits in the configured VOD
folder. This resolves a stored path-or-name to an actual file by checking it
directly, then searching the known VOD directories.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("vod_resolver")


def _search_dirs() -> list[Path]:
    dirs: list[Path] = []
    try:
        from config import cfg, paths
        local = getattr(getattr(cfg, "fetcher", None), "local_vod_dir", None)
        if local:
            dirs.append(Path(local))
        dirs.append(paths.RAW_VODS_DIR)
    except Exception:  # noqa: BLE001 — config may be unavailable in some contexts
        pass
    # de-dup, keep existing
    seen, out = set(), []
    for d in dirs:
        key = str(d).lower()
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def resolve_vod_path(stored: Optional[str], *, search_dirs: Optional[list[Path]] = None) -> Optional[Path]:
    """Return a real existing VOD file Path, or None.

    Tries the stored value as-is, then `{vod_dir}/{filename}`, then a recursive
    search of the VOD dirs for the filename.
    """
    if not stored:
        return None
    p = Path(stored)
    if p.is_file():
        return p

    name = p.name
    dirs = search_dirs if search_dirs is not None else _search_dirs()

    for d in dirs:
        cand = Path(d) / name
        if cand.is_file():
            return cand
    # Recursive fallback (subfolders).
    for d in dirs:
        base = Path(d)
        if base.is_dir():
            try:
                for found in base.rglob(name):
                    if found.is_file():
                        return found
            except OSError:
                continue
    log.warning("could not resolve VOD on disk: %s", stored)
    return None


__all__ = ["resolve_vod_path"]
