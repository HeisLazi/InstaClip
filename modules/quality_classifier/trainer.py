import json
import logging
import re
import subprocess
import tempfile
import time
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

from config import paths
from modules.quality_classifier.embeddings import embed, ollama_alive
from modules.quality_classifier.predictor import MODEL_PATH

try:
    from modules.streamer_lexicon import normalize_idioms
except (ImportError, Exception):
    def normalize_idioms(text): return text

log = logging.getLogger("quality_classifier.trainer")

GEN_PREFIX = re.compile(r"^GEN_\d+\.\d+_(.+)$")


def _clip_dirs():
    return {
        1: paths.OLD_CLIPS_DIR,
        0: paths.OUTPUT_DIR / "notclips",
    }


def _list_clips(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    exts = {".mp4", ".mkv", ".mov", ".avi", ".flv", ".webm"}
    return sorted(p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in exts)


def _transcript_cache_path(clip_path: Path) -> Path:
    return paths.CLIP_TRANSCRIPTS_DIR / f"{clip_path.stem}.txt"


def _filename_text_hint(clip_path: Path) -> str:
    """Pull a coarse text hint from GEN_<score>_<phrase>.mp4 filenames."""
    m = GEN_PREFIX.match(clip_path.stem)
    if m:
        return m.group(1).replace("_", " ")
    return clip_path.stem.replace("_", " ")


def _transcribe_clip(clip_path: Path, whisper_model) -> str:
    """
    Transcribe a single short clip to plain text.
    Uses a temp WAV so we don't pollute data/audio/.
    """
    cache = _transcript_cache_path(clip_path)
    if cache.exists():
        return cache.read_text(encoding="utf-8").strip()

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / (clip_path.stem + ".wav")
        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip_path),
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            str(wav),
        ]
        try:
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=True,
                timeout=180,
            )
        except subprocess.CalledProcessError as e:
            log.warning(f"ffmpeg failed on {clip_path.name}: {e.stderr.decode()[-200:]}")
            return _filename_text_hint(clip_path)
        except subprocess.TimeoutExpired:
            log.warning(f"ffmpeg timeout on {clip_path.name}")
            return _filename_text_hint(clip_path)

        try:
            segments, _info = whisper_model.transcribe(
                str(wav),
                beam_size=1,
                vad_filter=True,
                chunk_length=30,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
        except Exception as e:
            log.warning(f"Whisper failed on {clip_path.name}: {e}")
            text = ""

    if not text:
        # Fallback to filename hint so the example isn't lost.
        text = _filename_text_hint(clip_path)

    cache.write_text(text, encoding="utf-8")
    return text


def build_dataset(force_retranscribe: bool = False,
                  use_vision: bool = False,
                  vision_model: str = "llava:7b"
                  ) -> tuple[list[np.ndarray], list[int], list[dict], list[float]]:
    """
    Walks positive (old_clips) and negative (notclips) directories,
    transcribes & embeds each. Returns (X_vecs, y_labels, metadata).

    If use_vision is True, each clip is also captioned by an Ollama vision
    model and the captions are concatenated with the transcript before
    embedding — same enrichment the predictor uses at inference time.
    """
    from utils.whisper_utils import load_whisper_model

    if not ollama_alive():
        raise RuntimeError(
            "Ollama is not reachable at http://localhost:11434 — "
            "start Ollama before training the quality classifier."
        )

    if use_vision:
        from modules.vision_describer.vision_describer import vision_alive
        ok, msg = vision_alive(vision_model)
        if not ok:
            log.warning(f"Vision unavailable ({msg}) — training without visual captions.")
            use_vision = False

    paths.CLIP_TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    from modules.clip_reviews import classify_review_signal, get_review

    # publisher.py is excluded from the public edition; training falls back to
    # local clip folders only. Provide no-op stubs so existing loops keep working.
    posted_stems = lambda: set()
    posted_clip_paths = lambda: []

    def _apply_review(
        stem: str, base_label: int, base_weight: float
    ) -> tuple[int | None, float, dict | None]:
        """
        Fold a human review into the (label, weight) for this clip.
        Verdict/tags beat folder placement; rating only modulates confidence.
        Boundary/context failures are excluded because they describe a bad cut,
        not whether the underlying moment is semantically clip-worthy. Null
        reviews are also excluded because they contain no taste explanation.
        Returns (label, weight, review_dict_or_None).
        """
        review = get_review(stem)
        if not review:
            return base_label, base_weight, None
        label = base_label
        weight = base_weight
        signal = classify_review_signal(review)
        if signal in {"boundary", "context", "null"}:
            return None, weight, review
        if signal == "positive":
            label = 1
            weight = max(weight, 3.0)
        elif signal == "negative":
            label = 0
            weight = max(weight, 2.0)
        # rating is 1-5
        rating = review.get("rating")
        if isinstance(rating, (int, float)):
            r = int(rating)
            if r >= 5:
                weight *= 1.5
            elif r >= 4:
                weight *= 1.2
            elif r <= 2 and signal == "negative":
                weight *= 1.2
        return label, weight, review

    posted = posted_stems()
    dirs = _clip_dirs()
    all_clips = []
    seen_stems: set[str] = set()
    review_overrides = 0
    for base_label, directory in dirs.items():
        clips = _list_clips(directory)
        log.info(f"  {directory.name}: {len(clips)} clips (label={base_label})")
        for c in clips:
            seen_stems.add(c.stem)
            effective_label = 1 if c.stem in posted else base_label
            weight = 5.0 if c.stem in posted else 1.0
            effective_label, weight, review = _apply_review(c.stem, effective_label, weight)
            if effective_label is None:
                log.info("  excluding %s: review is a trim/context failure", c.name)
                continue
            if review and (review.get("verdict") in ("keeper", "miss") or review.get("rating")):
                review_overrides += 1
            all_clips.append((c, effective_label, weight, review))

    posted_extra = 0
    for c in posted_clip_paths():
        if c.stem in seen_stems:
            continue
        label, weight, review = _apply_review(c.stem, 1, 5.0)
        if label is None:
            continue
        all_clips.append((c, label, weight, review))
        seen_stems.add(c.stem)
        posted_extra += 1
    if posted:
        log.info(f"Posted clips are weighted as premium positives (5x); extra posted-only clips={posted_extra}")
    if review_overrides:
        log.info(f"Human reviews applied to {review_overrides} clips (label/weight adjusted)")

    if not all_clips:
        raise RuntimeError("No clips found to train on.")

    pos_count = sum(1 for _, y, _w, _r in all_clips if y == 1)
    neg_count = sum(1 for _, y, _w, _r in all_clips if y == 0)
    log.info(f"Dataset: {pos_count} positives, {neg_count} negatives")

    if pos_count < 5 or neg_count < 5:
        raise RuntimeError(
            f"Not enough labeled clips (pos={pos_count}, neg={neg_count}). "
            "Need at least 5 of each to train a classifier."
        )

    log.info("Loading Whisper for clip transcription...")
    whisper_model = load_whisper_model()

    X, y, meta, weights = [], [], [], []
    started = time.time()

    for i, (clip_path, label, weight, review) in enumerate(all_clips, start=1):
        if force_retranscribe:
            cache = _transcript_cache_path(clip_path)
            if cache.exists():
                cache.unlink()

        text = _transcribe_clip(clip_path, whisper_model)
        if not text:
            log.warning(f"  [{i}/{len(all_clips)}] skipping {clip_path.name}: empty transcript")
            continue

        visual_caption = ""
        if use_vision:
            from modules.vision_describer.vision_describer import get_or_caption_clip
            try:
                visual_caption = get_or_caption_clip(
                    clip_path, model=vision_model, n_frames=3,
                    force=force_retranscribe,
                ) or ""
            except Exception as e:
                log.warning(f"  vision failed for {clip_path.name}: {e}")

        # Normalize multi-word idioms ("is not make sure", "no cap", etc.)
        # into stable semantic tokens before embedding, so Whisper transcript
        # variants collapse to a single feature for the classifier.
        normalized = normalize_idioms(text)
        combined = normalized
        if visual_caption:
            combined += f" || visual: {visual_caption}"

        vec = embed(combined)
        if vec is None:
            log.warning(f"  [{i}/{len(all_clips)}] skipping {clip_path.name}: embed failed")
            continue

        X.append(vec)
        y.append(label)
        weights.append(weight)
        meta.append({
            "clip": clip_path.name,
            "label": label,
            "sample_weight": weight,
            "posted": clip_path.stem in posted,
            "reviewed": review is not None,
            "review_verdict": (review or {}).get("verdict"),
            "review_rating": (review or {}).get("rating"),
            "text": text[:240],
            "visual": visual_caption[:240],
        })

        if i % 10 == 0:
            elapsed = time.time() - started
            log.info(f"  [{i}/{len(all_clips)}] processed ({elapsed:.0f}s elapsed)")

    log.info(f"Built dataset: {len(X)} examples in {time.time() - started:.0f}s")
    return X, y, meta, weights


def train(force_retranscribe: bool = False,
          use_vision: bool = False,
          vision_model: str = "llava:7b") -> dict:
    log.info("=" * 60)
    log.info("QUALITY CLASSIFIER — TRAINING")
    log.info(f"  use_vision={use_vision} model={vision_model if use_vision else '-'}")
    log.info("=" * 60)

    X_list, y_list, meta, weights = build_dataset(
        force_retranscribe=force_retranscribe,
        use_vision=use_vision,
        vision_model=vision_model,
    )
    X = np.vstack(X_list)
    y = np.asarray(y_list, dtype=np.int64)
    sample_weight = np.asarray(weights, dtype=np.float64)

    pos = int((y == 1).sum())
    neg = int((y == 0).sum())
    log.info(f"Final training set: {len(y)} examples (pos={pos}, neg={neg})")

    clf = Pipeline([
        ("scale", StandardScaler(with_mean=True, with_std=True)),
        ("lr", LogisticRegression(
            C=1.0,
            class_weight="balanced",
            max_iter=2000,
            solver="lbfgs",
        )),
    ])

    # Cross-val for honest metrics; final model fits on all data.
    cv_folds = 5 if min(pos, neg) >= 5 else max(2, min(pos, neg))
    try:
        cv_acc = cross_val_score(clf, X, y, cv=cv_folds, scoring="accuracy")
        cv_auc = cross_val_score(clf, X, y, cv=cv_folds, scoring="roc_auc")
        cv_acc_mean = float(cv_acc.mean())
        cv_auc_mean = float(cv_auc.mean())
        log.info(f"CV accuracy ({cv_folds}-fold): {cv_acc_mean:.3f} ± {cv_acc.std():.3f}")
        log.info(f"CV ROC-AUC  ({cv_folds}-fold): {cv_auc_mean:.3f} ± {cv_auc.std():.3f}")
    except Exception as e:
        log.warning(f"CV scoring failed: {e}")
        cv_acc_mean = None
        cv_auc_mean = None

    clf.fit(X, y, lr__sample_weight=sample_weight)
    train_acc = float(accuracy_score(y, clf.predict(X)))
    train_auc = float(roc_auc_score(y, clf.predict_proba(X)[:, 1]))
    log.info(f"Train accuracy: {train_acc:.3f}")
    log.info(f"Train ROC-AUC:  {train_auc:.3f}")

    paths.PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(clf, MODEL_PATH)
    metadata_path = paths.PROFILES_DIR / "quality_classifier_meta.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump({
            "examples": int(len(y)),
            "weighted_examples": float(sample_weight.sum()),
            "positives": pos,
            "negatives": neg,
            "posted_positives": int(sum(1 for m in meta if m.get("posted"))),
            "reviewed_examples": int(sum(1 for m in meta if m.get("reviewed"))),
            "review_keepers": int(sum(1 for m in meta if m.get("review_verdict") == "keeper")),
            "review_misses":  int(sum(1 for m in meta if m.get("review_verdict") == "miss")),
            "train_accuracy": train_acc,
            "train_auc": train_auc,
            "cv_accuracy": cv_acc_mean,
            "cv_auc": cv_auc_mean,
            "embed_model": "nomic-embed-text",
            "embed_dim": int(X.shape[1]),
            "use_vision": use_vision,
            "vision_model": vision_model if use_vision else None,
            "examples_meta": meta[:50],  # truncated preview
        }, f, indent=2)

    log.info(f"Classifier saved: {MODEL_PATH}")
    log.info(f"Metadata saved:   {metadata_path}")
    log.info("=" * 60)

    return {
        "examples": int(len(y)),
        "positives": pos,
        "negatives": neg,
        "train_accuracy": train_acc,
        "train_auc": train_auc,
        "cv_accuracy": cv_acc_mean,
        "cv_auc": cv_auc_mean,
    }


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    result = train(force_retranscribe=force)
    print(json.dumps(result, indent=2))
