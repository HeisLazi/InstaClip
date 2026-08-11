"""Build the self-contained backend/FFmpeg sidecars required by Tauri."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BINARIES = ROOT / "frontend" / "src-tauri" / "binaries"
TRIPLE = "x86_64-pc-windows-msvc"


def _require_tool(name: str) -> Path:
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"{name} is required to build the tester package")
    return Path(resolved)


def main() -> None:
    BINARIES.mkdir(parents=True, exist_ok=True)
    subprocess.check_call([sys.executable, "-m", "PyInstaller", "ClipperBackend.spec", "--clean", "--noconfirm"], cwd=ROOT)
    backend = ROOT / "dist" / "instaclip-backend.exe"
    if not backend.exists():
        raise RuntimeError(f"PyInstaller did not create {backend}")
    shutil.copy2(backend, BINARIES / f"instaclip-backend-{TRIPLE}.exe")
    shutil.copy2(_require_tool("ffmpeg"), BINARIES / f"ffmpeg-{TRIPLE}.exe")
    shutil.copy2(_require_tool("ffprobe"), BINARIES / f"ffprobe-{TRIPLE}.exe")
    print(f"Prepared clipper sidecars in {BINARIES}")


if __name__ == "__main__":
    main()
