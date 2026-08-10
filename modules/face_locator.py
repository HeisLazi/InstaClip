"""Locate the streamer's face in a video frame → bounding box.

Powers face-CENTERED reframing (Lazarus 2026-07-06: auto-reframe cut his face
half out of frame — defaults assumed a top-right facecam) and the fullcam/smallcam
classifier in scene_layout. Uses the same mediapipe FaceLandmarker model the
reaction scorer already ships; everything degrades to None on any failure so
callers keep their static defaults.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("face_locator")

_landmarker = None


def _get_landmarker():
    """Lazy singleton FaceLandmarker in IMAGE mode (reuses the reaction model)."""
    global _landmarker
    if _landmarker is not None:
        return _landmarker
    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision

        from modules.face_detector.face_detector import _ensure_model
        model = _ensure_model()
        if model is None:
            return None
        options = mp_vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model)),
            running_mode=mp_vision.RunningMode.IMAGE,
            num_faces=3,
            # Stream frames often show a SMALL corner facecam — the 0.5 default
            # misses it (measured 3/12 → usable at 0.3 on real clips).
            min_face_detection_confidence=0.3,
            min_face_presence_confidence=0.3,
        )
        _landmarker = mp_vision.FaceLandmarker.create_from_options(options)
        return _landmarker
    except Exception as exc:  # noqa: BLE001 — face features are always optional
        log.info("face landmarker unavailable: %s", exc)
        return None


def _grab_frame(video: Path, at_seconds: float) -> Optional[Path]:
    out = Path(tempfile.gettempdir()) / f"_face_frame_{abs(hash((str(video), round(at_seconds, 1))))}.jpg"
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, at_seconds):.3f}",
           "-i", str(video), "-frames:v", "1", "-q:v", "3", str(out)]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        return None
    return out


def locate_faces(video: str | Path, at_seconds: float) -> list[dict[str, Any]]:
    """Face bounding boxes (pixels) in the frame at `at_seconds`:
    [{x, y, w, h, frame_w, frame_h, area_ratio}] — largest face first.
    Empty list on any failure (no model, no frame, no face)."""
    lm = _get_landmarker()
    if lm is None:
        return []
    frame = _grab_frame(Path(str(video)), at_seconds)
    if frame is None:
        return []
    try:
        import mediapipe as mp
        image = mp.Image.create_from_file(str(frame))
        result = lm.detect(image)
        fw, fh = image.width, image.height
        boxes: list[dict[str, Any]] = []
        for lms in result.face_landmarks or []:
            xs = [p.x for p in lms]
            ys = [p.y for p in lms]
            x0, x1 = max(0.0, min(xs)) * fw, min(1.0, max(xs)) * fw
            y0, y1 = max(0.0, min(ys)) * fh, min(1.0, max(ys)) * fh
            w, h = x1 - x0, y1 - y0
            if w <= 2 or h <= 2:
                continue
            boxes.append({"x": round(x0), "y": round(y0), "w": round(w), "h": round(h),
                          "frame_w": fw, "frame_h": fh,
                          "area_ratio": round((w * h) / max(1, fw * fh), 5)})
        boxes.sort(key=lambda b: b["w"] * b["h"], reverse=True)
        # Identity-aware ordering: when a face is enrolled, ITS face leads the
        # list (so crops center on the streamer, not the biggest guest).
        if len(boxes) > 1:
            picked = pick_enrolled_face(boxes, frame)
            if picked is not None and picked.get("identity"):
                rest = [b for b in boxes
                        if (b["x"], b["y"], b["w"]) != (picked["x"], picked["y"], picked["w"])]
                boxes = [picked] + rest
        return boxes
    except Exception as exc:  # noqa: BLE001
        log.debug("face locate failed at %.1fs: %s", at_seconds, exc)
        return []
    finally:
        try:
            frame.unlink()
        except OSError:
            pass


def first_faces(video: str | Path, times: list[float]) -> list[dict[str, Any]]:
    """Sample several timestamps and return the first frame's faces found —
    single-frame detection misses gameplay-only frames, so callers should pass
    a few points across their window (e.g. 25/50/75%)."""
    for t in times:
        faces = locate_faces(video, t)
        if faces:
            return faces
    return []


def face_centered_crop_box(video: str | Path, at_seconds: float,
                           source_w: int, source_h: int,
                           aspect: float = 9 / 16,
                           faces: Optional[list[dict[str, Any]]] = None) -> Optional[list[int]]:
    """A [x, y, w, h] crop of `aspect` (w/h) centered on the largest face.
    None when no face is found (caller keeps its static default).
    `faces` injectable for tests."""
    found = faces if faces is not None else locate_faces(video, at_seconds)
    if not found:
        return None
    f = found[0]
    crop_h = source_h
    crop_w = round(crop_h * aspect)
    if crop_w > source_w:
        crop_w = source_w
        crop_h = round(crop_w / aspect)
    cx = f["x"] + f["w"] / 2
    cy = f["y"] + f["h"] / 2
    x = int(min(max(0, cx - crop_w / 2), source_w - crop_w))
    y = int(min(max(0, cy - crop_h / 2), source_h - crop_h))
    return [x, y, crop_w, crop_h]


def face_cam_box(video: str | Path, at_seconds: float,
                 source_w: int, source_h: int, expand: float = 2.6,
                 faces: Optional[list[dict[str, Any]]] = None) -> Optional[list[int]]:
    """A facecam-style box: the largest face expanded `expand`x (head + shoulders),
    clamped to the frame. None when no face is found."""
    found = faces if faces is not None else locate_faces(video, at_seconds)
    if not found:
        return None
    f = found[0]
    w = min(source_w, round(f["w"] * expand))
    h = min(source_h, round(f["h"] * expand))
    cx, cy = f["x"] + f["w"] / 2, f["y"] + f["h"] / 2
    x = int(min(max(0, cx - w / 2), source_w - w))
    y = int(min(max(0, cy - h / 2), source_h - h))
    return [x, y, w, h]


# ---------------------------------------------------------------------------
# Face IDENTITY (v1): enrolled appearance matching.
# Detection finds A face; with a guest on screen that can be the WRONG face
# (Lazarus 2026-07-06). Enrollment stores appearance signatures (HSV histograms
# of the face crop) from reference photos; at reframe time the detected face
# closest to the enrolled signature wins. This is appearance matching, not
# biometric FR — a proper embedding model can replace `_signature` later without
# changing callers.
# ---------------------------------------------------------------------------

FACES_DIR_NAME = "faces"


def _faces_dir():
    from config import paths
    d = paths.DATA_DIR / FACES_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _signature(image_path: Path, box: dict[str, Any]) -> Optional[list[float]]:
    """Normalized HSV histogram of the face crop — cheap appearance signature."""
    try:
        import cv2
        import numpy as np
        img = cv2.imread(str(image_path))
        if img is None:
            return None
        x, y, w, h = box["x"], box["y"], box["w"], box["h"]
        crop = img[max(0, y):y + h, max(0, x):x + w]
        if crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256])
        hist = hist.flatten()
        total = float(hist.sum()) or 1.0
        return [float(v) / total for v in hist]
    except Exception as exc:  # noqa: BLE001
        log.debug("signature failed: %s", exc)
        return None


def _sig_similarity(a: list[float], b: list[float]) -> float:
    """Histogram intersection (0..1)."""
    return float(sum(min(x, y) for x, y in zip(a, b)))


# --- Real face recognition (OpenCV SFace + YuNet), preferred over histograms ---
_ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models"
_YUNET_URL = f"{_ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx"
_SFACE_URL = f"{_ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx"
SFACE_MATCH_THRESHOLD = 0.363   # OpenCV-documented cosine threshold for SFace

_fr = {"det": None, "rec": None, "tried": False}


def _fr_models():
    """Lazy YuNet detector + SFace recognizer (models auto-download like the
    face_landmarker does). Returns (detector, recognizer) or (None, None)."""
    if _fr["tried"]:
        return _fr["det"], _fr["rec"]
    _fr["tried"] = True
    try:
        import urllib.request

        import cv2
        from config import paths
        mdir = paths.DATA_DIR / "models"
        mdir.mkdir(parents=True, exist_ok=True)
        files = {}
        for key, url in (("yunet", _YUNET_URL), ("sface", _SFACE_URL)):
            dest = mdir / url.rsplit("/", 1)[-1]
            if not dest.exists():
                log.info("downloading %s model...", key)
                with urllib.request.urlopen(url, timeout=60) as resp:
                    dest.write_bytes(resp.read())
            files[key] = dest
        _fr["det"] = cv2.FaceDetectorYN.create(str(files["yunet"]), "", (320, 320),
                                               score_threshold=0.6)
        _fr["rec"] = cv2.FaceRecognizerSF.create(str(files["sface"]), "")
    except Exception as exc:  # noqa: BLE001 — fall back to histogram matching
        log.info("SFace/YuNet unavailable (%s) — using histogram fallback", exc)
    return _fr["det"], _fr["rec"]


def _sface_embeddings(image_path: Path, near_box: Optional[dict[str, Any]] = None) -> list:
    """SFace embedding(s) for faces in an image. When `near_box` is given, only
    the YuNet detection overlapping it; otherwise the largest face."""
    det, rec = _fr_models()
    if det is None or rec is None:
        return []
    try:
        import cv2
        import numpy as np
        img = cv2.imread(str(image_path))
        if img is None:
            return []
        h, w = img.shape[:2]
        det.setInputSize((w, h))
        _, faces = det.detect(img)
        if faces is None or len(faces) == 0:
            return []
        rows = list(faces)
        if near_box is not None:
            cx, cy = near_box["x"] + near_box["w"] / 2, near_box["y"] + near_box["h"] / 2
            rows.sort(key=lambda r: (r[0] + r[2] / 2 - cx) ** 2 + (r[1] + r[3] / 2 - cy) ** 2)
            rows = rows[:1]
        else:
            rows.sort(key=lambda r: r[2] * r[3], reverse=True)
            rows = rows[:1]
        out = []
        for row in rows:
            aligned = rec.alignCrop(img, np.asarray(row))
            out.append(rec.feature(aligned).flatten())
        return out
    except Exception as exc:  # noqa: BLE001
        log.debug("sface embed failed for %s: %s", image_path, exc)
        return []


def _cosine(a, b) -> float:
    import numpy as np
    a = np.asarray(a); b = np.asarray(b)
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1e-9
    return float(a @ b / denom)


def enroll_face(name: str, image_paths: list[str | Path]) -> dict[str, Any]:
    """Store face identity from reference photos (the face must be the prominent
    one in each photo). Prefers REAL SFace embeddings (biometric); falls back to
    appearance histograms when the models are unavailable. Overwrites previous
    enrollment for `name`."""
    import json

    # Preferred path: SFace biometric embeddings.
    vectors, used_v = [], []
    for p in image_paths:
        p = Path(str(p))
        embs = _sface_embeddings(p)
        if embs:
            vectors.append([float(v) for v in embs[0]])
            used_v.append(p.name)
    if vectors:
        out = _faces_dir() / f"{name}.json"
        out.write_text(json.dumps({"name": name, "kind": "sface",
                                   "vectors": vectors, "photos": used_v}),
                       encoding="utf-8")
        log.info("enrolled face '%s' (SFace) from %d photo(s)", name, len(vectors))
        return {"name": name, "photos": len(vectors), "kind": "sface"}

    sigs: list[list[float]] = []
    used: list[str] = []
    for p in image_paths:
        p = Path(str(p))
        # Reference photos: detect on the image directly (largest face wins).
        lm = _get_landmarker()
        if lm is None:
            raise RuntimeError("face model unavailable")
        try:
            import mediapipe as mp
            image = mp.Image.create_from_file(str(p))
            result = lm.detect(image)
            fw, fh = image.width, image.height
            boxes = []
            for lms in result.face_landmarks or []:
                xs = [q.x for q in lms]; ys = [q.y for q in lms]
                boxes.append({"x": round(min(xs) * fw), "y": round(min(ys) * fh),
                              "w": round((max(xs) - min(xs)) * fw),
                              "h": round((max(ys) - min(ys)) * fh)})
            if not boxes:
                continue
            box = max(boxes, key=lambda b: b["w"] * b["h"])
            sig = _signature(p, box)
            if sig:
                sigs.append(sig)
                used.append(p.name)
        except Exception as exc:  # noqa: BLE001
            log.warning("enroll photo %s failed: %s", p.name, exc)
    if not sigs:
        raise RuntimeError("no usable face found in the reference photos")
    out = _faces_dir() / f"{name}.json"
    out.write_text(json.dumps({"name": name, "kind": "hist",
                               "signatures": sigs, "photos": used}),
                   encoding="utf-8")
    log.info("enrolled face '%s' (histogram fallback) from %d photo(s)", name, len(sigs))
    return {"name": name, "photos": len(sigs), "kind": "hist"}


def _load_face_record(name: str) -> dict[str, Any]:
    import json
    f = _faces_dir() / f"{name}.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _load_face_signatures(name: str) -> list[list[float]]:
    return _load_face_record(name).get("signatures") or []


def pick_enrolled_face(faces: list[dict[str, Any]], frame_image: Path,
                       name: str = "lazi", min_similarity: float = 0.35,
                       signatures: Optional[list[list[float]]] = None,
                       sig_fn=None) -> Optional[dict[str, Any]]:
    """Among detected faces, the one matching the enrolled identity — or the
    largest face when nobody is enrolled / nothing matches confidently.
    SFace biometric matching when enrolled with it; histogram fallback otherwise."""
    if not faces:
        return None

    if signatures is None and sig_fn is None:
        record = _load_face_record(name)
        if record.get("kind") == "sface" and record.get("vectors"):
            best, best_score = None, 0.0
            for f in faces:
                embs = _sface_embeddings(Path(str(frame_image)), near_box=f)
                if not embs:
                    continue
                score = max(_cosine(embs[0], ref) for ref in record["vectors"])
                if score > best_score:
                    best, best_score = f, score
            if best is not None and best_score >= SFACE_MATCH_THRESHOLD:
                best = dict(best)
                best["identity"] = name
                best["identity_score"] = round(best_score, 3)
                return best
            return faces[0]

    sigs = signatures if signatures is not None else _load_face_signatures(name)
    if not sigs:
        return faces[0]  # no enrollment — keep previous largest-face behaviour
    make_sig = sig_fn or _signature
    best, best_score = None, 0.0
    for f in faces:
        s = make_sig(frame_image, f)
        if not s:
            continue
        score = max(_sig_similarity(s, ref) for ref in sigs)
        if score > best_score:
            best, best_score = f, score
    if best is not None and best_score >= min_similarity:
        best = dict(best)
        best["identity"] = name
        best["identity_score"] = round(best_score, 3)
        return best
    return faces[0]


__all__ = ["locate_faces", "first_faces", "face_centered_crop_box", "face_cam_box",
           "enroll_face", "pick_enrolled_face"]
