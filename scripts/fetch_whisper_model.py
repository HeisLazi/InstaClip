"""Build-time step: pre-fetch the faster-whisper model so it can be BUNDLED into
the installer instead of silently downloading ~1.5 GB on a buyer's first run.

Run this BEFORE building the clipper installer:

    python scripts/fetch_whisper_model.py            # uses cfg.whisper.model_size
    python scripts/fetch_whisper_model.py --size small

It downloads the CTranslate2-converted model into `models/whisper-<size>/`, which
`ClipperBackend.spec` then ships as bundled data. At runtime
`utils.whisper_utils.resolve_model_source` finds it and loads it in place with no
network call. Idempotent — skips the download if the model is already present.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# faster-whisper's official CTranslate2 conversions live under the Systran org.
_REPO = "Systran/faster-whisper-{size}"


def _default_size() -> str:
    try:
        sys.path.insert(0, str(ROOT))
        from config import cfg
        return str(getattr(cfg.whisper, "model_size", "medium") or "medium")
    except Exception:  # noqa: BLE001
        return "medium"


def fetch(size: str) -> Path:
    dest = ROOT / "models" / f"whisper-{size}"
    if (dest / "model.bin").exists():
        print(f"[fetch_whisper] already present: {dest}")
        return dest
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        raise SystemExit("huggingface_hub is required: pip install huggingface_hub")
    dest.mkdir(parents=True, exist_ok=True)
    print(f"[fetch_whisper] downloading {_REPO.format(size=size)} -> {dest} ...")
    snapshot_download(
        repo_id=_REPO.format(size=size),
        local_dir=str(dest),
        local_dir_use_symlinks=False,
        allow_patterns=["*.bin", "*.json", "*.txt", "vocabulary*"],
    )
    if not (dest / "model.bin").exists():
        raise SystemExit(f"[fetch_whisper] download did not yield model.bin in {dest}")
    print(f"[fetch_whisper] done: {dest}")
    return dest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", default=None, help="whisper model size (default: cfg.whisper.model_size)")
    args = parser.parse_args()
    fetch(args.size or _default_size())
