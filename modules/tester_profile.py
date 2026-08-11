"""Local, editable taste profile for clipping-beta testers."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from config import paths

PROFILE_DIR = paths.DATA_DIR / "tester_profiles"
_SAFE_ID = re.compile(r"[^a-zA-Z0-9_-]+")

PRESETS: dict[str, dict[str, Any]] = {
    "general": {
        "label": "General",
        "description": "Complete setup and payoff, clear context, low filler, and a strong opening hook.",
        "traits": ["hook", "complete payoff", "clear context", "tight pacing", "visual relevance"],
        "preferred_duration": [15, 60],
    },
    "default": {
        "label": "Default",
        "description": "Balanced highlights with clear speech, energetic moments, and a satisfying payoff.",
        "traits": ["balanced highlights", "clear speech", "energetic moments", "tight payoff", "visual relevance"],
        "preferred_duration": [15, 60],
    },
    "personalized": {
        "label": "Personalized",
        "description": "Starts neutral and learns only from confirmed examples and explicit feedback.",
        "traits": [],
        "preferred_duration": [15, 60],
    },
}


def _profile_path(user_id: str) -> Path:
    safe = _SAFE_ID.sub("-", user_id.strip())[:80] or "local-tester"
    return PROFILE_DIR / f"{safe}.json"


def _default(user_id: str, preset: str = "general") -> dict[str, Any]:
    selected = PRESETS.get(preset, PRESETS["general"])
    timestamp = time.time()
    return {
        "version": 1,
        "user_id": user_id,
        "preset": preset if preset in PRESETS else "general",
        "traits": list(selected["traits"]),
        "preferred_duration": list(selected["preferred_duration"]),
        "notes": "",
        "examples": [],
        "calibration_feedback": [],
        "onboarding_complete": False,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def presets() -> list[dict[str, Any]]:
    return [{"id": key, **value} for key, value in PRESETS.items()]


def load_profile(user_id: str) -> dict[str, Any]:
    path = _profile_path(user_id)
    if not path.exists():
        return _default(user_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else _default(user_id)
    except (OSError, json.JSONDecodeError):
        return _default(user_id)


def save_profile(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    existing = load_profile(user_id)
    preset = str(payload.get("preset") or existing.get("preset") or "general").lower()
    if preset not in PRESETS:
        raise ValueError("unknown taste preset")
    traits = []
    for raw in payload.get("traits", existing.get("traits", [])):
        value = str(raw).strip().lower()[:80]
        if value and value not in traits:
            traits.append(value)
    duration = payload.get("preferred_duration", existing.get("preferred_duration", [15, 60]))
    if not isinstance(duration, list) or len(duration) != 2:
        raise ValueError("preferred_duration must be [minimum, maximum]")
    minimum, maximum = max(1, float(duration[0])), min(600, float(duration[1]))
    if maximum <= minimum:
        raise ValueError("preferred duration maximum must exceed minimum")
    examples = []
    for raw in payload.get("examples", existing.get("examples", []))[:20]:
        if not isinstance(raw, dict):
            continue
        examples.append({
            "path": str(raw.get("path") or "")[:1000],
            "label": "bad" if raw.get("label") == "bad" else "good",
            "reason": str(raw.get("reason") or "")[:1000],
        })
    profile = {
        **existing,
        "preset": preset,
        "traits": traits[:30],
        "preferred_duration": [minimum, maximum],
        "notes": str(payload.get("notes", existing.get("notes", "")))[:8000],
        "examples": examples,
        "calibration_feedback": list(payload.get("calibration_feedback", existing.get("calibration_feedback", [])))[-500:],
        "onboarding_complete": bool(payload.get("onboarding_complete", existing.get("onboarding_complete", False))),
        "updated_at": time.time(),
    }
    path = _profile_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(pending, path)
    return profile


def add_feedback(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    profile = load_profile(user_id)
    feedback = list(profile.get("calibration_feedback") or [])
    signal = str(payload.get("signal") or "").lower()
    if signal not in {"good", "true_miss", "boundary", "null"}:
        raise ValueError("signal must be good, true_miss, boundary, or null")
    feedback.append({
        "candidate_id": str(payload.get("candidate_id") or "")[:100],
        "signal": signal,
        "notes": str(payload.get("notes") or "")[:2000],
        "start": payload.get("start"),
        "end": payload.get("end"),
        "created_at": time.time(),
    })
    return save_profile(user_id, {**profile, "calibration_feedback": feedback[-500:]})


def reset_profile(user_id: str, preset: str) -> dict[str, Any]:
    profile = _default(user_id, preset)
    path = _profile_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    os.replace(pending, path)
    return profile
