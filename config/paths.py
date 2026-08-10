# =============================================================================
# config/paths.py — All filesystem paths for Project LeK
# =============================================================================
# RULE: No other file hardcodes a path. Ever. Import from here.
# =============================================================================

import os
import sys
from pathlib import Path

# Project root = the folder containing the config/ directory.
# When running as a PyInstaller-frozen .exe, files like settings.json and
# the user's data live next to the .exe — NOT inside the _internal bundle.
if os.environ.get("INSTACLIP_DATA_ROOT"):
    ROOT_DIR = Path(os.environ["INSTACLIP_DATA_ROOT"]).expanduser().resolve()
elif getattr(sys, "frozen", False) or os.environ.get("INSTACLIP_EDITION", "").strip().lower() == "clipper":
    # Frozen builds AND any clipper-edition run isolate to the per-user app data
    # folder. The clipper edition must never fall through to the repo tree — that
    # would point a tester build at the owner's private data/DB (WS1 isolation).
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    ROOT_DIR = (local / "InstaClipClipperBeta").resolve()
else:
    ROOT_DIR = Path(__file__).parent.parent.resolve()

# -----------------------------------------------------------------------------
# DATA DIRECTORIES
# -----------------------------------------------------------------------------
DATA_DIR         = ROOT_DIR / "data"
OLD_CLIPS_DIR    = DATA_DIR / "old_clips"      # Module 0 input
AUDIO_DIR        = DATA_DIR / "audio"          # Extracted .wav files
CHATS_DIR        = DATA_DIR / "chats"          # Module 3 — chat logs (.json)
RAW_VODS_DIR     = DATA_DIR / "raw_vods"       # Module 1 — downloaded VODs
PROFILES_DIR     = DATA_DIR / "profiles"       # lek_profile.json lives here
TRANSCRIPTS_DIR  = DATA_DIR / "transcripts"    # Raw transcript cache
TRANSCRIPT_CHECKPOINTS_DIR = DATA_DIR / "transcript_checkpoints"
CLIP_TRANSCRIPTS_DIR = DATA_DIR / "clip_transcripts"  # Per-clip text cache (classifier)
CLIP_REVIEWS_FILE = DATA_DIR / "clip_reviews.json"    # Human clip ratings + reasons
EDITOR_PROJECTS_DIR = DATA_DIR / "editor_projects"
EDITOR_WAVEFORMS_DIR = DATA_DIR / "editor_waveforms"
EDITOR_AUDIO_PROXIES_DIR = DATA_DIR / "editor_audio_proxies"
EDITOR_VIDEO_PROXIES_DIR = DATA_DIR / "editor_video_proxies"
STORY_MEDIA_SIGNALS_DIR = DATA_DIR / "story_media_signals"

# -----------------------------------------------------------------------------
# OUTPUT DIRECTORIES
# -----------------------------------------------------------------------------
OUTPUT_DIR       = ROOT_DIR / "output"
CLIPS_DIR        = OUTPUT_DIR / "clips"        # Final approved clips
NOTCLIPS_DIR     = OUTPUT_DIR / "notclips"     # Rejected — review queue
METADATA_DIR     = OUTPUT_DIR / "metadata"     # Clip metadata + highlight JSON
KEEPERS_DIR      = OUTPUT_DIR / "keepers"      # Per-VOD shortcut to "good" clips (hard links)
PUBLISH_PACKAGES_DIR = OUTPUT_DIR / "publish_packages"
PUBLISH_QUEUE_FILE   = OUTPUT_DIR / "publish_queue.json"

# -----------------------------------------------------------------------------
# KEY FILES
# -----------------------------------------------------------------------------
PROFILE_PATH     = PROFILES_DIR / "lek_profile.json"
LOG_FILE         = ROOT_DIR / "logs" / "pipeline.log"
SETTINGS_FILE    = ROOT_DIR / "config" / "settings.json"

# -----------------------------------------------------------------------------
# MODULE DIRECTORIES (for reference — no files written here directly)
# -----------------------------------------------------------------------------
MODULES_DIR      = ROOT_DIR / "modules"

# -----------------------------------------------------------------------------
# BUNDLED (READ-ONLY) RESOURCES shipped inside the installer
# -----------------------------------------------------------------------------
# PyInstaller unpacks bundled `datas` to sys._MEIPASS at runtime; in a normal
# dev checkout the repo root plays the same role. This is where pre-bundled
# models live (read-only) — distinct from the writable DATA_DIR.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", ROOT_DIR)).resolve()
# Writable fallback cache for any model that still has to be downloaded at
# runtime (kept inside the app's own data dir, not the roaming HF cache).
WHISPER_DOWNLOAD_DIR = DATA_DIR / "models" / "whisper"


def bundled_whisper_dir(size: str) -> Path:
    """Where a pre-bundled faster-whisper model of a given size would live."""
    return BUNDLE_DIR / "models" / f"whisper-{size}"


def ensure_dirs() -> None:
    """
    Create all required project directories if they don't exist.
    Called once at startup via config/__init__.py.
    """
    dirs = [
        DATA_DIR,
        OLD_CLIPS_DIR,
        AUDIO_DIR,
        CHATS_DIR,
        RAW_VODS_DIR,
        PROFILES_DIR,
        TRANSCRIPTS_DIR,
        TRANSCRIPT_CHECKPOINTS_DIR,
        CLIP_TRANSCRIPTS_DIR,
        EDITOR_PROJECTS_DIR,
        EDITOR_WAVEFORMS_DIR,
        EDITOR_AUDIO_PROXIES_DIR,
        EDITOR_VIDEO_PROXIES_DIR,
        STORY_MEDIA_SIGNALS_DIR,
        OUTPUT_DIR,
        CLIPS_DIR,
        NOTCLIPS_DIR,
        METADATA_DIR,
        KEEPERS_DIR,
        PUBLISH_PACKAGES_DIR,
        ROOT_DIR / "logs",
        ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
