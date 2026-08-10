"""System health probe — feeds the Status / Dashboard pages."""

import shutil
from pathlib import Path

from fastapi import APIRouter

from config import cfg, paths

router = APIRouter(tags=["status"])


@router.get("/status")
def status():
    from modules.face_detector.face_detector import MEDIAPIPE_AVAILABLE
    from modules.quality_classifier.embeddings import ollama_alive
    from modules.quality_classifier.predictor import model_available
    from modules.speaker_id.speaker_id import list_speakers, resemblyzer_available
    from modules.vision_describer.vision_describer import vision_alive

    vision_ok, vision_msg = vision_alive(cfg.clip_engine.vision_model)
    return {
        "vod_folder": {
            "path":   str(cfg.fetcher.local_vod_dir),
            "exists": Path(cfg.fetcher.local_vod_dir).exists(),
        },
        "ffmpeg":            {"on_path": shutil.which("ffmpeg") is not None},
        "profile":           {"trained": paths.PROFILE_PATH.exists()},
        "quality_classifier":{"trained": model_available()},
        "ollama":            {"alive": ollama_alive()},
        "vision":            {"model": cfg.clip_engine.vision_model,
                              "ok":    vision_ok,
                              "msg":   vision_msg,
                              "enabled": cfg.clip_engine.vision_enabled},
        "face_detector":     {"available": MEDIAPIPE_AVAILABLE},
        "speaker_id":        {
            "resemblyzer":   resemblyzer_available(),
            "speakers":      list_speakers(),
            "enabled":       cfg.clip_engine.speaker_id_enabled,
            "target":        cfg.clip_engine.speaker_id_target,
        },
        "twitch":            {"configured": False},
        "note":              "Twitch integration is not included in the public edition.",
        "whisper":           {"device":     cfg.whisper.device,
                              "model_size": cfg.whisper.model_size},
        "paths":             {
            "clips_out":       str(paths.CLIPS_DIR),
            "old_clips":       str(paths.OLD_CLIPS_DIR),
            "notclips":        str(paths.OUTPUT_DIR / "notclips"),
            "log":             str(paths.LOG_FILE),
            "crash_log":       str(paths.ROOT_DIR / "logs" / "crash.log"),
            "settings":        str(paths.SETTINGS_FILE),
            "root":            str(paths.ROOT_DIR),
        },
    }


@router.get("/status/counts")
def counts():
    """Light endpoint for the dashboard's action-items card."""
    def _count(p: Path) -> int:
        return len(list(p.rglob("*.mp4"))) if p.exists() else 0
    return {
        "positives": _count(paths.OLD_CLIPS_DIR),
        "negatives": _count(paths.OUTPUT_DIR / "notclips"),
        "newly_cut": _count(paths.CLIPS_DIR),
    }
