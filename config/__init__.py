# =============================================================================
# config/__init__.py — Central Configuration Loader
# =============================================================================
# Loads settings.json and exposes typed config values.
# Every module does: from config import cfg, paths
# =============================================================================

import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

from config.paths import SETTINGS_FILE, ensure_dirs


def _load_settings() -> dict:
    if not SETTINGS_FILE.exists():
        print(f"[FATAL] settings.json not found at: {SETTINGS_FILE}")
        sys.exit(1)
    with open(SETTINGS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _setup_logging(level_str: str) -> None:
    from config.paths import LOG_FILE
    level = getattr(logging, level_str.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


# =============================================================================
# Load on import
# =============================================================================
ensure_dirs()
_raw = _load_settings()
_setup_logging(_raw["logging"]["level"])

# Build slang lookup: alias -> canonical
_slang_lookup = {}
for canonical, aliases in _raw["profiler"].get("slang_dictionary", {}).items():
    for alias in aliases:
        _slang_lookup[alias.lower()] = canonical.lower()

cfg = SimpleNamespace(
    whisper  = SimpleNamespace(**_raw["whisper"]),
    audio    = SimpleNamespace(**_raw["audio"]),

    fetcher  = SimpleNamespace(
        local_vod_dir          = Path(_raw["fetcher"]["local_vod_dir"]),
        supported_extensions   = _raw["fetcher"]["supported_extensions"],
        yt_dlp_format          = _raw["fetcher"]["yt_dlp_format"],
        yt_dlp_output_template = _raw["fetcher"]["yt_dlp_output_template"],
    ),

    listener = SimpleNamespace(
        word_timestamps      = _raw["listener"]["word_timestamps"],
        min_segment_duration = _raw["listener"]["min_segment_duration"],
        checkpoint_seconds   = int(_raw["listener"].get("checkpoint_seconds", 600)),
    ),

    profiler = SimpleNamespace(
        top_words                      = _raw["profiler"]["top_words"],
        top_phrases                    = _raw["profiler"]["top_phrases"],
        top_patterns                   = _raw["profiler"]["top_patterns"],
        stopwords                      = set(_raw["profiler"]["stopwords"]),
        background_frequency_threshold = _raw["profiler"]["background_frequency_threshold"],
        high_energy_percentile         = _raw["profiler"]["high_energy_percentile"],
        repetition_thresholds          = _raw["profiler"]["repetition_thresholds"],
        low_energy_patterns            = _raw["profiler"]["low_energy_patterns"],
        context_window                 = SimpleNamespace(**_raw["profiler"]["context_window"]),
        slang_dictionary               = _raw["profiler"].get("slang_dictionary", {}),
        slang_lookup                   = _slang_lookup,
        hype_words                     = set(_raw["profiler"].get("hype_words", [])),
    ),

    clip_engine = SimpleNamespace(
        selection_engine            = _raw["clip_engine"].get("selection_engine", "rules"),
        weights                     = _raw["clip_engine"]["score_weights"],
        highlight_threshold         = _raw["clip_engine"]["highlight_threshold"],
        pre_roll                    = _raw["clip_engine"]["pre_roll_seconds"],
        post_roll                   = _raw["clip_engine"]["post_roll_seconds"],
        face_detection_enabled      = _raw["clip_engine"].get("face_detection_enabled", False),
        quality_classifier_enabled  = _raw["clip_engine"].get("quality_classifier_enabled", False),
        quality_classifier_weight   = _raw["clip_engine"].get("quality_classifier_weight", 0.0),
        quality_min_keep            = _raw["clip_engine"].get("quality_min_keep", 0.0),
        vision_enabled              = _raw["clip_engine"].get("vision_enabled", False),
        vision_model                = _raw["clip_engine"].get("vision_model", "llava:7b"),
        vision_frames_per_highlight = _raw["clip_engine"].get("vision_frames_per_highlight", 3),
        speaker_id_enabled          = _raw["clip_engine"].get("speaker_id_enabled", False),
        speaker_id_target           = _raw["clip_engine"].get("speaker_id_target", "lazi"),
        speaker_id_threshold        = _raw["clip_engine"].get("speaker_id_threshold", 0.65),
        speaker_boost               = _raw["clip_engine"].get("speaker_boost", 0.0),
    ),

    web = SimpleNamespace(**_raw["web"]),
)

from config import paths  # noqa: E402
