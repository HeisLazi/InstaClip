"""Frozen FastAPI entry point used by the Tauri clipping-beta installer."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def _prepare_runtime() -> Path:
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    root = Path(os.environ.get("INSTACLIP_DATA_ROOT") or local / "InstaClipClipperBeta").resolve()
    os.environ["INSTACLIP_DATA_ROOT"] = str(root)
    os.environ["INSTACLIP_BUNDLE_ROOT"] = str(_bundle_root())
    os.environ.setdefault("INSTACLIP_EDITION", "clipper")
    root.mkdir(parents=True, exist_ok=True)
    settings = root / "config" / "settings.json"
    if not settings.exists():
        settings.parent.mkdir(parents=True, exist_ok=True)
        bundled = _bundle_root() / "config" / "settings.json"
        if not bundled.exists():
            raise RuntimeError(f"Bundled settings missing: {bundled}")
        shutil.copy2(bundled, settings)

    executable_dir = Path(sys.executable).resolve().parent
    os.environ["PATH"] = os.pathsep.join([str(executable_dir), str(_bundle_root()), os.environ.get("PATH", "")])
    return root


def main() -> None:
    _prepare_runtime()
    import uvicorn

    uvicorn.run("backend.main:app", host="127.0.0.1", port=8765, workers=1, log_level="info")


if __name__ == "__main__":
    main()
