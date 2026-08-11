# =============================================================================
# modules/face_detector/face_detector.py — Face Reaction Detector
# =============================================================================
# Detects facial reactions per second in a VOD using MediaPipe Tasks
# (FaceLandmarker with blendshapes). Output is a {second: score} dict the
# clip_engine merges with the audio/text signals.
#
# Why blendshapes: MediaPipe's FaceLandmarker emits standardized 0-1 scores
# for ~52 expression categories (jawOpen, browInnerUp, mouthSmileLeft, etc).
# That's more stable than guessing reactions from raw landmark coordinates.
#
# Model: face_landmarker.task is downloaded on first run to data/models/.
# (~3MB, one-time. After that, fully offline.)
# =============================================================================

import json
import logging
import urllib.request
from pathlib import Path

from config import paths

log = logging.getLogger("face_detector")

# Lazy native-binding imports — keep startup cheap and tolerant.
try:
    import cv2
    import mediapipe as mp
    import numpy as np
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python.vision import (
        FaceLandmarker,
        FaceLandmarkerOptions,
        RunningMode,
    )
    MEDIAPIPE_AVAILABLE = True
except Exception as e:
    MEDIAPIPE_AVAILABLE = False
    log.warning(f"MediaPipe Tasks unavailable: {e}")


MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/latest/face_landmarker.task"
)
MODEL_DIR = paths.DATA_DIR / "models"
MODEL_PATH = MODEL_DIR / "face_landmarker.task"


# =============================================================================
# CACHE
# =============================================================================

def get_face_cache_path(vod_path: Path) -> Path:
    return paths.TRANSCRIPTS_DIR / (vod_path.stem + "_face.json")


def face_cache_exists(vod_path: Path) -> bool:
    return get_face_cache_path(vod_path).exists()


def load_face_cache(vod_path: Path) -> dict:
    path = get_face_cache_path(vod_path)
    log.info(f"Loading cached face data: {path.name}")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {int(k): float(v) for k, v in raw.items()}


def save_face_cache(data: dict, vod_path: Path) -> None:
    path = get_face_cache_path(vod_path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    log.info(f"Face data cached: {path.name}")


# =============================================================================
# MODEL ASSET MANAGEMENT
# =============================================================================

def _ensure_model() -> Path | None:
    """Download the face_landmarker.task model on first use. Cached after."""
    if MODEL_PATH.exists():
        return MODEL_PATH

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    log.info(f"Downloading face landmarker model (~3MB) to {MODEL_PATH}...")
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=60) as resp:
            data = resp.read()
        MODEL_PATH.write_bytes(data)
        log.info("Model downloaded successfully.")
        return MODEL_PATH
    except Exception as e:
        log.error(f"Could not download face landmarker model: {e}")
        return None


# =============================================================================
# BLENDSHAPE SCORERS
# =============================================================================
# Blendshapes are returned by FaceLandmarker as a list of Category(name, score)
# entries — we read by name to be robust to ordering changes between versions.

_REACTION_BLENDSHAPES = {
    # Strong reaction signals — surprise / shock / open-mouth laughs.
    "jawOpen":         0.35,
    "mouthFunnel":     0.10,
    "mouthPucker":     0.05,
    "browInnerUp":     0.15,
    "browOuterUpLeft": 0.10,
    "browOuterUpRight":0.10,
    "eyeWideLeft":     0.08,
    "eyeWideRight":    0.08,
    "mouthSmileLeft":  0.05,
    "mouthSmileRight": 0.05,
}


def _score_from_blendshapes(blendshapes) -> float:
    if not blendshapes:
        return 0.0
    by_name = {b.category_name: float(b.score) for b in blendshapes}
    total = 0.0
    for name, weight in _REACTION_BLENDSHAPES.items():
        total += by_name.get(name, 0.0) * weight
    return float(min(total, 1.0))


# =============================================================================
# MAIN PROCESSOR
# =============================================================================

def analyze_face_reactions(vod_path: Path) -> dict:
    """
    Sample video at 1 fps and score facial reactions per second.
    Returns {second_int: reaction_score in [0,1]}.
    """
    if not MEDIAPIPE_AVAILABLE:
        return {}

    model = _ensure_model()
    if model is None:
        log.warning("Face landmarker model unavailable — skipping face analysis.")
        return {}

    log.info(f"Analyzing face reactions: {vod_path.name}")

    cap = cv2.VideoCapture(str(vod_path))
    if not cap.isOpened():
        log.error(f"Could not open video: {vod_path}")
        return {}

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    total_secs = int(total_frames / fps) if fps else 0
    log.info(f"Video: {total_secs}s at {fps:.1f}fps — sampling 1 frame/sec")

    options = FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(model)),
        running_mode=RunningMode.VIDEO,
        num_faces=1,
        output_face_blendshapes=True,
        output_facial_transformation_matrixes=False,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    face_scores: dict[int, float] = {}
    landmarker = FaceLandmarker.create_from_options(options)
    try:
        for second in range(total_secs):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(second * fps))
            ok, frame = cap.read()
            if not ok or frame is None:
                face_scores[second] = 0.0
                continue

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = landmarker.detect_for_video(mp_image, second * 1000)

            if not result.face_blendshapes:
                face_scores[second] = 0.0
                continue

            face_scores[second] = round(
                _score_from_blendshapes(result.face_blendshapes[0]), 4
            )

            if second and second % 300 == 0:
                pct = (second / total_secs * 100) if total_secs else 0
                log.info(f"  Face: {second}s / {total_secs}s ({pct:.0f}%)")
    finally:
        landmarker.close()
        cap.release()

    log.info(f"Face analysis complete — {len(face_scores)} seconds scored.")
    return face_scores


# =============================================================================
# PUBLIC INTERFACE
# =============================================================================

def get_face_scores(vod_path: Path, force_rerun: bool = False) -> dict:
    """Time-indexed face reaction scores, cached after first run."""
    if not MEDIAPIPE_AVAILABLE:
        return {}

    log.info("=" * 60)
    log.info("FACE DETECTOR")
    log.info(f"VOD: {vod_path.name}")
    log.info("=" * 60)

    if not force_rerun and face_cache_exists(vod_path):
        return load_face_cache(vod_path)

    scores = analyze_face_reactions(vod_path)
    if scores:
        save_face_cache(scores, vod_path)
    return scores


# Alias used by clip_engine — keep names aligned.
build_face_index = get_face_scores


def get_face_score_at(timestamp: float, face_scores: dict) -> float:
    """Average face score in a 3-second window for stability."""
    if not face_scores:
        return 0.0
    sec = int(timestamp)
    window = [
        face_scores.get(sec - 1, 0.0),
        face_scores.get(sec, 0.0),
        face_scores.get(sec + 1, 0.0),
    ]
    valid = [v for v in window if v > 0]
    return float(sum(valid) / len(valid)) if valid else 0.0
