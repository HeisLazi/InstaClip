"""Editor V2 project, media-analysis, preview-audio, and render endpoints."""

from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from modules import editor, editor_v2

# Cloud/owner-only extensions are not included in the public edition.
longform_agent = None
youtube_brand = None

router = APIRouter(prefix="/edit/v2", tags=["editor-v2"])


class FromClipRequest(BaseModel):
    bucket: str = "output"
    stem: str
    name: Optional[str] = None


class FromLocalRequest(BaseModel):
    path: str
    name: Optional[str] = None


class ClipAssetRequest(BaseModel):
    bucket: str = "output"
    stem: str


class StoryCutRequest(BaseModel):
    brief: str
    target_minutes: float = 12
    max_sections: int = 12
    title: Optional[str] = None
    generate_captions: bool = True
    stream_type: str = "auto"
    goal: str = ""
    required_events: list[str] = Field(default_factory=list)
    excluded_topics: list[str] = Field(default_factory=list)


class YouTubeBrandKitRequest(BaseModel):
    intro_path: str = ""
    outro_path: str = ""
    prelude_enabled: bool = True
    prelude_count: int = 2
    prelude_clip_seconds: float = 8
    post_credit_mode: str = "auto"
    post_credit_min_score: float = 0.68


def _project(project_id: str) -> dict[str, Any]:
    try:
        return editor_v2.load_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "editor project not found")
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc))


@router.get("/projects")
def projects():
    return {"projects": editor_v2.list_projects()}


@router.get("/youtube-brand-kit")
def youtube_brand_kit():
    raise HTTPException(501, detail="YouTube brand kit is not included in the public edition.")


@router.put("/youtube-brand-kit")
def put_youtube_brand_kit(request: YouTubeBrandKitRequest):
    raise HTTPException(501, detail="YouTube brand kit is not included in the public edition.")


@router.post("/projects/from-clip")
def project_from_clip(request: FromClipRequest):
    try:
        return {"project": editor_v2.create_project_from_clip(request.bucket, request.stem, request.name)}
    except FileNotFoundError:
        raise HTTPException(404, f"clip not found: {request.stem}")
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc))


@router.post("/projects/from-local")
def project_from_local(request: FromLocalRequest):
    # Security (WS1): the path is client-supplied — require it inside the allowed
    # media roots so this can't open arbitrary local files. (Guard added by Claude
    # per productization plan; see utils/path_guard.py.)
    from utils.path_guard import PathNotAllowed, require_media_path
    try:
        safe = require_media_path(request.path, kinds=("video", "audio", "image"))
    except PathNotAllowed as exc:
        status = 404 if "no file at" in str(exc) else 403
        raise HTTPException(status, str(exc))
    try:
        return {"project": editor_v2.create_project_from_local(str(safe), request.name)}
    except FileNotFoundError:
        raise HTTPException(404, f"local video not found: {request.path}")
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc))


@router.get("/projects/{project_id}")
def get_project(project_id: str):
    return {"project": _project(project_id)}


@router.put("/projects/{project_id}")
def put_project(project_id: str, project: dict[str, Any]):
    if project.get("id") != project_id:
        raise HTTPException(400, "project id does not match URL")
    try:
        return {"project": editor_v2.save_project(project)}
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc))


@router.delete("/projects/{project_id}", status_code=204)
def remove_project(project_id: str):
    try:
        editor_v2.delete_project(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "editor project not found")


class TranscriptOpsBody(BaseModel):
    ops: list[dict[str, Any]]
    expected_revision: Optional[int] = None


@router.post("/projects/{project_id}/transcript-ops")
def transcript_ops(project_id: str, body: TranscriptOpsBody):
    """Typed transcript-editing operations (cut_ranges / remove_silences /
    remove_fillers) applied server-side; returns the updated project + a report.
    Contract agreed with the frontend: validated ops, revision-checked, audited —
    never arbitrary project-JSON patching. (Backend by Claude, WS3.2.)"""
    from modules.transcript_ops import TranscriptOpsError, apply_ops

    project = _project(project_id)
    if body.expected_revision is not None and int(project.get("revision", 0)) != body.expected_revision:
        raise HTTPException(409, f"revision conflict: project is at {project.get('revision')}")
    try:
        project, report = apply_ops(project, body.ops)
    except TranscriptOpsError as exc:
        raise HTTPException(400, str(exc))
    saved = editor_v2.save_project(project)
    return {"project": saved, "report": report}


@router.get("/projects/{project_id}/transcript")
def project_transcript(project_id: str):
    """Immutable source transcript for the project's primary asset — segments with
    word-level timing when available: {stem, version, segments:[{text,start,end,
    words:[{text,start,end}]}]}. No local paths are exposed. 404 when no transcript
    exists yet (run the pipeline/transcription first). (Contract for the Transcript
    tab's true word-level editing — Codex 02:46.)"""
    import json as _json

    from config import paths as _paths
    from modules.transcript_ops import TranscriptOpsError, _primary_asset

    project = _project(project_id)
    try:
        _, source = _primary_asset(project)
    except TranscriptOpsError as exc:
        raise HTTPException(400, str(exc))
    stem = source.stem
    tpath = _paths.TRANSCRIPTS_DIR / f"{stem}.json"
    if not tpath.exists():
        raise HTTPException(404, f"no transcript for {stem!r} — transcribe the source first")
    try:
        data = _json.loads(tpath.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(500, f"transcript unreadable: {exc}")

    segments = []
    for seg in data.get("segments") or []:
        segments.append({
            "text": str(seg.get("text") or "").strip(),
            "start": float(seg.get("start") or 0.0),
            "end": float(seg.get("end") or 0.0),
            "words": [
                {"text": str(w.get("word") or "").strip(),
                 "start": float(w.get("start") or 0.0),
                 "end": float(w.get("end") or 0.0)}
                for w in (seg.get("words") or [])
            ],
        })
    return {"stem": stem, "version": int(tpath.stat().st_mtime),
            "has_words": any(s["words"] for s in segments), "segments": segments}


class EpisodeProposeBody(BaseModel):
    vod_stem: str
    content_type: str = "auto"     # auto | reaction | segments | irl
    min_minutes: float = 6.0
    target_minutes: float = 24.0
    max_minutes: float = 35.0
    gap_seconds: float = 25.0
    layout_switches: Optional[list[float]] = None


@router.post("/episodes/propose")
def propose_episodes(body: EpisodeProposeBody):
    """Episode planning is a cloud-extension not included in the public edition."""
    raise HTTPException(501, detail="Episode planning is not included in the public edition.")


class ExtendBody(BaseModel):
    before: float = 0.0
    after: float = 0.0
    expected_revision: Optional[int] = None


@router.post("/projects/{project_id}/extend")
def extend_project(project_id: str, body: ExtendBody):
    """Extend the project's clip beyond its current bounds — widens in-asset when
    there's room, otherwise re-cuts a wider file from the source VOD (clip-room
    clips carry their VOD link). Returns {project, report}. (Backend by Claude.)"""
    from modules.clip_extend import ExtendError, extend_project as _extend

    project = _project(project_id)
    if body.expected_revision is not None and int(project.get("revision", 0)) != body.expected_revision:
        raise HTTPException(409, f"revision conflict: project is at {project.get('revision')}")
    try:
        project, report = _extend(project, body.before, body.after)
    except ExtendError as exc:
        raise HTTPException(400, str(exc))
    saved = editor_v2.save_project(project)
    return {"project": saved, "report": report}


class DetectCamBody(BaseModel):
    source_time: Optional[float] = None   # sample here; default = across first item
    aspect: float = 9 / 16                # for the face-centered crop suggestion


@router.post("/projects/{project_id}/detect-cam")
def detect_cam(project_id: str, body: DetectCamBody):
    """Find the ENROLLED creator's face/cam in the project's source — wherever the
    cam sits that stream (bottom-left, top-right, …). Returns source-pixel boxes
    the UI can apply as item crops: `cam_box` (facecam region, reaction-stack cam)
    and `crop_box` (9:16 crop centered on the face). (Lazarus 2026-07-06.)"""
    from modules.editor import probe
    from modules.face_locator import face_cam_box, face_centered_crop_box, first_faces
    from modules.transcript_ops import TranscriptOpsError, _primary_asset

    project = _project(project_id)
    try:
        _, source = _primary_asset(project)
    except TranscriptOpsError as exc:
        raise HTTPException(400, str(exc))
    if not source.is_file():
        raise HTTPException(404, f"project source media not found: {source.name}")

    info = probe(source)
    w, h = int(info.get("width") or 1920), int(info.get("height") or 1080)
    if body.source_time is not None:
        times = [float(body.source_time)]
    else:
        items = [i for t in project.get("tracks", []) for i in t.get("items", [])]
        s_in = min((float(i.get("sourceIn", 0)) for i in items), default=0.0)
        s_out = max((float(i.get("sourceOut", 0)) for i in items), default=s_in + 8)
        span = max(1.0, s_out - s_in)
        times = [s_in + span * f for f in (0.5, 0.25, 0.75)]

    faces = first_faces(source, times)
    if not faces:
        return {"found": False, "detail": "no face found at the sampled times — "
                "try a moment where the cam is clearly visible (set source_time)"}
    face = faces[0]
    return {
        "found": True,
        "identity": face.get("identity"),
        "identity_score": face.get("identity_score"),
        "face": {k: face[k] for k in ("x", "y", "w", "h", "area_ratio")},
        "cam_box": face_cam_box(source, 0, w, h, faces=faces),
        "crop_box": face_centered_crop_box(source, 0, w, h, aspect=body.aspect, faces=faces),
        "source_size": [w, h],
    }


class LayoutScanBody(BaseModel):
    start: float = 0.0
    end: Optional[float] = None
    threshold: float = 0.30


@router.post("/projects/{project_id}/layout-scan")
def layout_scan(project_id: str, body: LayoutScanBody):
    """Detect camera/scene layout switches (full cam ↔ small cam) in the
    project's primary asset so the UI can show markers, auto-split at switches,
    and reframe per segment. (Backend by Claude — Lazarus: cam switches must be
    recognised.)"""
    from modules.scene_layout import detect_layout_segments
    from modules.transcript_ops import TranscriptOpsError, _primary_asset

    project = _project(project_id)
    try:
        _, source = _primary_asset(project)
    except TranscriptOpsError as exc:
        raise HTTPException(400, str(exc))
    if not source.is_file():
        raise HTTPException(404, f"project source media not found: {source.name}")
    return detect_layout_segments(source, body.start, body.end, threshold=body.threshold)


@router.post("/projects/{project_id}/story-cut")
def create_story_cut(project_id: str, request: StoryCutRequest):
    """Story-cut generation is a cloud-extension not included in the public edition."""
    raise HTTPException(501, detail="Story-cut generation is not included in the public edition.")


@router.post("/projects/{project_id}/assets/clip")
def add_clip_asset(project_id: str, request: ClipAssetRequest):
    project = _project(project_id)
    for asset in project["assets"].values():
        if asset.get("origin") in {"source", "gallery"} and asset.get("bucket") == request.bucket and asset.get("stem") == request.stem:
            return {"asset": asset, "project": project}
    try:
        source = editor_v2.resolve_clip(request.bucket, request.stem)
        asset = editor_v2.asset_from_path(
            project_id, source, origin="gallery", bucket=request.bucket, stem=request.stem,
        )
        editor_v2.add_asset(project, asset)
        return {"asset": asset, "project": project}
    except FileNotFoundError:
        raise HTTPException(404, f"clip not found: {request.stem}")
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc))


@router.post("/projects/{project_id}/assets/media/{media_id}")
def add_media_asset(project_id: str, media_id: str):
    project = _project(project_id)
    for asset in project["assets"].values():
        if asset.get("origin") == "import" and asset.get("mediaId") == media_id:
            return {"asset": asset, "project": project}
    try:
        source = editor_v2.resolve_media(media_id)
        asset = editor_v2.asset_from_path(project_id, source, origin="import", media_id=media_id)
        editor_v2.add_asset(project, asset)
        return {"asset": asset, "project": project}
    except FileNotFoundError:
        raise HTTPException(404, f"imported media not found: {media_id}")
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc))


@router.post("/projects/{project_id}/assets/sound/{sound_name}")
def add_sound_asset(project_id: str, sound_name: str):
    project = _project(project_id)
    for asset in project["assets"].values():
        if asset.get("origin") == "sound-bin" and asset.get("stem") == sound_name:
            return {"asset": asset, "project": project}
    source = editor.sound_path(sound_name)
    if source is None:
        raise HTTPException(404, f"sound not found: {sound_name}")
    try:
        asset = editor_v2.asset_from_path(project_id, source, origin="sound-bin", stem=source.stem)
        editor_v2.add_asset(project, asset)
        return {"asset": asset, "project": project}
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc))


@router.get("/projects/{project_id}/assets/{asset_id}/stream")
def stream_asset(project_id: str, asset_id: str):
    project = _project(project_id)
    try:
        source = editor_v2.resolve_asset(project, asset_id)
        return FileResponse(str(source), headers={"Cache-Control": "no-store"})
    except FileNotFoundError:
        raise HTTPException(404, "asset file not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/projects/{project_id}/assets/{asset_id}/thumbnail")
def asset_thumbnail(
    project_id: str,
    asset_id: str,
    at: Optional[float] = Query(None, ge=0),
    width: int = Query(180, ge=96, le=480),
):
    project = _project(project_id)
    asset = project["assets"].get(asset_id)
    if not asset or asset.get("kind") == "audio":
        raise HTTPException(404, "asset has no thumbnail")
    try:
        source = editor_v2.resolve_asset(project, asset_id)
        thumbnail = (
            editor_v2.timeline_thumbnail_for(source, asset["fingerprint"], at, width)
            if at is not None else editor.media_thumbnail(source)
        )
        return FileResponse(
            str(thumbnail),
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=31536000" if at is not None else "no-store"},
        )
    except Exception as exc:
        raise HTTPException(400, f"thumbnail failed: {exc}")


@router.get("/projects/{project_id}/assets/{asset_id}/waveform")
def asset_waveform(project_id: str, asset_id: str, points: int = Query(1200, ge=32, le=5000)):
    project = _project(project_id)
    asset = project["assets"].get(asset_id)
    if not asset or not asset.get("hasAudio"):
        raise HTTPException(404, "asset has no audio")
    try:
        return editor_v2.waveform_for(
            editor_v2.resolve_asset(project, asset_id), asset["fingerprint"], points,
        )
    except Exception as exc:
        raise HTTPException(400, f"waveform generation failed: {exc}")


@router.get("/projects/{project_id}/assets/{asset_id}/audio-proxy")
def asset_audio_proxy(project_id: str, asset_id: str):
    project = _project(project_id)
    asset = project["assets"].get(asset_id)
    if not asset or not asset.get("hasAudio"):
        raise HTTPException(404, "asset has no audio")
    try:
        proxy = editor_v2.audio_proxy_for(
            editor_v2.resolve_asset(project, asset_id), asset["fingerprint"],
        )
        return FileResponse(str(proxy), media_type="audio/mp4", headers={"Cache-Control": "public, max-age=31536000"})
    except Exception as exc:
        raise HTTPException(400, f"audio proxy failed: {exc}")


@router.get("/projects/{project_id}/assets/{asset_id}/video-proxy")
def asset_video_proxy(project_id: str, asset_id: str):
    project = _project(project_id)
    asset = project["assets"].get(asset_id)
    if not asset or asset.get("kind") != "video":
        raise HTTPException(404, "asset has no video")
    try:
        proxy = editor_v2.video_proxy_for(
            editor_v2.resolve_asset(project, asset_id), asset["fingerprint"],
        )
        return FileResponse(str(proxy), media_type="video/mp4", headers={"Cache-Control": "public, max-age=31536000"})
    except Exception as exc:
        raise HTTPException(400, f"video proxy failed: {exc}")


@router.post("/projects/{project_id}/render")
def render(project_id: str):
    project = _project(project_id)
    try:
        output = editor_v2.render_project(project)
        info = editor.probe(output)
        return {
            "ok": True,
            "stem": output.stem,
            "bucket": "edited",
            "path": str(output),
            "duration": info["duration"],
            "renderedAt": int(time.time() * 1000),
        }
    except Exception as exc:
        raise HTTPException(400, f"Editor V2 render failed: {exc}")
