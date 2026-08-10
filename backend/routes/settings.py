"""Read/patch settings.json."""

import json
from typing import Any

from fastapi import APIRouter, HTTPException

from config import paths

router = APIRouter(prefix="/settings", tags=["settings"])


def _read() -> dict:
    if not paths.SETTINGS_FILE.exists():
        raise HTTPException(500, "settings.json missing")
    with open(paths.SETTINGS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _write(raw: dict) -> None:
    with open(paths.SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)


@router.get("")
def get_settings():
    return _read()


@router.patch("")
def patch_settings(updates: dict[str, Any]):
    """
    Body is a partial dict; we deep-merge it into settings.json.
    Mirrors live cfg attributes where they exist so the change applies
    to long-running jobs in the same process.
    """
    raw = _read()
    _deep_merge(raw, updates)
    _write(raw)
    _mirror_to_cfg(updates)
    return raw


def _deep_merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v


def _mirror_to_cfg(updates: dict) -> None:
    """Best-effort live-update of the in-memory cfg SimpleNamespace."""
    from config import cfg
    for section, body in updates.items():
        ns = getattr(cfg, section, None)
        if ns is None or not isinstance(body, dict):
            continue
        for key, value in body.items():
            if hasattr(ns, key):
                setattr(ns, key, value)
