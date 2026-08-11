"""Deterministic Whisper-model bundling decision for the clipper installer build.

Extracted from ClipperBackend.spec so it can be unit-tested (success AND failure
paths). Fixes three validator defects found in review:
  1. a zero/truncated `model.bin` used to pass — now it must exceed a sane floor
     (a real CTranslate2 model.bin is hundreds of MB);
  2. `INSTACLIP_ALLOW_UNBUNDLED_MODEL=false` used to bypass because ANY non-empty
     value counted — now only genuinely truthy values bypass;
  3. every valid `whisper-*` dir got bundled — now ONLY the configured model is,
     so we never ship a model the app won't load (and never bloat the installer).

Note: full determinism (pin exact revision/size/SHA-256) lands once the
small-vs-medium benchmark selects the shipping model; this closes the correctness
holes that are independent of which model is chosen.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

# A real faster-whisper model.bin is >=~75 MB (tiny) up to ~3 GB (large-v3).
# Anything smaller than this floor is a zero/truncated/partial download.
MIN_MODEL_BIN_BYTES = 10 * 1024 * 1024  # 10 MB
_TRUTHY = {"1", "true", "yes", "on"}


def is_truthy(value: Optional[str]) -> bool:
    """Only genuinely-affirmative env values count. 'false'/'0'/'' do NOT bypass."""
    return str(value or "").strip().lower() in _TRUTHY


def valid_model_bin(model_dir: Path) -> bool:
    """A model dir counts as bundled only if model.bin exists AND is real-sized."""
    model_bin = model_dir / "model.bin"
    try:
        return model_bin.is_file() and model_bin.stat().st_size >= MIN_MODEL_BIN_BYTES
    except OSError:
        return False


def plan_whisper_bundle(models_root: Path, configured_size: Optional[str],
                        allow_unbundled: Optional[str]) -> dict:
    """Decide what to bundle. Returns:
        {"ok": bool, "datas": [(src, dest)], "reason": str}
    `ok=False` means the build MUST fail (caller raises). `datas` is what to add
    to PyInstaller (only the configured model, and only if valid)."""
    if not configured_size:
        return {"ok": False, "datas": [], "reason": "no configured whisper model_size"}
    want_dir = models_root / f"whisper-{configured_size}"
    if valid_model_bin(want_dir):
        return {"ok": True,
                "datas": [(str(want_dir), f"models/whisper-{configured_size}")],
                "reason": f"bundling validated model whisper-{configured_size}"}
    # Configured model is missing/partial.
    present = sorted(p.name for p in models_root.glob("whisper-*")) if models_root.exists() else []
    detail = (f"configured model 'whisper-{configured_size}' has no valid model.bin "
              f"(>= {MIN_MODEL_BIN_BYTES // (1024*1024)} MB). Present dirs: {present}. "
              f"Run scripts/fetch_whisper_model.py --size {configured_size}.")
    if is_truthy(allow_unbundled):
        return {"ok": True, "datas": [],
                "reason": "download-fallback build (INSTACLIP_ALLOW_UNBUNDLED_MODEL set): " + detail}
    return {"ok": False, "datas": [], "reason": detail}


__all__ = ["plan_whisper_bundle", "valid_model_bin", "is_truthy", "MIN_MODEL_BIN_BYTES"]
