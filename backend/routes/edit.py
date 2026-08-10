"""Clip editing: trim, crop, reaction reframe, audio boost, sound FX.

Drives modules/editor.py via a declarative edit spec. Includes a single-frame
preview endpoint so the UI can show crop/reframe boxes live before rendering.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import paths
from modules import editor
from utils.clip_files import find_clip_file, safe_folder_name

log = logging.getLogger("backend.edit")
router = APIRouter(prefix="/edit", tags=["edit"])

_BUCKET_DIRS = {
    "output":    paths.CLIPS_DIR,
    "positives": paths.OLD_CLIPS_DIR,
    "negatives": paths.NOTCLIPS_DIR,
    "edited":    editor.EDITED_DIR,
}


def _resolve(bucket: str, stem: str) -> Path:
    root = _BUCKET_DIRS.get(bucket)
    if root is None:
        raise HTTPException(400, f"unknown bucket '{bucket}'")
    clip = find_clip_file(root, stem)
    if clip is None:
        raise HTTPException(404, f"clip not found: {stem}.mp4")
    return clip


class EditRequest(BaseModel):
    bucket: str = "output"
    stem: str
    spec: dict[str, Any]


class SegmentsRequest(BaseModel):
    bucket: str = "output"
    stem: str
    segments: list[dict[str, Any]]
    output_stem: Optional[str] = None


class PreviewRequest(BaseModel):
    bucket: str = "output"
    stem: str
    spec: dict[str, Any]
    at: float = 0.0


class CompilationRequest(BaseModel):
    items: list[dict[str, Any]]
    output_stem: Optional[str] = None
    transition_sound: Optional[str] = None
    transition_duration: float = 0.0
    # None/"card" = black interstitial; "mix"/"fade_black"/"fade_white"/"bw" = xfade
    transition_type: Optional[str] = None


class CustomPresetRequest(BaseModel):
    name: str
    spec: dict[str, Any]


class TrimSuggestionRequest(BaseModel):
    bucket: str = "output"
    stem: str


def _resolve_media(asset_id: str) -> Path:
    editor.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    if Path(asset_id).name != asset_id:
        raise HTTPException(400, "invalid media id")
    for path in editor.MEDIA_DIR.iterdir():
        if path.is_file() and path.stem == asset_id and editor.media_kind(path):
            return path
    raise HTTPException(404, f"imported media not found: {asset_id}")


@router.get("/sounds")
def sounds():
    """Sound-FX palette available for overlay (drop files in data/sounds/)."""
    return {"sounds_dir": str(editor.SOUNDS_DIR), "sounds": editor.list_sounds()}


@router.get("/sounds/{sound_name}/stream")
def stream_sound(sound_name: str):
    sound = editor.sound_path(sound_name)
    if sound is None:
        raise HTTPException(404, f"sound not found: {sound_name}")
    return FileResponse(str(sound), headers={"Cache-Control": "no-store"})


@router.post("/sounds/import")
async def import_sound(file: UploadFile = File(...)):
    """Import a licensed local audio file into the editor sound bin."""
    editor.SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    original = Path(file.filename or "sound.wav")
    suffix = original.suffix.lower()
    allowed = {".mp3", ".wav", ".m4a", ".mp4", ".aac", ".ogg"}
    if suffix not in allowed:
        raise HTTPException(400, f"unsupported sound type: {suffix or 'unknown'}")
    stem = safe_folder_name(original.stem, fallback="sound")
    destination = editor.SOUNDS_DIR / f"{stem}{suffix}"
    counter = 1
    while destination.exists():
        destination = editor.SOUNDS_DIR / f"{stem}_{counter}{suffix}"
        counter += 1

    max_bytes = 64 * 1024 * 1024
    written = 0
    try:
        with open(destination, "wb") as output:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(413, "sound file exceeds 64 MB")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    info = editor.probe(destination)
    return {
        "ok": True,
        "sound": {
            "name": destination.stem,
            "file": destination.name,
            "duration": info["duration"],
        },
    }


@router.get("/media")
def media():
    """List persistent images and videos imported from the local machine."""
    return {"media_dir": str(editor.MEDIA_DIR), "assets": editor.list_media()}


@router.post("/media/import")
async def import_media(file: UploadFile = File(...)):
    """Copy an image or video into the editor's persistent local media bin."""
    editor.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    original = Path(file.filename or "media")
    suffix = original.suffix.lower()
    if suffix not in editor.IMAGE_EXTENSIONS | editor.VIDEO_EXTENSIONS:
        raise HTTPException(400, f"unsupported media type: {suffix or 'unknown'}")
    base_stem = safe_folder_name(original.stem, fallback="media")
    stem = base_stem
    counter = 1
    while any(path.stem == stem for path in editor.MEDIA_DIR.iterdir() if path.is_file()):
        stem = f"{base_stem}_{counter}"
        counter += 1
    destination = editor.MEDIA_DIR / f"{stem}{suffix}"

    max_bytes = 2 * 1024 * 1024 * 1024
    written = 0
    try:
        with open(destination, "wb") as output:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(413, "media file exceeds 2 GB")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    asset = editor.media_info(destination)
    if not asset["width"] or not asset["height"]:
        destination.unlink(missing_ok=True)
        raise HTTPException(400, "ffmpeg could not read this image or video")
    return {"ok": True, "asset": asset}


@router.get("/media/{asset_id}/stream")
def stream_media(asset_id: str):
    return FileResponse(str(_resolve_media(asset_id)), headers={"Cache-Control": "no-store"})


@router.get("/media/{asset_id}/thumbnail")
def media_thumbnail(asset_id: str):
    try:
        thumb = editor.media_thumbnail(_resolve_media(asset_id))
    except Exception as exc:
        raise HTTPException(400, f"thumbnail failed: {exc}")
    return FileResponse(str(thumb), headers={"Cache-Control": "no-store"})


@router.post("/compile")
def compile_media(req: CompilationRequest):
    """Render mixed media independently, with optional black sound transitions."""
    if not req.items:
        raise HTTPException(400, "add at least one clip, image, or video")
    if len(req.items) > 100:
        raise HTTPException(400, "a compilation can contain at most 100 items")
    if req.transition_duration < 0 or req.transition_duration > 10:
        raise HTTPException(400, "transition duration must be between 0 and 10 seconds")
    resolved: list[dict[str, Any]] = []
    for item in req.items:
        source_type = item.get("source_type", "clip")
        if source_type == "media":
            source = _resolve_media(str(item.get("media_id", "")))
            kind = editor.media_kind(source)
        else:
            source = _resolve(str(item.get("bucket", "output")), str(item.get("stem", "")))
            kind = "video"
        resolved.append({
            "source": source,
            "kind": kind,
            "spec": item.get("spec") or {},
            "automatic": bool(item.get("automatic", False)),
            "still_duration": item.get("still_duration", 3.0),
        })
    output_stem = safe_folder_name(
        req.output_stem or f"compilation_{time.strftime('%Y%m%d_%H%M%S')}",
        fallback="compilation",
    )
    try:
        out = editor.render_compilation(
            resolved,
            output_stem=output_stem,
            transition_sound=req.transition_sound,
            transition_duration=req.transition_duration,
            transition_type=req.transition_type,
        )
    except Exception as exc:
        raise HTTPException(400, f"compilation failed: {exc}")
    info = editor.probe(out)
    return {"ok": True, "stem": out.stem, "bucket": "edited",
            "path": str(out), "duration": info["duration"]}


@router.post("/suggest-trim")
def suggest_trim(req: TrimSuggestionRequest):
    """Use video understanding to tighten one clip around its final payoff."""
    source = _resolve(req.bucket, req.stem)
    try:
        from modules.compilation import suggest_payoff_trim
        return suggest_payoff_trim(source)
    except Exception as exc:
        raise HTTPException(400, f"trim suggestion failed: {exc}")


@router.delete("/presets/{preset_id}")
def delete_preset(preset_id: str):
    if not editor.delete_custom_preset(preset_id):
        raise HTTPException(404, "custom preset not found")
    return {"ok": True}


@router.get("/{bucket}/{stem}/probe")
def probe(bucket: str, stem: str):
    """Source dimensions/duration/fps so the UI can set up trim + crop boxes."""
    clip = _resolve(bucket, stem)
    return editor.probe(clip)


@router.get("/{bucket}/{stem}/templates")
def templates(bucket: str, stem: str):
    """One-click edit presets (full-cam blur, reaction stack, crop) with boxes
    pre-computed for this clip's dimensions."""
    clip = _resolve(bucket, stem)
    info = editor.probe(clip)
    return {"templates": editor.templates(info["width"], info["height"])}


@router.get("/{bucket}/{stem}/presets")
def custom_presets(bucket: str, stem: str):
    clip = _resolve(bucket, stem)
    info = editor.probe(clip)
    return {"presets": editor.list_custom_presets(info["width"], info["height"])}


@router.post("/{bucket}/{stem}/presets")
def save_preset(bucket: str, stem: str, req: CustomPresetRequest):
    clip = _resolve(bucket, stem)
    info = editor.probe(clip)
    try:
        preset = editor.save_custom_preset(
            req.name, req.spec, info["width"], info["height"]
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    return {"preset": preset}


@router.post("/render-segments")
def render_segments(req: SegmentsRequest):
    """Render a clip whose layout changes mid-way (full-cam <-> reaction)."""
    clip = _resolve(req.bucket, req.stem)
    try:
        out = editor.render_segments(clip, req.segments, output_stem=req.output_stem)
    except Exception as e:
        raise HTTPException(400, f"segment render failed: {e}")
    info = editor.probe(out)
    return {"ok": True, "stem": out.stem, "bucket": "edited",
            "path": str(out), "duration": info["duration"]}


@router.post("/preview")
def preview(req: PreviewRequest):
    """Render a single frame at `at` seconds with the current spec applied.
    Used for live crop/reframe feedback. Returns a JPEG."""
    clip = _resolve(req.bucket, req.stem)
    try:
        frame = editor.render_edit(clip, req.spec, preview_at=req.at)
    except Exception as e:
        raise HTTPException(400, f"preview failed: {e}")
    return FileResponse(str(frame), media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})


@router.post("/render")
def render(req: EditRequest):
    """Apply the full edit spec and write an edited MP4 to output/edited/."""
    clip = _resolve(req.bucket, req.stem)
    try:
        out = editor.render_edit(clip, req.spec)
    except Exception as e:
        raise HTTPException(400, f"render failed: {e}")
    info = editor.probe(out)
    return {"ok": True, "stem": out.stem, "bucket": "edited",
            "path": str(out), "duration": info["duration"]}


@router.post("/auto")
def auto(req: EditRequest):
    """One-shot auto edit (reaction reframe + loudness normalise)."""
    clip = _resolve(req.bucket, req.stem)
    cam = req.spec.get("cam_box")
    content = req.spec.get("content_box")
    try:
        out = editor.auto_edit(clip, cam_box=cam, content_box=content)
    except Exception as e:
        raise HTTPException(400, f"auto-edit failed: {e}")
    return {"ok": True, "stem": out.stem, "bucket": "edited", "path": str(out)}
