# =============================================================================
# modules/fetcher/fetcher.py — Module 1: The Fetcher
# Project LeK — Auto Clipper V1
# =============================================================================
# PURPOSE:
#   Resolve a VOD source (local file, local folder, or URL) into a single
#   video file path that Module 2 (Listener) can process.
#
# DATA CONTRACT:
#   Input:  source — one of:
#               - URL string       (Twitch/YouTube)
#               - local file path  (specific .mp4 or other video)
#               - None             (interactive picker from local_vod_dir)
#   Output: Path to a single video file ready for transcription
#
# CONSUMED BY:
#   modules/listener/listener.py
# =============================================================================

import logging
from pathlib import Path

from config import cfg, paths

log = logging.getLogger("fetcher")


# =============================================================================
# URL DETECTION
# =============================================================================

def is_url(source: str) -> bool:
    """Check if the source string is a web URL."""
    return source.startswith("http://") or source.startswith("https://")


# =============================================================================
# LOCAL VOD PICKER
# =============================================================================

def list_local_vods() -> list[Path]:
    """
    Scan the configured local VOD directory for supported video files.
    Returns sorted list of Paths.
    """
    vod_dir = cfg.fetcher.local_vod_dir
    if not vod_dir.exists():
        log.error(f"Local VOD directory not found: {vod_dir}")
        return []

    files = []
    for ext in cfg.fetcher.supported_extensions:
        files.extend(vod_dir.glob(f"*{ext}"))
        files.extend(vod_dir.glob(f"*{ext.upper()}"))

    return sorted(set(files))


def pick_local_vod() -> Path | None:
    """
    Interactively list local VODs and let user pick one by number.
    Returns selected Path or None if user cancels.
    """
    vods = list_local_vods()
    if not vods:
        log.error(f"No VODs found in {cfg.fetcher.local_vod_dir}")
        return None

    print("\n" + "=" * 60)
    print("LOCAL VODS AVAILABLE")
    print("=" * 60)
    for i, vod in enumerate(vods, start=1):
        size_mb = round(vod.stat().st_size / (1024 * 1024), 1)
        print(f"  [{i:>3}] {vod.name}  ({size_mb} MB)")
    print("=" * 60)

    while True:
        choice = input("Enter VOD number (or 'q' to quit): ").strip()
        if choice.lower() == "q":
            return None
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(vods):
                selected = vods[idx]
                log.info(f"Selected local VOD: {selected.name}")
                return selected
            else:
                print(f"  Enter a number between 1 and {len(vods)}")
        except ValueError:
            print("  Invalid input — enter a number.")


# =============================================================================
# URL DOWNLOADER
# =============================================================================

def download_vod(url: str) -> Path | None:
    """
    Download a VOD from Twitch/YouTube using yt-dlp's Python API
    (works in frozen .exe builds where yt-dlp.exe isn't on PATH).

    Data contract:
        Input:  URL string
        Output: Path to downloaded file, or None on failure
    """
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        log.critical("yt-dlp Python package not available — run: pip install yt-dlp")
        return None

    output_template = str(
        paths.RAW_VODS_DIR / cfg.fetcher.yt_dlp_output_template
    )

    opts = {
        "format": cfg.fetcher.yt_dlp_format,
        "outtmpl": output_template,
        "noplaylist": True,
        "socket_timeout": 60,
        "retries": 3,
    }

    log.info(f"Downloading VOD from: {url}")
    log.info("This may take a while for long VODs...")

    try:
        with YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as e:
        log.error(f"yt-dlp download failed: {e}")
        return None

    vods = sorted(
        [p for p in paths.RAW_VODS_DIR.glob("*.*")
         if p.suffix.lower() in cfg.fetcher.supported_extensions],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if vods:
        log.info(f"Downloaded: {vods[0].name}")
        return vods[0]

    log.error("Download seemed to succeed but file not found.")
    return None


# =============================================================================
# PUBLIC INTERFACE
# =============================================================================

def fetch_vod(source: str | None = None) -> Path | None:
    """
    Main fetcher entry point.

    Args:
        source: URL string, local file path string, or None for interactive picker

    Data contract:
        Input:  str | None
        Output: Path to video file ready for Module 2, or None on failure
    """
    log.info("=" * 60)
    log.info("MODULE 1: FETCHER")
    log.info("=" * 60)

    # Case 1: No source — interactive local picker
    if source is None:
        log.info("No source provided — launching local VOD picker.")
        vod_path = pick_local_vod()

    # Case 2: URL
    elif is_url(source):
        log.info(f"URL detected: {source}")
        vod_path = download_vod(source)

    # Case 3: Local file path
    else:
        vod_path = Path(source)
        if not vod_path.exists():
            log.error(f"File not found: {vod_path}")
            return None
        if vod_path.suffix.lower() not in cfg.fetcher.supported_extensions:
            log.error(f"Unsupported file type: {vod_path.suffix}")
            return None
        log.info(f"Local file: {vod_path.name}")

    if vod_path is None:
        log.error("Fetcher returned no VOD. Pipeline halted.")
        return None

    size_mb = round(vod_path.stat().st_size / (1024 * 1024), 1)
    log.info(f"VOD ready: {vod_path.name} ({size_mb} MB)")
    log.info("=" * 60)
    log.info("NEXT: Module 2 (Listener) will transcribe this VOD")
    log.info("=" * 60)

    return vod_path


# =============================================================================
# STANDALONE ENTRY POINT
# python modules/fetcher/fetcher.py                         <- interactive picker
# python modules/fetcher/fetcher.py "URL"                   <- download from URL
# python modules/fetcher/fetcher.py "/path/to/video.mp4"    <- specific local file
# =============================================================================
if __name__ == "__main__":
    import sys
    source_arg = sys.argv[1] if len(sys.argv) > 1 else None
    result = fetch_vod(source_arg)
    if result:
        print(f"\nFetcher output: {result}")
