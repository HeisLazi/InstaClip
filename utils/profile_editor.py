"""
Read/write helpers for data/profiles/lek_profile.json.

Used by the GUI's Profile editor tab and by the LLM-based profile tuner.
"""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from config import paths

log = logging.getLogger("profile_editor")

EDITABLE_LISTS = {
    "highlight_words":     {"label": "Highlight words",
                            "desc": "Words that boost a segment's score (positive signal)."},
    "background_words":    {"label": "Background words",
                            "desc": "Words you say all the time — when too many appear, score drops."},
    "penalized_words":     {"label": "Penalized words",
                            "desc": "Words that suggest a low-quality moment (drop score hard)."},
    "low_energy_patterns": {"label": "Low-energy patterns",
                            "desc": "Phrases that indicate calm/thoughtful talk, not a clip."},
}

# These are dict-list shapes ({"phrase": str, "score": float} or
# {"pattern": str, "score": float}).
EDITABLE_DICT_LISTS = {
    "hype_phrases":        {"label": "Hype phrases",
                            "desc": "Multi-word patterns that often appear in your good clips.",
                            "key_field": "phrase"},
    "repetition_patterns": {"label": "Repetition patterns",
                            "desc": "Repeated phrases that scored well.",
                            "key_field": "pattern"},
}


# =============================================================================
# Load / save
# =============================================================================

def load_profile() -> dict:
    if not paths.PROFILE_PATH.exists():
        return {}
    with open(paths.PROFILE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _backup_profile() -> Path | None:
    if not paths.PROFILE_PATH.exists():
        return None
    backup = paths.PROFILES_DIR / f"lek_profile_v{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    shutil.copy2(paths.PROFILE_PATH, backup)
    return backup


def save_profile(profile: dict) -> Path:
    """Save the profile, backing up the previous version first."""
    backup = _backup_profile()
    paths.PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    with open(paths.PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)
    if backup:
        log.info(f"Profile saved (backup: {backup.name})")
    else:
        log.info("Profile saved (no prior version to back up).")
    return paths.PROFILE_PATH


# =============================================================================
# Atomic list mutations
# =============================================================================

def add_to_list(profile: dict, key: str, value: Any) -> bool:
    """Add a value to a list field. Returns True if it was a new addition."""
    if key not in profile:
        profile[key] = []
    lst = profile[key]
    if key in EDITABLE_DICT_LISTS:
        kf = EDITABLE_DICT_LISTS[key]["key_field"]
        existing = {(item.get(kf) if isinstance(item, dict) else item) for item in lst}
        if isinstance(value, dict) and value.get(kf) in existing:
            return False
        if isinstance(value, str) and value in existing:
            return False
        if isinstance(value, str):
            value = {kf: value, "score": 0.5}
        lst.append(value)
        return True

    # Plain string list.
    if isinstance(value, str) and value in lst:
        return False
    lst.append(value)
    return True


def remove_from_list(profile: dict, key: str, value: Any) -> bool:
    """Remove a value from a list field. Returns True if it was present."""
    if key not in profile:
        return False
    lst = profile[key]
    if key in EDITABLE_DICT_LISTS:
        kf = EDITABLE_DICT_LISTS[key]["key_field"]
        target = value.get(kf) if isinstance(value, dict) else value
        before = len(lst)
        profile[key] = [
            item for item in lst
            if (item.get(kf) if isinstance(item, dict) else item) != target
        ]
        return len(profile[key]) != before

    if value in lst:
        lst.remove(value)
        return True
    return False


# =============================================================================
# Applying an LLM-suggested patch
# =============================================================================

def apply_patch(profile: dict, patch: dict) -> dict:
    """
    Apply a structured patch produced by the LLM tuner. Patch shape:
      {
        "add":    {"highlight_words": ["foo", "bar"], "hype_phrases": ["yo what"], ...},
        "remove": {"penalized_words": ["bruh"], ...}
      }
    Returns a stats summary.
    """
    added = 0
    removed = 0
    skipped = 0

    for key, values in (patch.get("add") or {}).items():
        if key not in EDITABLE_LISTS and key not in EDITABLE_DICT_LISTS:
            skipped += len(values)
            continue
        for v in values:
            if add_to_list(profile, key, v):
                added += 1
            else:
                skipped += 1

    for key, values in (patch.get("remove") or {}).items():
        if key not in EDITABLE_LISTS and key not in EDITABLE_DICT_LISTS:
            skipped += len(values)
            continue
        for v in values:
            if remove_from_list(profile, key, v):
                removed += 1
            else:
                skipped += 1

    return {"added": added, "removed": removed, "skipped": skipped}
