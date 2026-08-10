# =============================================================================
# modules/speaker_id/speaker_id.py
# =============================================================================
# Identifies which transcript segments are "lazi" vs anyone else, using a
# voice-print embedding from Resemblyzer.
#
# Flow:
#   1. enroll_speaker(name, wav_or_clip) -> stores a 256-d embedding to
#      data/speakers/{name}.npy
#   2. identify_segments(audio_path, segments) -> tags each segment with
#      speaker label ("lazi" / "other" / "unknown") and similarity score
#
# Used by:
#   - modules.listener.listener (to annotate segments)
#   - modules.clip_engine.clip_engine (to boost lazi segments)
#   - modules.quality_classifier.trainer (passes speaker tag into the embedding)
# =============================================================================

import json
import logging
import sys
import types
from pathlib import Path
from typing import Optional

import numpy as np

from config import paths


# -----------------------------------------------------------------------------
# Resemblyzer imports webrtcvad at module load time. We don't use webrtcvad
# (our segments come from Whisper's VAD), and webrtcvad has no wheels on
# Windows — so we inject a minimal stub before resemblyzer is loaded.
# -----------------------------------------------------------------------------
if "webrtcvad" not in sys.modules:
    _stub = types.ModuleType("webrtcvad")

    class _StubVad:
        def __init__(self, *a, **kw): pass
        def set_mode(self, mode): pass
        def is_speech(self, *a, **kw): return True

    _stub.Vad = _StubVad
    sys.modules["webrtcvad"] = _stub

log = logging.getLogger("speaker_id")

SPEAKERS_DIR = paths.DATA_DIR / "speakers"
DEFAULT_THRESHOLD = 0.65  # cosine similarity above this -> match


# =============================================================================
# Lazy-load encoder (it warms up the torch graph; do it once)
# =============================================================================

_encoder = None


def _get_encoder():
    global _encoder
    if _encoder is not None:
        return _encoder
    try:
        from resemblyzer import VoiceEncoder
    except ImportError:
        log.warning("resemblyzer not installed — speaker ID disabled.")
        return None
    log.info("Loading Resemblyzer VoiceEncoder...")
    _encoder = VoiceEncoder()
    log.info("VoiceEncoder ready.")
    return _encoder


def resemblyzer_available() -> bool:
    try:
        import resemblyzer  # noqa: F401
        return True
    except ImportError:
        return False


# =============================================================================
# Enrollment
# =============================================================================

def _load_wav(audio_path: Path):
    """Return a 16kHz mono float32 array suitable for resemblyzer."""
    from resemblyzer import preprocess_wav
    return preprocess_wav(str(audio_path))


def embed_audio(audio_path: Path) -> Optional[np.ndarray]:
    enc = _get_encoder()
    if enc is None:
        return None
    try:
        wav = _load_wav(audio_path)
        return enc.embed_utterance(wav)
    except Exception as e:
        log.warning(f"embed failed for {audio_path.name}: {e}")
        return None


def enroll_speaker(name: str, audio_paths: list[Path]) -> dict:
    """
    Compute an average voice embedding across one or more audio samples and
    save it to data/speakers/{name}.npy.
    """
    if not resemblyzer_available():
        raise RuntimeError("resemblyzer not installed.")

    SPEAKERS_DIR.mkdir(parents=True, exist_ok=True)
    embeds = []
    used = []
    for p in audio_paths:
        emb = embed_audio(p)
        if emb is None:
            log.warning(f"  skipping {p.name} — could not embed")
            continue
        embeds.append(emb)
        used.append(p.name)

    if not embeds:
        raise RuntimeError("No usable audio samples for enrollment.")

    avg = np.mean(np.stack(embeds), axis=0)
    # Re-normalize (mean of unit vectors isn't unit length).
    norm = np.linalg.norm(avg)
    if norm > 0:
        avg = avg / norm

    out_path = SPEAKERS_DIR / f"{name}.npy"
    np.save(out_path, avg.astype(np.float32))

    meta_path = SPEAKERS_DIR / f"{name}.json"
    meta_path.write_text(json.dumps({
        "name": name,
        "samples": used,
        "n_samples": len(used),
        "dim": int(avg.shape[0]),
    }, indent=2), encoding="utf-8")

    log.info(f"Enrolled '{name}' from {len(used)} samples — saved {out_path}")
    return {"name": name, "samples": len(used), "path": str(out_path)}


def _find_clip_file(stem: str, bucket: str = "") -> Optional[Path]:
    """Best-effort resolve a reviewed clip's stem to a file on disk."""
    if not stem:
        return None
    bucket_dirs = {
        "clips": paths.CLIPS_DIR,
        "output": paths.CLIPS_DIR,
        "notclips": paths.NOTCLIPS_DIR,
        "edited": paths.OUTPUT_DIR / "edited",
        "positives": paths.OUTPUT_DIR / "positives",
    }
    search = []
    if bucket in bucket_dirs:
        search.append(bucket_dirs[bucket])
    # Fall back to the common output buckets if the recorded bucket is missing/wrong.
    search += [paths.CLIPS_DIR, paths.OUTPUT_DIR / "edited", paths.OUTPUT_DIR / "positives"]
    for d in search:
        candidate = d / f"{stem}.mp4"
        if candidate.is_file():
            return candidate
    return None


def gather_keeper_clip_paths(max_clips: int = 25) -> list[Path]:
    """The creator's KEEPER clips that exist on disk — labelled examples of their
    own voice in real stream conditions (their voice is the one common to all)."""
    from modules.clip_reviews import classify_review_signal, list_reviews

    found: list[Path] = []
    for r in list_reviews(limit=5000):
        if classify_review_signal(r) != "positive":
            continue
        f = _find_clip_file(str(r.get("stem") or ""), str(r.get("bucket") or ""))
        if f is not None and f not in found:
            found.append(f)
        if len(found) >= max_clips:
            break
    return found


def enroll_from_keepers(name: str = "lazi", *, max_clips: int = 25,
                        clip_paths: Optional[list[Path]] = None,
                        embedder=None) -> dict:
    """Build a robust voice print by averaging embeddings across many of the
    creator's own keeper clips, instead of one clean mic sample. The creator is
    the single voice common to all their clips, so the averaged centroid emphasises
    their voice AND stays in-domain (same codec/noise/energy as real clips), which
    generalises far better across tone and stream conditions. Backs up any existing
    print. `embedder`/`clip_paths` are injectable for testing."""
    embed = embedder or embed_audio
    sources = clip_paths if clip_paths is not None else gather_keeper_clip_paths(max_clips)
    if not sources:
        raise RuntimeError("no keeper clips found on disk to enroll from")

    embeds, used = [], []
    for p in sources:
        e = embed(Path(p))
        if e is None:
            continue
        embeds.append(np.asarray(e, dtype=np.float32))
        used.append(Path(p).name)
    if not embeds:
        raise RuntimeError("could not embed any keeper clips (missing audio deps or unreadable files)")

    # Keeper clips CONTAIN GUESTS — a clip dominated by someone else's voice
    # poisons the average ("still doesn't differentiate me", 2026-07-06). Refine:
    # drop the embeddings least similar to the centroid (guest-heavy clips), then
    # re-average the consistent core — the streamer is the voice common to most.
    stack = np.stack(embeds)
    if len(embeds) >= 4:
        centroid = np.mean(stack, axis=0)
        centroid /= (np.linalg.norm(centroid) or 1.0)
        sims = stack @ centroid / np.maximum(np.linalg.norm(stack, axis=1), 1e-9)
        keep_n = max(3, int(round(len(embeds) * 0.7)))
        keep_idx = np.argsort(sims)[-keep_n:]
        dropped = [used[i] for i in range(len(used)) if i not in set(keep_idx.tolist())]
        if dropped:
            log.info("voice refine: dropped %d guest-heavy clip(s): %s",
                     len(dropped), ", ".join(dropped[:5]))
        stack = stack[keep_idx]
        used = [used[i] for i in keep_idx.tolist()]

    avg = np.mean(stack, axis=0)
    norm = np.linalg.norm(avg)
    if norm > 0:
        avg = avg / norm

    SPEAKERS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SPEAKERS_DIR / f"{name}.npy"
    if out_path.exists():
        import shutil
        shutil.copyfile(out_path, SPEAKERS_DIR / f"{name}.npy.bak")  # keep the old print
    np.save(out_path, avg.astype(np.float32))

    meta_path = SPEAKERS_DIR / f"{name}.json"
    meta_path.write_text(json.dumps({
        "name": name, "samples": used, "n_samples": len(used),
        "dim": int(avg.shape[0]), "source": "keeper_clips",
    }, indent=2), encoding="utf-8")

    log.info("Enrolled '%s' from %d keeper clips — saved %s", name, len(used), out_path)
    return {"name": name, "samples": len(used), "path": str(out_path), "source": "keeper_clips"}


def load_speaker(name: str) -> Optional[np.ndarray]:
    p = SPEAKERS_DIR / f"{name}.npy"
    if not p.exists():
        return None
    return np.load(p)


def list_speakers() -> list[str]:
    if not SPEAKERS_DIR.exists():
        return []
    return sorted(p.stem for p in SPEAKERS_DIR.glob("*.npy"))


# =============================================================================
# Identification at inference time
# =============================================================================

def _embed_window(audio_path: Path, start: float, duration: float):
    """
    Load just the [start, start+duration] slice of the audio file as a
    16kHz mono float32 array via librosa.
    """
    try:
        import librosa
        from resemblyzer import preprocess_wav
    except ImportError as e:
        log.warning(f"deps unavailable: {e}")
        return None

    try:
        wav, _ = librosa.load(str(audio_path),
                              sr=16000, mono=True,
                              offset=max(0.0, start),
                              duration=max(0.2, duration))
        if wav.size < 16000 * 0.4:   # less than ~0.4s — too short for a reliable embed
            return None
        return preprocess_wav(wav, source_sr=16000)
    except Exception as e:
        log.warning(f"audio slice failed at {start:.2f}+{duration:.2f}s: {e}")
        return None


def identify_segments(audio_path: Path, segments: list[dict],
                      target_speaker: str = "lazi",
                      threshold: float = DEFAULT_THRESHOLD) -> list[dict]:
    """
    Annotate each segment with a 'speaker' label and 'speaker_sim' score.

    Returns the same list with added fields. If the encoder or target
    fingerprint isn't available, segments get speaker='unknown' and we
    bail gracefully.
    """
    enc = _get_encoder()
    target_emb = load_speaker(target_speaker)
    if enc is None or target_emb is None:
        for s in segments:
            s.setdefault("speaker", "unknown")
            s.setdefault("speaker_sim", 0.0)
        return segments

    log.info(f"Tagging {len(segments)} segments against speaker '{target_speaker}' "
             f"(threshold={threshold})...")

    tagged = 0
    for i, seg in enumerate(segments):
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start + 1.0))
        duration = max(0.4, min(10.0, end - start))  # cap embed window at 10s

        wav = _embed_window(audio_path, start, duration)
        if wav is None:
            seg["speaker"] = "unknown"
            seg["speaker_sim"] = 0.0
            continue

        emb = enc.embed_utterance(wav)
        sim = float(np.dot(emb, target_emb))
        seg["speaker_sim"] = round(sim, 4)
        seg["speaker"] = target_speaker if sim >= threshold else "other"
        if seg["speaker"] == target_speaker:
            tagged += 1

        if (i + 1) % 200 == 0:
            log.info(f"  speaker-id: {i+1}/{len(segments)} segments")

    log.info(f"Speaker-id complete — {tagged}/{len(segments)} segments tagged as '{target_speaker}'")
    return segments


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m modules.speaker_id.speaker_id enroll <name> <sample1.wav> [sample2 ...]")
        print("  python -m modules.speaker_id.speaker_id list")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "enroll":
        if len(sys.argv) < 4:
            print("Need a name and at least one sample.")
            sys.exit(1)
        name = sys.argv[2]
        samples = [Path(p) for p in sys.argv[3:]]
        print(json.dumps(enroll_speaker(name, samples), indent=2))
    elif cmd == "list":
        for n in list_speakers():
            print(n)
