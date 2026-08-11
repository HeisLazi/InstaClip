# =============================================================================
# modules/editor.py — Clip editor engine
# Project LeK
# =============================================================================
# PURPOSE:
#   Post-cut editing for clips: trim, crop, the 9:16 reaction reframe
#   (facecam stacked above the reacted content), audio boost/normalise, and
#   sound-FX overlays. Everything is driven by a single "edit spec" dict so the
#   frontend can describe an edit declaratively and we render it in one ffmpeg
#   pass.
#
#   This codifies the manual ffmpeg work (the football reframe, the bet-reveal
#   sound layering, etc.) into reusable, testable operations.
#
# EDIT SPEC (all fields optional except a layout):
#   {
#     "trim":        {"start": 2.0, "end": 18.0},      # seconds into source
#     "layout":      "reaction" | "crop" | "fullcam" | "passthrough",
#     "cam_box":     [x, y, w, h],   # facecam region in source (reaction/fullcam)
#     "content_box": [x, y, w, h],   # reacted content region in source (reaction)
#     "crop_box":    [x, y, w, h],   # region to keep (crop layout)
#     "audio_boost_db": 6.0,         # simple volume gain in dB
#     "audio_normalize": true,       # EBU R128 loudnorm (fixes quiet clips)
#     "sound_fx":    [{"name": "boom", "at": 3.5, "gain": 0.9}, ...],
#     "output_stem": "my_edit"       # optional; auto-derived otherwise
#   }
# =============================================================================

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from config import paths

log = logging.getLogger("editor")

# Output canvas for vertical social clips.
OUT_W, OUT_H = 1080, 1920
# In the reaction stack: facecam occupies a top band, content sits below it.
CAM_TOP = 55
CAM_H = 600
CONTENT_TOP = 660

# Where edited clips and sound FX live.
EDITED_DIR = paths.OUTPUT_DIR / "edited"
SOUNDS_DIR = paths.DATA_DIR / "sounds"
MEDIA_DIR = paths.DATA_DIR / "editor_media"
MEDIA_THUMBS_DIR = paths.DATA_DIR / "editor_media_thumbs"
CUSTOM_PRESETS_FILE = paths.DATA_DIR / "editor_presets.json"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _ensure_dirs() -> None:
    EDITED_DIR.mkdir(parents=True, exist_ok=True)
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_THUMBS_DIR.mkdir(parents=True, exist_ok=True)


def probe(path: Path) -> dict[str, Any]:
    """Return duration, width, height, fps for a media file."""
    r = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "stream=codec_type,width,height,r_frame_rate",
         "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(r.stdout)
        streams = data.get("streams") or []
        stream = next((item for item in streams if item.get("codec_type") == "video"), {})
        num, _, den = (stream.get("r_frame_rate") or "30/1").partition("/")
        fps = float(num) / float(den) if den and float(den) else 30.0
        return {
            "duration": float(data.get("format", {}).get("duration") or 0.0),
            "width": int(stream.get("width") or 0),
            "height": int(stream.get("height") or 0),
            "fps": round(fps, 3),
            "has_audio": any(item.get("codec_type") == "audio" for item in streams),
        }
    except (json.JSONDecodeError, ValueError, KeyError):
        return {"duration": 0.0, "width": 0, "height": 0, "fps": 30.0,
                "has_audio": False}


def media_kind(path: Path) -> Optional[str]:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    return None


def media_info(path: Path) -> dict[str, Any]:
    info = probe(path)
    kind = media_kind(path)
    return {
        "id": path.stem,
        "name": path.name,
        "kind": kind,
        "duration": info["duration"] if kind == "video" else 0.0,
        "width": info["width"],
        "height": info["height"],
        "has_audio": info["has_audio"],
        "size_mb": round(path.stat().st_size / (1024 * 1024), 2),
    }


def list_media() -> list[dict[str, Any]]:
    """Return persistent image/video assets imported into the editor bin."""
    _ensure_dirs()
    assets = [media_info(path) for path in MEDIA_DIR.iterdir()
              if path.is_file() and media_kind(path)]
    return sorted(assets, key=lambda item: item["name"].lower())


def media_thumbnail(path: Path) -> Path:
    """Return an image suitable for the media bin, generating video thumbs lazily."""
    _ensure_dirs()
    if media_kind(path) == "image":
        return path
    out = MEDIA_THUMBS_DIR / f"{path.stem}.jpg"
    if out.exists() and out.stat().st_mtime >= path.stat().st_mtime:
        return out
    out.unlink(missing_ok=True)
    info = probe(path)
    at = min(1.0, max(0.0, info["duration"] / 3))
    cmd = ["ffmpeg", "-y", "-ss", str(round(at, 3)), "-i", str(path),
           "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "3", str(out)]
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"thumbnail render failed: {result.stderr.decode()[-400:]}")
    return out


def list_sounds() -> list[dict[str, Any]]:
    """Available sound-FX in the global sounds folder (drop the palette here)."""
    _ensure_dirs()
    out: list[dict[str, Any]] = []
    for f in sorted(SOUNDS_DIR.glob("*")):
        if f.suffix.lower() in (".mp3", ".wav", ".m4a", ".mp4", ".aac", ".ogg"):
            out.append({"name": f.stem, "file": f.name, "duration": probe(f)["duration"]})
    return out


def _sound_path(name: str) -> Optional[Path]:
    for f in SOUNDS_DIR.glob("*"):
        if f.stem.lower() == name.lower():
            return f
    return None


def sound_path(name: str) -> Optional[Path]:
    """Resolve one sound-bin item by its public stem."""
    return _sound_path(name)


# -----------------------------------------------------------------------------
# Filtergraph construction
# -----------------------------------------------------------------------------

def _video_chain(spec: dict[str, Any]) -> str:
    """Build the [0:v] -> [vout] portion of the filtergraph for a layout."""
    layout = spec.get("layout", "passthrough")

    if layout == "reaction":
        cx, cy, cw, ch = spec["cam_box"]
        gx, gy, gw, gh = spec["content_box"]
        return (
            "[0:v]split=3[bg][cam][game];"
            f"[bg]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
            f"crop={OUT_W}:{OUT_H},boxblur=28,setsar=1[bgb];"
            f"[cam]crop={cw}:{ch}:{cx}:{cy},"
            f"scale={OUT_W}:{CAM_H}:force_original_aspect_ratio=increase,"
            f"crop={OUT_W}:{CAM_H},setsar=1[camv];"
            f"[game]crop={gw}:{gh}:{gx}:{gy},scale={OUT_W}:-2,setsar=1[gamev];"
            f"[bgb][camv]overlay=0:{CAM_TOP}[t1];"
            f"[t1][gamev]overlay=0:{CONTENT_TOP},format=yuv420p[vout]"
        )

    if layout == "crop":
        # FIT the selected region and blur-pad the rest — never fill-and-slice.
        # The old chain (scale=increase + a second centre-crop) silently chopped
        # any box that wasn't exactly 9:16 (editors pick wide/YouTube-ish boxes
        # via Discord's "Different crop"), over-zooming and cutting people in
        # half. A true 9:16 box still renders edge-to-edge exactly as before.
        x, y, w, h = spec["crop_box"]
        return (
            "[0:v]split=2[bg][fg];"
            f"[bg]crop={w}:{h}:{x}:{y},scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
            f"crop={OUT_W}:{OUT_H},boxblur=28,setsar=1[bgb];"
            f"[fg]crop={w}:{h}:{x}:{y},scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
            "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1[fgv];"
            "[bgb][fgv]overlay=(W-w)/2:(H-h)/2,format=yuv420p[vout]"
        )

    if layout == "fullcam":
        # Facecam centered at full width, with a blurred ZOOMED COPY OF ITSELF
        # filling the 9:16 background (the posted "full cam" look).
        cx, cy, cw, ch = spec.get("cam_box") or [0, 0, 0, 0]
        crop = f"crop={cw}:{ch}:{cx}:{cy}," if (cw and ch) else ""
        return (
            "[0:v]split=2[bg][cam];"
            f"[bg]{crop}scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
            f"crop={OUT_W}:{OUT_H},boxblur=28,setsar=1[bgb];"
            f"[cam]{crop}scale={OUT_W}:-2,setsar=1[camv];"
            f"[bgb][camv]overlay=0:(H-h)/2,format=yuv420p[vout]"
        )

    # passthrough — keep source frame, just ensure even dims.
    return "[0:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1,format=yuv420p[vout]"


def _audio_chain(spec: dict[str, Any], fx_specs: list[dict[str, Any]],
                 main_input_index: int = 0, fx_input_start: int = 1,
                 process_main: bool = True) -> str:
    """Build the audio portion: boost/normalise the main track, then mix in
    any sound FX (each delayed to its timestamp). FX inputs are indices 1..N.

    `fx_specs` is the resolved, in-order list of FX specs — exactly one per FX
    input already appended to the ffmpeg command. Passing it explicitly (rather
    than a count + re-reading ``spec["sound_fx"]``) means the timing/gain for
    input k can never drift onto the wrong spec when an unresolved sound was
    dropped upstream. That drift was the H1 misalignment bug."""
    parts: list[str] = []
    main = f"[{main_input_index}:a]"
    filters = []
    if process_main and spec.get("audio_normalize"):
        # EBU R128 loudnorm — the right fix for "it be quiet".
        filters.append("loudnorm=I=-14:TP=-1.5:LRA=11")
    boost = spec.get("audio_boost_db")
    if process_main and boost:
        filters.append(f"volume={float(boost)}dB")
    if filters:
        parts.append(f"{main}{','.join(filters)}[main]")
        main_label = "[main]"
    else:
        parts.append(f"{main}anull[main]")
        main_label = "[main]"

    if not fx_specs:
        # Rename [main] -> [aout]
        parts[-1] = parts[-1].replace("[main]", "[aout]")
        return ";".join(parts)

    mix_labels = [main_label]
    for k, fx in enumerate(fx_specs):
        at = float(fx.get("at", 0.0))
        gain = float(fx.get("gain", 1.0))
        ms = int(at * 1000)
        idx = fx_input_start + k
        parts.append(f"[{idx}:a]adelay={ms}|{ms},volume={gain}[fx{k}]")
        mix_labels.append(f"[fx{k}]")
    parts.append(
        "".join(mix_labels)
        + f"amix=inputs={len(mix_labels)}:duration=first:normalize=0[aout]"
    )
    return ";".join(parts)


# -----------------------------------------------------------------------------
# Render
# -----------------------------------------------------------------------------

def _resolve_fx_inputs(spec: dict[str, Any]) -> list[tuple[Path, dict[str, Any]]]:
    fx_specs = spec.get("sound_fx", []) or []
    resolved: list[tuple[Path, dict[str, Any]]] = []
    for fx in fx_specs:
        p = _sound_path(str(fx.get("name", "")))
        if p is not None:
            resolved.append((p, fx))
    return resolved


def _default_layout_boxes(spec: dict[str, Any], source_info: dict[str, Any],
                          source: Optional[Path] = None) -> dict[str, Any]:
    """Fill in missing layout boxes so a boxless edit request renders instead of
    crashing — FACE-CENTERED when a face is found (static template defaults
    assumed a top-right facecam and cut the streamer half out of frame), template
    defaults otherwise. Never overrides boxes the caller supplied."""
    layout = spec.get("layout", "passthrough")
    needed = {"reaction": ("cam_box", "content_box"),
              "crop": ("crop_box",),
              "fullcam": ("cam_box",)}.get(layout, ())
    missing = [k for k in needed if not spec.get(k)]
    if not missing:
        return spec
    w = source_info.get("width") or 1920
    h = source_info.get("height") or 1080
    tpl = templates(w, h)
    defaults = {"reaction": tpl["reaction_stack"], "crop": tpl["crop_916"],
                "fullcam": tpl["fullcam_blur"]}[layout]

    # Try to center on the streamer's actual face at the middle of the clip window.
    face_boxes: dict[str, Any] = {}
    if source is not None:
        try:
            from modules.face_locator import face_cam_box, face_centered_crop_box, first_faces
            trim = spec.get("trim") or {}
            t0 = float(trim.get("start", 0.0))
            t1 = float(trim.get("end", 0.0)) or (t0 + 8.0)
            span = max(1.0, t1 - t0)
            # Sample DENSELY across the window — reaction clips alternate between
            # the cam and the reacted content, so a few samples can all land on
            # content frames with no face (real fullcam render failure 2026-07-06).
            samples = [t0 + span * f for f in (0.5, 0.25, 0.75, 0.125, 0.375, 0.625, 0.875)]
            faces = first_faces(source, samples)
            if faces:
                if "cam_box" in missing:
                    face_boxes["cam_box"] = face_cam_box(source, 0, w, h, faces=faces)
                if "crop_box" in missing:
                    face_boxes["crop_box"] = face_centered_crop_box(source, 0, w, h, faces=faces)
        except Exception as exc:  # noqa: BLE001 — face centering must never break a render
            log.debug("face-centered defaults unavailable: %s", exc)

    # No-face fallback for FULLCAM: a centered 9:16 crop beats the template's
    # full-frame box — the full frame renders as a small letterboxed band in the
    # blur, which is never what "full cam" means (Lazarus render 2026-07-06).
    if layout == "fullcam" and "cam_box" in missing and "cam_box" not in face_boxes:
        side = round(h * 9 / 16)
        face_boxes["cam_box"] = [round((w - side) / 2), 0, side, h]
        log.info("fullcam: no face found across samples — using centered 9:16 crop")

    out = dict(spec)
    for k in missing:
        out[k] = face_boxes.get(k, defaults.get(k))
    out = {k: v for k, v in out.items() if v is not None}
    log.info("edit spec omitted %s for layout=%s — defaulted (%s)", missing, layout,
             "face-centered" if face_boxes else "template")
    return out


def render_edit(source: Path, spec: dict[str, Any], preview_at: Optional[float] = None) -> Path:
    """Render an edit spec against `source`.

    If `preview_at` is given, render a single JPEG frame at that time (for the
    UI's live crop/reframe preview) and return the image path. Otherwise render
    the full edited MP4 and return its path.
    """
    _ensure_dirs()
    if not source.exists():
        raise FileNotFoundError(f"source clip not found: {source}")

    source_info = probe(source)
    trim = spec.get("trim") or {}
    ss = trim.get("start")
    end = trim.get("end")
    dur = (float(end) - float(ss)) if (ss is not None and end is not None) else None

    # A Discord/API edit request may name a layout without supplying its boxes
    # (users don't know pixel coords). Default the missing boxes from the same
    # source-sized presets the frontend templates use, instead of KeyError-ing
    # the render (the "claimed edit never came back" bug).
    spec = _default_layout_boxes(spec, source_info, source=source)

    resolved_fx = _resolve_fx_inputs(spec) if preview_at is None else []
    fx_paths = [path for path, _ in resolved_fx]
    vchain = _video_chain(spec)

    cmd: list[str] = ["ffmpeg", "-y"]
    # Trim as INPUT options on the source: -ss (fast seek) + -t (read duration),
    # both placed before -i source so they don't bind to later FX inputs.
    if ss is not None:
        cmd += ["-ss", str(round(float(ss), 3))]
    if dur is not None:
        cmd += ["-t", str(round(dur, 3))]
    cmd += ["-i", str(source)]

    if preview_at is not None:
        # Single-frame preview — video only, fast.
        rel = max(0.0, float(preview_at) - float(ss or 0.0))
        out = EDITED_DIR / f"_preview_{uuid.uuid4().hex[:8]}.jpg"
        cmd += ["-filter_complex", vchain, "-map", "[vout]",
                "-ss", str(round(rel, 3)), "-frames:v", "1", "-q:v", "3", str(out)]
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            raise RuntimeError(f"preview render failed: {r.stderr.decode()[-400:]}")
        return out

    # Supply silence for imported videos that do not contain an audio stream.
    main_audio_index = 0
    if not source_info["has_audio"]:
        silent_duration = dur if dur is not None else max(
            0.1, float(source_info["duration"]) - float(ss or 0.0)
        )
        main_audio_index = 1
        cmd += ["-f", "lavfi", "-t", str(round(silent_duration, 3)),
                "-i", "anullsrc=r=48000:cl=stereo"]

    # Full render. FX inputs are added after the source and optional silence.
    fx_input_start = main_audio_index + 1
    for fx in fx_paths:
        cmd += ["-i", str(fx)]
    # Pass the resolved (path, spec) pairs' specs in the SAME order as the FX
    # inputs above, so each input lines up with its own at/gain — see H1.
    achain = _audio_chain(
        spec, [fx for _, fx in resolved_fx], main_audio_index, fx_input_start,
        process_main=bool(source_info["has_audio"]),
    )
    filt = f"{vchain};{achain}"

    out_stem = spec.get("output_stem") or f"{source.stem}_edit_{time.strftime('%H%M%S')}"
    out = EDITED_DIR / f"{out_stem}.mp4"
    out.unlink(missing_ok=True)
    cmd += ["-filter_complex", filt, "-map", "[vout]", "-map", "[aout]",
            "-r", "30", "-c:v", "libx264", "-preset", "fast", "-crf", "19",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]

    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"edit render failed: {r.stderr.decode()[-600:]}")
    log.info(f"rendered edit -> {out}")
    return out


def templates(width: int, height: int) -> dict[str, dict[str, Any]]:
    """Named edit presets with boxes computed for a given source size.
    The frontend offers these as one-click 'auto-select templates'."""
    w = width or 1920
    h = height or 1080
    cam_w, cam_h = round(w * 0.28), round(h * 0.28)
    side = round(h * 9 / 16)
    return {
        "fullcam_blur": {
            "label": "Full cam (blur bg)",
            "layout": "fullcam",
            "cam_box": [0, 0, w, h],
            "audio_normalize": True,
        },
        "reaction_stack": {
            "label": "Reaction stack",
            "layout": "reaction",
            "cam_box": [w - cam_w, 0, cam_w, cam_h],
            "content_box": [0, 0, round(w * 0.77), h],
            "audio_normalize": True,
        },
        "crop_916": {
            "label": "Crop 9:16",
            "layout": "crop",
            "crop_box": [round((w - side) / 2), 0, side, h],
            "audio_normalize": True,
        },
    }


def _read_custom_presets() -> dict[str, Any]:
    if not CUSTOM_PRESETS_FILE.exists():
        return {"version": 1, "presets": []}
    try:
        data = json.loads(CUSTOM_PRESETS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "presets": []}
    if not isinstance(data, dict) or not isinstance(data.get("presets"), list):
        return {"version": 1, "presets": []}
    return data


def _write_custom_presets(data: dict[str, Any]) -> None:
    CUSTOM_PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CUSTOM_PRESETS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(CUSTOM_PRESETS_FILE)


def _normalise_box(value: Any, width: int, height: int) -> Optional[list[float]]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x, y, box_width, box_height = (float(item) for item in value)
    except (TypeError, ValueError):
        return None
    safe_width = max(1, width)
    safe_height = max(1, height)
    return [
        max(0.0, min(1.0, x / safe_width)),
        max(0.0, min(1.0, y / safe_height)),
        max(0.001, min(1.0, box_width / safe_width)),
        max(0.001, min(1.0, box_height / safe_height)),
    ]


def _materialise_box(value: Any, width: int, height: int) -> Optional[list[int]]:
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        x, y, box_width, box_height = (float(item) for item in value)
    except (TypeError, ValueError):
        return None
    return [
        round(x * width),
        round(y * height),
        max(1, round(box_width * width)),
        max(1, round(box_height * height)),
    ]


def list_custom_presets(width: int, height: int) -> list[dict[str, Any]]:
    """Return user presets scaled from stored ratios to this source size."""
    presets: list[dict[str, Any]] = []
    for stored in _read_custom_presets()["presets"]:
        if not isinstance(stored, dict):
            continue
        preset = {
            "id": str(stored.get("id") or ""),
            "label": str(stored.get("label") or "Custom preset"),
            "layout": stored.get("layout", "passthrough"),
            "audio_normalize": bool(stored.get("audio_normalize", False)),
            "audio_boost_db": float(stored.get("audio_boost_db") or 0.0),
        }
        for key in ("cam_box", "content_box", "crop_box"):
            box = _materialise_box(stored.get(key), width, height)
            if box is not None:
                preset[key] = box
        presets.append(preset)
    return presets


def save_custom_preset(name: str, spec: dict[str, Any], width: int,
                       height: int) -> dict[str, Any]:
    """Persist a resolution-independent editor preset."""
    label = " ".join(str(name).split()).strip()[:80]
    if not label:
        raise ValueError("preset name is required")
    layout = str(spec.get("layout") or "passthrough")
    if layout not in {"reaction", "crop", "fullcam", "passthrough"}:
        raise ValueError(f"unsupported preset layout: {layout}")
    stored: dict[str, Any] = {
        "id": uuid.uuid4().hex[:12],
        "label": label,
        "layout": layout,
        "audio_normalize": bool(spec.get("audio_normalize", False)),
        "audio_boost_db": max(-24.0, min(24.0, float(spec.get("audio_boost_db") or 0.0))),
        "updated_at": time.time(),
    }
    for key in ("cam_box", "content_box", "crop_box"):
        box = _normalise_box(spec.get(key), width, height)
        if box is not None:
            stored[key] = box
    data = _read_custom_presets()
    data["presets"].append(stored)
    _write_custom_presets(data)
    return next(
        preset for preset in list_custom_presets(width, height)
        if preset["id"] == stored["id"]
    )


def delete_custom_preset(preset_id: str) -> bool:
    data = _read_custom_presets()
    original = len(data["presets"])
    data["presets"] = [
        preset for preset in data["presets"]
        if not isinstance(preset, dict) or str(preset.get("id")) != preset_id
    ]
    if len(data["presets"]) == original:
        return False
    _write_custom_presets(data)
    return True


def automatic_spec(source: Path, trim: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Build a safe center-crop edit for arbitrary imported video dimensions."""
    info = probe(source)
    width = info["width"] or 1920
    height = info["height"] or 1080
    target_ratio = OUT_W / OUT_H
    if width / height >= target_ratio:
        crop_height = height
        crop_width = max(2, round(height * target_ratio))
    else:
        crop_width = width
        crop_height = max(2, round(width / target_ratio))
    spec: dict[str, Any] = {
        "layout": "crop",
        "crop_box": [
            max(0, round((width - crop_width) / 2)),
            max(0, round((height - crop_height) / 2)),
            crop_width,
            crop_height,
        ],
        "audio_normalize": True,
    }
    if trim:
        spec["trim"] = trim
    return spec


def render_still(source: Path, duration: float, output_stem: str) -> Path:
    """Render an image as a vertical still with a blurred fill and silent audio."""
    _ensure_dirs()
    safe_duration = max(0.1, min(float(duration), 300.0))
    out = EDITED_DIR / f"{output_stem}.mp4"
    out.unlink(missing_ok=True)
    filt = (
        "[0:v]split=2[bg][fg];"
        f"[bg]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{OUT_H},boxblur=28,setsar=1[bgv];"
        f"[fg]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,setsar=1[fgv];"
        "[bgv][fgv]overlay=(W-w)/2:(H-h)/2,format=yuv420p[vout]"
    )
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-t", str(round(safe_duration, 3)),
        "-i", str(source), "-f", "lavfi", "-t", str(round(safe_duration, 3)),
        "-i", "anullsrc=r=48000:cl=stereo", "-filter_complex", filt,
        "-map", "[vout]", "-map", "1:a", "-r", "30", "-c:v", "libx264",
        "-preset", "fast", "-crf", "19", "-c:a", "aac", "-b:a", "192k",
        "-t", str(round(safe_duration, 3)), "-movflags", "+faststart", str(out),
    ]
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"still render failed: {result.stderr.decode()[-600:]}")
    return out


def _render_interstitial(sound: Optional[Path], duration: float,
                         output_stem: str) -> Path:
    """Render a black transition card with the selected sound or silence."""
    safe_duration = max(0.1, min(float(duration), 10.0))
    out = EDITED_DIR / f"{output_stem}.mp4"
    out.unlink(missing_ok=True)
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i",
           f"color=c=black:s={OUT_W}x{OUT_H}:r=30:d={safe_duration}"]
    if sound is not None:
        cmd += ["-i", str(sound), "-filter_complex",
                f"[1:a]atrim=0:{safe_duration},asetpts=PTS-STARTPTS,"
                f"apad=whole_dur={safe_duration}[aout]", "-map", "0:v", "-map", "[aout]"]
    else:
        cmd += ["-f", "lavfi", "-t", str(round(safe_duration, 3)),
                "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v", "-map", "1:a"]
    cmd += ["-t", str(round(safe_duration, 3)), "-c:v", "libx264", "-preset", "fast",
            "-crf", "19", "-c:a", "aac", "-b:a", "192k", str(out)]
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"transition render failed: {result.stderr.decode()[-600:]}")
    return out


# Real cross-clip transitions via ffmpeg xfade. Keys are what the UI sends.
XFADE_TRANSITIONS = {
    "mix": "fade",            # crossfade / dissolve between the two clips
    "dissolve": "fade",
    "fade_black": "fadeblack",  # fade through black
    "fade_white": "fadewhite",  # fade through white
    "bw": "fadegrays",          # "fade to black and white" — fades through grayscale
    "black_and_white": "fadegrays",
    "fade_grays": "fadegrays",
}


def _concat_with_transitions(parts: list[Path], transition: str,
                             duration: float, out: Path) -> Path:
    """Join clips with an ffmpeg xfade transition (mix / fade-black / fade-white /
    fade-to-B&W). Each pair overlaps by `duration`; audio is acrossfaded to match."""
    xf = XFADE_TRANSITIONS.get(transition)
    if not xf or len(parts) < 2:
        return _concat_parts(parts, out)
    out.unlink(missing_ok=True)
    durs = [probe(p)["duration"] for p in parts]
    dur = max(0.2, min(float(duration), 3.0))

    cmd: list[str] = ["ffmpeg", "-y"]
    for part in parts:
        cmd += ["-i", str(part)]
    n = len(parts)

    stmts: list[str] = []
    for i in range(n):
        stmts.append(
            f"[{i}:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
            f"pad={OUT_W}:{OUT_H}:-1:-1,setsar=1,fps=30,format=yuv420p,"
            f"settb=AVTB,setpts=PTS-STARTPTS[v{i}]"
        )
        stmts.append(f"[{i}:a]aresample=48000,asetpts=PTS-STARTPTS[a{i}]")

    prev_v, running = "v0", durs[0]
    for i in range(1, n):
        offset = max(0.0, running - dur)
        label = "vout" if i == n - 1 else f"vx{i}"
        stmts.append(
            f"[{prev_v}][v{i}]xfade=transition={xf}:duration={dur:.3f}:"
            f"offset={offset:.3f}[{label}]"
        )
        running = running + durs[i] - dur
        prev_v = label

    prev_a = "a0"
    for i in range(1, n):
        label = "aout" if i == n - 1 else f"ax{i}"
        stmts.append(f"[{prev_a}][a{i}]acrossfade=d={dur:.3f}[{label}]")
        prev_a = label

    cmd += ["-filter_complex", ";".join(stmts), "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "19",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"transition concat failed: {result.stderr.decode()[-600:]}")
    return out


def _concat_parts(parts: list[Path], out: Path) -> Path:
    out.unlink(missing_ok=True)
    if len(parts) == 1:
        shutil.copy2(parts[0], out)
        return out
    cmd: list[str] = ["ffmpeg", "-y"]
    for part in parts:
        cmd += ["-i", str(part)]
    count = len(parts)
    video_filters = "".join(
        f"[{index}:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
        f"pad={OUT_W}:{OUT_H}:-1:-1,setsar=1,fps=30,setpts=PTS-STARTPTS[v{index}];"
        for index in range(count)
    )
    audio_filters = "".join(
        f"[{index}:a]aresample=48000,asetpts=PTS-STARTPTS[a{index}];"
        for index in range(count)
    )
    concat_inputs = "".join(f"[v{index}][a{index}]" for index in range(count))
    concat = concat_inputs + f"concat=n={count}:v=1:a=1[vout][aout]"
    cmd += ["-filter_complex", video_filters + audio_filters + concat,
            "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264",
            "-preset", "fast", "-crf", "19", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(out)]
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"media concat failed: {result.stderr.decode()[-600:]}")
    return out


def render_compilation(items: list[dict[str, Any]], output_stem: str,
                       transition_sound: Optional[str] = None,
                       transition_duration: float = 0.0,
                       transition_type: Optional[str] = None) -> Path:
    """Render independent mixed-media items and join them.

    `transition_type` picks how clips are joined:
      - None / "card": a black interstitial card (optionally with a sound) — legacy
      - "mix" / "fade_black" / "fade_white" / "bw": a real xfade transition where
        consecutive clips overlap (no black card).
    """
    _ensure_dirs()
    if not items:
        raise ValueError("no compilation items provided")
    token = uuid.uuid4().hex[:8]
    parts: list[Path] = []
    temporary: list[Path] = []
    use_xfade = bool(transition_type) and transition_type in XFADE_TRANSITIONS
    sound = _sound_path(transition_sound) if transition_sound else None
    if transition_sound and sound is None:
        raise ValueError(f"transition sound not found: {transition_sound}")
    try:
        for index, item in enumerate(items):
            source = Path(item["source"])
            kind = item.get("kind") or media_kind(source) or "video"
            spec = dict(item.get("spec") or {})
            part_stem = f"_compile_{token}_{index}"
            if kind == "image":
                trim = spec.get("trim") or {}
                duration = float(trim.get("end", item.get("still_duration", 3.0))) - float(trim.get("start", 0.0))
                part = render_still(source, duration, part_stem)
            else:
                if item.get("automatic"):
                    supplied = spec
                    spec = automatic_spec(source, supplied.get("trim"))
                    for key in ("audio_boost_db", "audio_normalize", "sound_fx"):
                        if key in supplied:
                            spec[key] = supplied[key]
                spec["output_stem"] = part_stem
                part = render_edit(source, spec)
            parts.append(part)
            temporary.append(part)
            # Legacy black-card transition only when NOT using a real xfade.
            if (not use_xfade and index < len(items) - 1
                    and transition_duration > 0):
                transition = _render_interstitial(
                    sound, transition_duration, f"_compile_{token}_transition_{index}"
                )
                parts.append(transition)
                temporary.append(transition)
        out = EDITED_DIR / f"{output_stem}.mp4"
        if use_xfade and len(parts) > 1 and transition_duration > 0:
            return _concat_with_transitions(
                parts, transition_type, transition_duration, out)
        return _concat_parts(parts, out)
    finally:
        for path in temporary:
            path.unlink(missing_ok=True)


def render_segments(source: Path, segments: list[dict[str, Any]],
                    output_stem: Optional[str] = None) -> Path:
    """Render a clip whose layout CHANGES over time (e.g. full-cam -> reaction).

    `segments` is a list of edit specs, each with its own `trim` and layout. We
    render each segment then concatenate them into one vertical clip.
    """
    _ensure_dirs()
    if not segments:
        raise ValueError("no segments provided")

    parts: list[Path] = []
    token = uuid.uuid4().hex[:6]
    for i, seg in enumerate(segments):
        sp = dict(seg)
        sp["output_stem"] = f"_seg_{token}_{i}"
        parts.append(render_edit(source, sp))

    if len(parts) == 1:
        return parts[0]

    out_stem = output_stem or f"{source.stem}_multi_{time.strftime('%H%M%S')}"
    out = EDITED_DIR / f"{out_stem}.mp4"
    out.unlink(missing_ok=True)
    cmd: list[str] = ["ffmpeg", "-y"]
    for p in parts:
        cmd += ["-i", str(p)]
    n = len(parts)
    vp = "".join(
        f"[{i}:v]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
        f"pad={OUT_W}:{OUT_H}:-1:-1,setsar=1,fps=30[v{i}];" for i in range(n)
    )
    cc = "".join(f"[v{i}][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vout][aout]"
    cmd += ["-filter_complex", vp + cc, "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "19",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"segment concat failed: {r.stderr.decode()[-600:]}")
    log.info(f"rendered {n}-segment edit -> {out}")
    return out


def auto_edit(source: Path, cam_box: Optional[list[int]] = None,
              content_box: Optional[list[int]] = None) -> Path:
    """One-shot auto edit: reaction reframe (if cam/content boxes given, else a
    sensible top-right default) + loudness normalise. The user fine-tunes after.
    """
    info = probe(source)
    w, h = info["width"] or 1920, info["height"] or 1080
    if cam_box and content_box:
        spec = {"layout": "reaction", "cam_box": cam_box, "content_box": content_box}
    elif cam_box:
        spec = {"layout": "reaction", "cam_box": cam_box,
                "content_box": [0, 0, int(w * 0.77), h]}
    else:
        # No boxes -> just normalise + center-crop to vertical (safe default).
        side = int(h * 9 / 16)
        spec = {"layout": "crop", "crop_box": [(w - side) // 2, 0, side, h]}
    spec["audio_normalize"] = True
    spec["output_stem"] = f"{source.stem}_auto"
    return render_edit(source, spec)
