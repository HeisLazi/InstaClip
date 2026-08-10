import logging
from pathlib import Path

import joblib
import numpy as np

from config import paths
from modules.quality_classifier.embeddings import embed

try:
    from modules.streamer_lexicon import normalize_idioms
except (ImportError, Exception):
    def normalize_idioms(text): return text

log = logging.getLogger("quality_classifier.predictor")

MODEL_PATH = paths.PROFILES_DIR / "quality_classifier.joblib"
REVIEW_TRAINED_PATH = paths.PROFILES_DIR / "quality_classifier_review_trained.joblib"

_model_cache = {"clf": None, "loaded": False}


def _active_model_path():
    """Prefer the review-trained model when available, fall back to the base one."""
    if REVIEW_TRAINED_PATH.exists():
        return REVIEW_TRAINED_PATH
    return MODEL_PATH


def model_available() -> bool:
    return REVIEW_TRAINED_PATH.exists() or MODEL_PATH.exists()


def _load():
    if _model_cache["loaded"]:
        return _model_cache["clf"]
    _model_cache["loaded"] = True
    path = _active_model_path()
    if not path.exists():
        log.info(f"Quality classifier not trained yet (no {MODEL_PATH.name}).")
        _model_cache["clf"] = None
        return None
    try:
        _model_cache["clf"] = joblib.load(path)
        log.info(f"Quality classifier loaded: {path.name}")
    except Exception as e:
        log.warning(f"Could not load quality classifier from {path.name}: {e}")
        _model_cache["clf"] = None
    return _model_cache["clf"]


def predict_quality(text: str, visual_caption: str | None = None) -> float | None:
    """
    Returns P(clip is good) in [0,1], or None if classifier unavailable.

    visual_caption is the schema-ready hook for the future on-screen
    annotation feature — currently appended to text if provided.
    """
    clf = _load()
    if clf is None:
        return None

    normalized = normalize_idioms(text) if text else text
    combined = normalized if not visual_caption else f"{normalized} || visual: {visual_caption}"
    vec = embed(combined)
    if vec is None:
        return None

    proba = clf.predict_proba(vec.reshape(1, -1))[0]
    # Class 1 is "good" by trainer convention.
    return float(proba[1])


def predict_batch(texts: list[str]) -> list[float | None]:
    return [predict_quality(t) for t in texts]
