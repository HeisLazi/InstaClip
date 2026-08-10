# =============================================================================
# utils/file_utils.py — Shared File I/O Helpers
# =============================================================================
# Used by: all modules
# =============================================================================

import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger("utils.file")


def save_json(data: dict, path: Path, versioned: bool = False) -> Path:
    """
    Save a dictionary as a JSON file.

    Args:
        data:      Dictionary to serialize
        path:      Target file path (e.g. profiles/lek_profile.json)
        versioned: If True, also saves a timestamped copy for rollback

    Returns:
        The path the file was saved to.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    log.info(f"Saved: {path}")

    if versioned:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        versioned_path = path.parent / f"{path.stem}_v{timestamp}{path.suffix}"
        with open(versioned_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log.info(f"Versioned copy saved: {versioned_path}")

    return path


def load_json(path: Path) -> dict:
    """
    Load a JSON file. Returns empty dict if file doesn't exist.
    """
    if not path.exists():
        log.warning(f"JSON not found: {path}")
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def find_video_files(directory: Path) -> list[Path]:
    """
    Return all .mp4 files below a directory, sorted by name.
    """
    files = sorted(directory.rglob("*.mp4"))
    if not files:
        log.warning(f"No .mp4 files found in: {directory}")
    return files
