"""
Extract training data from clip reviews and retrain the quality classifier.
Uses explicit verdict/tags as ground truth; ratings are not binary labels.
"""

import json
import logging
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from config import paths
from modules.clip_reviews import classify_review_signal, list_reviews
from modules.quality_classifier.embeddings import embed, ollama_alive
from modules.stream_context import detect_segment_type, get_segment_context

log = logging.getLogger("review_trainer")


def extract_training_data_from_reviews(
    min_rating: float = 0.5,
) -> tuple[np.ndarray, np.ndarray, list[dict], list[str]]:
    """
    Extract training examples from reviews.
    Keepers/positive tags are good. Genuine misses are bad. Reviews about bad
    boundaries or misunderstood context are excluded from semantic training.

    Returns:
        X: embeddings array (n_samples, embedding_dim)
        y: labels array (0 or 1)
        metadata: list of dicts with clip info
        texts: original transcripts/hints
    """
    if not ollama_alive():
        raise RuntimeError(
            "Ollama is not reachable at http://localhost:11434 — "
            "start Ollama before training."
        )

    reviews = list_reviews(limit=10000)
    log.info(f"Found {len(reviews)} reviews")

    X_list = []
    y_list = []
    metadata_list = []
    texts_list = []

    for review in reviews:
        signal = classify_review_signal(review)
        if signal == "positive":
            label = 1
        elif signal == "negative":
            label = 0
        else:
            continue

        rating = review.get("rating")
        if isinstance(rating, (int, float)):
            rating_float = float(rating)
            if rating_float > 1:
                rating_float = rating_float / 5.0
        else:
            rating_float = None

        stem = review.get("stem", "unknown")
        reasons = review.get("reasons", [])
        notes = review.get("notes", "")

        # Load transcript if available
        transcript_file = paths.CLIP_TRANSCRIPTS_DIR / f"{stem}.txt"
        transcript = ""
        if transcript_file.exists():
            transcript = transcript_file.read_text(encoding="utf-8").strip()

        # Training and inference must use the same feature domain. Review notes
        # define labels but are never present when scoring a new transcript.
        if not transcript:
            continue

        vec = embed(transcript)
        if vec is None:
            log.warning(f"Could not embed {stem}")
            continue

        X_list.append(vec)
        y_list.append(label)
        metadata_list.append(
            {
                "stem": stem,
                "rating": rating_float,
                "reasons": reasons,
                "notes": notes,
                "learning_signal": signal,
            }
        )
        texts_list.append(transcript)

    if not X_list:
        raise ValueError("No usable training data extracted from reviews")

    X = np.array(X_list)
    y = np.array(y_list)

    log.info(
        f"Extracted {len(X)} training examples: "
        f"{np.sum(y)} good, {len(X) - np.sum(y)} bad"
    )
    return X, y, metadata_list, texts_list


def train_quality_classifier(
    X: np.ndarray,
    y: np.ndarray,
    test_size: float = 0.2,
    model_path: Path | None = None,
) -> dict:
    """
    Train quality classifier on review data.

    Returns dict with metrics and model path.
    """
    if model_path is None:
        model_path = paths.PROFILES_DIR / "quality_classifier_review_trained.joblib"

    if len(np.unique(y)) < 2:
        raise ValueError("Need both positive and genuine-negative reviews to train")

    import joblib
    from sklearn.model_selection import train_test_split

    # Split data
    if len(X) > 10:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42, stratify=y
        )
    else:
        X_train, X_test, y_train, y_test = X, X, y, y

    # Build and train pipeline
    pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("classifier", LogisticRegression(max_iter=1000, random_state=42)),
        ]
    )

    pipeline.fit(X_train, y_train)

    # Evaluate
    y_pred_train = pipeline.predict(X_train)
    y_pred_test = pipeline.predict(X_test)

    train_acc = accuracy_score(y_train, y_pred_train)
    test_acc = accuracy_score(y_test, y_pred_test)

    results = {
        "train_accuracy": float(train_acc),
        "test_accuracy": float(test_acc),
        "n_train": len(X_train),
        "n_test": len(X_test),
        "n_good_train": int(np.sum(y_train)),
        "n_good_test": int(np.sum(y_test)),
    }

    if len(np.unique(y_test)) > 1:
        from sklearn.metrics import roc_auc_score

        y_proba = pipeline.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, y_proba)
        results["auc"] = float(auc)

        log.info("\n" + classification_report(y_test, y_pred_test))

    # Save model
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, model_path)

    log.info(
        f"\nQuality classifier trained:\n"
        f"  Train accuracy: {train_acc:.3f}\n"
        f"  Test accuracy: {test_acc:.3f}\n"
        f"  Model saved to: {model_path.name}"
    )

    return results


def retrain_from_reviews(force: bool = False) -> dict:
    """
    Main entry point: extract reviews and retrain classifier.
    """
    model_path = paths.PROFILES_DIR / "quality_classifier_review_trained.joblib"

    if model_path.exists() and not force:
        log.info(f"Review-trained model already exists at {model_path.name}")
        return {"skipped": True, "model_path": str(model_path)}

    try:
        X, y, metadata, texts = extract_training_data_from_reviews()
        results = train_quality_classifier(X, y, model_path=model_path)
        results["model_path"] = str(model_path)
        return results
    except Exception as e:
        log.error(f"Failed to retrain from reviews: {e}", exc_info=True)
        raise


def evaluate_review_patterns() -> dict:
    """
    Analyze review patterns to find high-value clip characteristics.
    Returns suggestions for improving clips.
    """
    reviews = list_reviews()

    high_rated = [r for r in reviews if classify_review_signal(r) == "positive"]
    low_rated = [r for r in reviews if classify_review_signal(r) == "negative"]
    boundary_failures = [
        r for r in reviews if classify_review_signal(r) in {"boundary", "context"}
    ]

    def analyze_reasons(review_list, label):
        reasons_count = {}
        for review in review_list:
            for reason in review.get("reasons", []):
                reasons_count[reason] = reasons_count.get(reason, 0) + 1
        return dict(sorted(reasons_count.items(), key=lambda x: -x[1]))

    high_reasons = analyze_reasons(high_rated, "high")
    low_reasons = analyze_reasons(low_rated, "low")

    return {
        "high_rated_clips": len(high_rated),
        "low_rated_clips": len(low_rated),
        "boundary_or_context_failures": len(boundary_failures),
        "top_positive_reasons": high_reasons,
        "top_negative_reasons": low_reasons,
        "recommendation": (
            "Focus on: " + ", ".join(list(high_reasons.keys())[:3])
            if high_reasons
            else "Collect more reviews"
        ),
    }
