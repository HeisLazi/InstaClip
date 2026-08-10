# =============================================================================
# modules/vision_describer/vision_describer.py
# =============================================================================
# Captions video frames using a local Ollama vision model (llava:7b by default).
# Used for:
#   1. Captioning training clips so the quality classifier learns visual context
#   2. Captioning highlight windows at inference time so the classifier scores
#      them with the same enriched input it was trained on
# =============================================================================

import base64
import io
import json
import logging
import urllib.error
import urllib.request
from pathlib import Path

from config import paths

log = logging.getLogger("vision_describer")

OLLAMA_GENERATE = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "llava:7b"
PROMPT = (
    "Describe what is happening in this video frame in one short sentence. "
    "Focus on the action and the person's facial expression. Be specific."
)
REQUEST_TIMEOUT = 120


# =============================================================================
# Frame sampling
# =============================================================================

def _sample_frame(video_path: Path, timestamp_seconds: float) -> bytes | None:
    """Grab one frame from `video_path` at the given timestamp as JPEG bytes."""
    try:
        import cv2
        from PIL import Image
    except ImportError as e:
        log.warning(f"cv2/PIL unavailable: {e}")
        return None

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        target_frame = max(0, min(total_frames - 1, int(timestamp_seconds * fps)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ok, frame = cap.read()
        if not ok or frame is None:
            return None
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        # Vision models don't need 4K — downscale to keep payload small + faster.
        max_dim = 640
        if max(img.size) > max_dim:
            ratio = max_dim / max(img.size)
            img = img.resize((int(img.size[0] * ratio), int(img.size[1] * ratio)),
                             Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return buf.getvalue()
    finally:
        cap.release()


# =============================================================================
# Ollama call
# =============================================================================

def _caption_image(image_bytes: bytes, model: str = DEFAULT_MODEL) -> str | None:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    payload = json.dumps({
        "model": model,
        "prompt": PROMPT,
        "stream": False,
        "images": [b64],
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_GENERATE,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            body = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        log.warning(f"Ollama vision call failed: {e}")
        return None

    text = (body.get("response") or "").strip()
    if not text:
        return None
    # llava sometimes prefixes "The image shows..." — keep the rest of the sentence.
    return text.replace("\n", " ").strip()


def vision_alive(model: str = DEFAULT_MODEL) -> tuple[bool, str]:
    """Quick health probe — used by the GUI."""
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            tags = json.loads(r.read())
    except Exception as e:
        return False, f"Ollama unreachable ({e})"
    models = {m["name"] for m in tags.get("models", [])}
    if model in models or any(m.startswith(model.split(":")[0] + ":") for m in models):
        return True, "OK"
    return False, f"Model '{model}' not pulled — run: ollama pull {model}"


# =============================================================================
# Public APIs
# =============================================================================

def describe_clip(clip_path: Path, model: str = DEFAULT_MODEL,
                  n_frames: int = 3) -> dict:
    """
    Caption a short clip by sampling N frames evenly across it.
    Returns {"captions": [str, ...], "combined": "..."}.
    """
    try:
        import cv2
    except ImportError:
        return {"captions": [], "combined": ""}

    cap = cv2.VideoCapture(str(clip_path))
    if not cap.isOpened():
        return {"captions": [], "combined": ""}
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps else 0
    cap.release()
    if duration <= 0:
        return {"captions": [], "combined": ""}

    # Sample at 25%/50%/75% of the clip by default; skip the very edges.
    timestamps = [duration * (i + 1) / (n_frames + 1) for i in range(n_frames)]

    captions = []
    for t in timestamps:
        frame_bytes = _sample_frame(clip_path, t)
        if not frame_bytes:
            continue
        caption = _caption_image(frame_bytes, model=model)
        if caption:
            captions.append(caption)

    return {
        "captions": captions,
        "combined": " ".join(captions),
    }


def describe_highlight(vod_path: Path, start: float, end: float,
                       model: str = DEFAULT_MODEL,
                       n_frames: int = 3) -> dict:
    """
    Caption a highlight window inside a longer VOD by sampling N frames
    spread across the window.
    """
    duration = max(0.0, end - start)
    if duration <= 0:
        return {"captions": [], "combined": ""}

    timestamps = [start + duration * (i + 1) / (n_frames + 1) for i in range(n_frames)]
    captions = []
    for t in timestamps:
        frame_bytes = _sample_frame(vod_path, t)
        if not frame_bytes:
            continue
        caption = _caption_image(frame_bytes, model=model)
        if caption:
            captions.append(caption)

    return {
        "captions": captions,
        "combined": " ".join(captions),
    }


# =============================================================================
# Caching helpers (for the training pipeline)
# =============================================================================

def caption_cache_path(clip_path: Path) -> Path:
    return paths.CLIP_TRANSCRIPTS_DIR / f"{clip_path.stem}.vision.txt"


def get_or_caption_clip(clip_path: Path, model: str = DEFAULT_MODEL,
                        n_frames: int = 3, force: bool = False) -> str:
    """
    Returns the cached caption string for a clip, generating it if missing.
    Used by the classifier trainer.
    """
    cache = caption_cache_path(clip_path)
    if cache.exists() and not force:
        return cache.read_text(encoding="utf-8").strip()
    result = describe_clip(clip_path, model=model, n_frames=n_frames)
    text = result.get("combined", "").strip()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m modules.vision_describer.vision_describer <video.mp4>")
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)
    ok, msg = vision_alive()
    print(f"Vision health: {msg}")
    print(json.dumps(describe_clip(path), indent=2))
