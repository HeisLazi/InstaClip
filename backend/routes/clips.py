"""Clip gallery: list, move, thumbnails, hover-play streaming."""

from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response

from config import paths
from backend.schemas import ClipInfo, ClipMoveRequest, ClipTagsRequest
from utils.clip_files import find_clip_file, iter_video_files, relative_group, safe_folder_name

log = logging.getLogger("backend.clips")
router = APIRouter(prefix="/clips", tags=["clips"])


_BUCKET_DIRS = {
    "output":    paths.CLIPS_DIR,
    "positives": paths.OLD_CLIPS_DIR,
    "negatives": paths.OUTPUT_DIR / "notclips",
    "edited":    paths.OUTPUT_DIR / "edited",
}


def _bucket_dir(bucket: str) -> Path:
    if bucket not in _BUCKET_DIRS:
        raise HTTPException(400, f"unknown bucket '{bucket}'")
    return _BUCKET_DIRS[bucket]


_GEN_FILENAME = re.compile(r"^GEN_(\d+\.\d+)_")


def _parse_score_from_name(stem: str) -> Optional[float]:
    m = _GEN_FILENAME.match(stem)
    return float(m.group(1)) if m else None


def _safe_vod_folder(vod_name: str) -> str:
    """Strip the .mp4 + sanitize so Windows accepts it as a folder name."""
    return safe_folder_name(vod_name, fallback="unknown_vod")


_metadata_fingerprint: tuple[tuple[str, int, int], ...] = ()
_metadata_cache: dict[str, dict[str, Any]] = {}


def _metadata_index() -> dict[str, dict[str, Any]]:
    """Index cut metadata once per metadata-directory change."""
    global _metadata_fingerprint, _metadata_cache
    files = sorted(paths.METADATA_DIR.glob("*_results.json"))
    fingerprint = tuple(
        (str(path), path.stat().st_mtime_ns, path.stat().st_size)
        for path in files
    )
    if fingerprint == _metadata_fingerprint:
        return _metadata_cache

    index: dict[str, dict[str, Any]] = {}
    for meta_path in sorted(files, key=lambda path: path.stat().st_mtime):
        try:
            with open(meta_path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        source_vod = _safe_vod_folder(
            data.get("vod", "") or meta_path.stem.removesuffix("_results")
        )
        for entry in data.get("clips", []):
            stem = entry.get("clip_id")
            if not stem:
                continue
            index[str(stem)] = {
                **entry,
                "source_vod": source_vod,
                "metadata_mtime": meta_path.stat().st_mtime,
            }
    _metadata_fingerprint = fingerprint
    _metadata_cache = index
    return index


def _metadata_for(stem: str, index: Optional[dict[str, dict[str, Any]]] = None) -> dict[str, Any]:
    metadata = index or _metadata_index()
    if stem in metadata:
        return metadata[stem]
    base = re.sub(r"_\d+$", "", stem)
    return metadata.get(base, {})


def _resolve_clip(bucket: str, stem: str) -> Path:
    root = _bucket_dir(bucket)
    clip = find_clip_file(root, stem)
    if clip is None:
        raise HTTPException(404, f"clip not found: {stem}.mp4")
    return clip


def _clip_info(bucket: str, clip: Path, metadata: dict[str, dict[str, Any]]) -> ClipInfo:
    root = _bucket_dir(bucket)
    entry = _metadata_for(clip.stem, metadata)
    physical_group = relative_group(root, clip)
    source_vod = entry.get("source_vod")
    group = physical_group or source_vod or "unsorted"
    stat = clip.stat()
    duration = entry.get("duration")
    score = entry.get("final_score")
    if score is None:
        score = entry.get("score")
    if score is None:
        score = _parse_score_from_name(clip.stem)
    return ClipInfo(
        stem=clip.stem,
        name=clip.name,
        bucket=bucket,
        size_mb=round(stat.st_size / (1024 * 1024), 2),
        duration_seconds=(
            float(duration)
            if isinstance(duration, (int, float)) and duration > 0
            else None
        ),
        mtime=stat.st_mtime,
        score=float(score) if isinstance(score, (int, float)) else None,
        quality_score=(
            float(entry["quality_score"])
            if isinstance(entry.get("quality_score"), (int, float))
            else None
        ),
        has_thumbnail=(paths.DATA_DIR / "thumbnails" / f"{clip.stem}.jpg").exists(),
        group=str(group),
        source_vod=str(source_vod) if source_vod else None,
        triggers=list(entry.get("triggers") or []),
        hazard_flags=list(entry.get("hazard_flags") or []),
    )


def _find_source_vod(clip_stem: str) -> Optional[str]:
    """Search results.json files for which VOD produced this clip. Returns
    the VOD stem (no extension) or None."""
    source = _metadata_for(clip_stem).get("source_vod")
    return str(source) if source else None


def _mirror_to_keepers(source_file: Path, clip_stem: str) -> Optional[Path]:
    """
    When a clip is labelled Good, also drop it under output/keepers/<vod>/.
    Uses a hard link so we don't double disk usage; falls back to copy if
    the filesystem refuses.
    """
    vod_stem = _find_source_vod(clip_stem) or "unsorted"
    dest_dir = paths.KEEPERS_DIR / vod_stem
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / source_file.name
    if dest.exists():
        return dest
    try:
        # NTFS hard link — zero extra disk, file appears in both places.
        import os as _os
        _os.link(str(source_file), str(dest))
        log.info(f"Keeper linked: {dest}")
    except (OSError, NotImplementedError) as e:
        log.warning(f"hardlink failed for {source_file.name}, copying instead ({e})")
        shutil.copy2(str(source_file), str(dest))
    return dest


@router.get("", response_model=list[ClipInfo])
def list_clips(bucket: str = Query("output", pattern="^(output|positives|negatives|edited)$"),
               limit: int = Query(500, ge=1, le=5000),
               group: Optional[str] = None,
               tag: str = "",
               search: str = "",
               min_duration: Optional[float] = Query(None, ge=0),
               max_duration: Optional[float] = Query(None, ge=0),
               min_score: Optional[float] = Query(None, ge=0, le=1),
               sort_by: str = Query("newest", pattern="^(newest|oldest|duration|score|size|name)$"),
               order: str = Query("desc", pattern="^(asc|desc)$")):
    d = _bucket_dir(bucket)
    if not d.exists():
        return []
    metadata = _metadata_index()
    out = [_clip_info(bucket, clip, metadata) for clip in iter_video_files(d)]

    # Attach sort/folder tags (one store read for the whole gallery).
    try:
        from modules.clip_reviews import tags_index
        tag_map = tags_index()
        for clip in out:
            clip.tags = tag_map.get(clip.stem, [])
    except Exception:
        pass

    query = search.strip().lower()
    if group and group != "all":
        out = [clip for clip in out if clip.group == group]
    if tag and tag.lower() not in ("", "all"):
        want = tag.strip().lower()
        out = [clip for clip in out if want in [t.lower() for t in clip.tags]]
    if query:
        out = [
            clip for clip in out
            if query in clip.stem.lower()
            or query in clip.group.lower()
            or any(query in trigger.lower() for trigger in clip.triggers)
            or any(query in t.lower() for t in clip.tags)
        ]
    if min_duration is not None:
        out = [clip for clip in out if clip.duration_seconds is None or clip.duration_seconds >= min_duration]
    if max_duration is not None:
        out = [clip for clip in out if clip.duration_seconds is not None and clip.duration_seconds <= max_duration]
    if min_score is not None:
        out = [clip for clip in out if clip.score is not None and clip.score >= min_score]

    key_functions = {
        "newest": lambda clip: clip.mtime,
        "oldest": lambda clip: clip.mtime,
        "duration": lambda clip: clip.duration_seconds if clip.duration_seconds is not None else -1,
        "score": lambda clip: clip.score if clip.score is not None else -1,
        "size": lambda clip: clip.size_mb,
        "name": lambda clip: clip.name.lower(),
    }
    reverse = order == "desc"
    if sort_by == "oldest":
        reverse = False
    out.sort(key=key_functions[sort_by], reverse=reverse)
    return out[:limit]


@router.get("/groups")
def clip_groups(bucket: str = Query("output", pattern="^(output|positives|negatives|edited)$")):
    root = _bucket_dir(bucket)
    metadata = _metadata_index()
    records = [_clip_info(bucket, clip, metadata) for clip in iter_video_files(root)]
    reviews = {}
    try:
        from modules.clip_reviews import list_reviews
        reviews = {review.get("stem"): review for review in list_reviews(limit=5000)}
    except Exception:
        pass

    grouped: dict[str, list[ClipInfo]] = {}
    for record in records:
        grouped.setdefault(record.group, []).append(record)
    groups = []
    for group_id, clips in grouped.items():
        durations = [clip.duration_seconds for clip in clips if clip.duration_seconds is not None]
        scores = [clip.score for clip in clips if clip.score is not None]
        groups.append({
            "id": group_id,
            "label": group_id.replace("_", " "),
            "count": len(clips),
            "micro_count": sum(1 for clip in clips if clip.duration_seconds is not None and clip.duration_seconds < 4),
            "reviewed_count": sum(1 for clip in clips if clip.stem in reviews),
            "total_size_mb": round(sum(clip.size_mb for clip in clips), 1),
            "avg_duration": round(sum(durations) / len(durations), 2) if durations else None,
            "best_score": max(scores) if scores else None,
            "newest": max((clip.mtime for clip in clips), default=0),
        })
    groups.sort(key=lambda item: item["newest"], reverse=True)
    return {
        "bucket": bucket,
        "total": len(records),
        "micro_total": sum(group["micro_count"] for group in groups),
        "groups": groups,
    }


_IMPORT_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")
_IMPORT_MAX_BYTES = 2 * 1024 ** 3  # 2 GB


def _save_imported_clip(fileobj, filename: str, bucket: str, group: str = "",
                        tags: Optional[list[str]] = None,
                        max_bytes: int = _IMPORT_MAX_BYTES) -> dict[str, Any]:
    """Stream an uploaded clip into a bucket (optionally under a stream group) and
    tag it. Used by POST /clips/import; factored out so it's testable w/o HTTP."""
    if bucket not in _BUCKET_DIRS:
        raise HTTPException(status_code=400, detail=f"unknown bucket {bucket!r}")
    name = Path(filename or "imported.mp4").name
    if not name.lower().endswith(_IMPORT_EXTS):
        raise HTTPException(status_code=400, detail="only video files can be imported")

    dest_dir = _bucket_dir(bucket)
    if group and group.strip():
        dest_dir = dest_dir / safe_folder_name(group.strip())
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest = dest_dir / name
    if dest.exists():  # auto-suffix, never clobber
        idx = 1
        while (dest_dir / f"{dest.stem}_{idx}{dest.suffix}").exists():
            idx += 1
        dest = dest_dir / f"{dest.stem}_{idx}{dest.suffix}"

    written = 0
    with open(dest, "wb") as out:
        while True:
            chunk = fileobj.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="file too large (>2GB)")
            out.write(chunk)

    tag_list = [t.strip() for t in (tags or []) if t and t.strip()]
    if tag_list:
        from modules.clip_reviews import set_clip_tags
        set_clip_tags(dest.stem, bucket, tag_list)

    return {
        "stem": dest.stem,
        "name": dest.name,
        "bucket": bucket,
        "group": (group.strip() if group and group.strip() else "unsorted"),
        "tags": tag_list,
    }


# WS1 abuse limit: imports are 2GB each — throttle to prevent a runaway local
# caller from exhausting the disk. In-process is fine (single backend process).
_IMPORT_MIN_INTERVAL = 2.0   # seconds between import starts
_import_last_start = 0.0
_import_lock = threading.Lock()


@router.post("/import")
async def import_clip(
    file: UploadFile = File(...),
    bucket: str = Form("positives"),
    group: str = Form(""),
    tags: str = Form(""),
):
    """Import an external clip into a bucket (good/bad/edited), optionally placed
    under a stream group and tagged (e.g. "raw example", "edited example")."""
    global _import_last_start
    with _import_lock:
        now = time.monotonic()
        if now - _import_last_start < _IMPORT_MIN_INTERVAL:
            raise HTTPException(status_code=429, detail="imports are rate-limited — retry in a moment")
        _import_last_start = now
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    return _save_imported_clip(file.file, file.filename or "", bucket, group, tag_list)


@router.get("/tags/taxonomy")
def tags_taxonomy():
    """Predefined good/bad sort tags for the gallery (custom tags also allowed)."""
    from modules.clip_reviews import TAG_TAXONOMY
    return {"taxonomy": TAG_TAXONOMY}


@router.put("/{bucket}/{stem}/tags")
def set_tags(bucket: str, stem: str, req: ClipTagsRequest):
    """Set the sort/folder tags for a clip (stored in the review record)."""
    _resolve_clip(bucket, stem)  # 404 if the clip doesn't exist
    from modules.clip_reviews import set_clip_tags
    record = set_clip_tags(stem, bucket, req.tags)
    return {"stem": stem, "bucket": bucket, "tags": record.get("tags", [])}


@router.post("/move")
def move_clip(req: ClipMoveRequest):
    src_dir = _bucket_dir(req.from_bucket)
    dst_dir = _bucket_dir(req.to_bucket)
    src = _resolve_clip(req.from_bucket, req.stem)
    group = relative_group(src_dir, src) or _metadata_for(req.stem).get("source_vod") or "unsorted"
    destination_folder = dst_dir / Path(str(group))
    destination_folder.mkdir(parents=True, exist_ok=True)
    dst = destination_folder / src.name
    if dst.exists():
        # Auto-suffix to avoid clobbering existing labels.
        idx = 1
        while (destination_folder / f"{src.stem}_{idx}{src.suffix}").exists():
            idx += 1
        dst = destination_folder / f"{src.stem}_{idx}{src.suffix}"
    shutil.move(str(src), str(dst))
    log.info(f"moved {src.name} {req.from_bucket} -> {req.to_bucket}")

    # When promoting a clip to "good", also mirror it into the per-stream
    # keepers folder so the user can grab it for editing later.
    keeper_path: Optional[str] = None
    if req.to_bucket == "positives":
        try:
            mirror = _mirror_to_keepers(dst, req.stem)
            if mirror:
                keeper_path = str(mirror)
        except Exception as e:
            log.warning(f"could not mirror to keepers: {e}")

    # Inverse: if a clip is being demoted out of positives, drop any stale
    # keeper link so the keepers view stays in sync.
    if req.from_bucket == "positives" and req.to_bucket != "positives":
        for keeper in paths.KEEPERS_DIR.rglob(f"{req.stem}.mp4"):
            try:
                keeper.unlink()
                log.info(f"keeper removed: {keeper}")
                # Try to remove empty parent.
                try:
                    keeper.parent.rmdir()
                except OSError:
                    pass
            except OSError:
                pass

    return {
        "ok":          True,
        "moved_to":    str(dst),
        "new_stem":    dst.stem,
        "keeper_path": keeper_path,
    }


@router.get("/{bucket}/{stem}/thumbnail")
def get_thumbnail(bucket: str, stem: str):
    clip = _resolve_clip(bucket, stem)
    from utils.thumbnail_utils import ensure_thumbnail
    thumb = ensure_thumbnail(clip, width=480)
    if not thumb or not thumb.exists():
        raise HTTPException(500, "thumbnail extraction failed")
    return FileResponse(str(thumb), media_type="image/jpeg")


@router.head("/{bucket}/{stem}/video.mp4")
@router.get("/{bucket}/{stem}/video.mp4")
@router.head("/{bucket}/{stem}/video")
@router.get("/{bucket}/{stem}/video")
def get_video(bucket: str, stem: str, request: Request):
    """
    Range-aware video delivery for the gallery / detail-view <video> element.
    Returns whole-file responses with Accept-Ranges header so subsequent
    range requests work, or 206 partial-content for explicit Range headers.
    """
    clip = _resolve_clip(bucket, stem)

    file_size = clip.stat().st_size
    range_header = request.headers.get("range")
    # Explicit codec hint helps some browsers pick the right decoder path.
    # H.264 Main + AAC LC is what our pipeline produces.
    content_type = 'video/mp4; codecs="avc1.4d4029,mp4a.40.2"'
    base_headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-store",
        "Content-Type":  content_type,
        # Permit canvas read-back from the ambient-mode glow extractor.
        "Access-Control-Allow-Origin":  "*",
        "Cross-Origin-Resource-Policy": "cross-origin",
    }

    # No range → whole file. Browsers will then issue range requests as
    # they scrub / play.
    if not range_header:
        return FileResponse(str(clip), media_type=content_type, headers=base_headers)

    # Parse "bytes=START-END". END may be empty (open-ended).
    match = re.match(r"bytes=(\d+)-(\d*)$", range_header.strip())
    if not match:
        raise HTTPException(416, "invalid range")
    start = int(match.group(1))
    end_str = match.group(2)
    end = int(end_str) if end_str else file_size - 1
    end = min(end, file_size - 1)
    if start > end or start >= file_size:
        return Response(status_code=416, headers={
            **base_headers,
            "Content-Range": f"bytes */{file_size}",
        })
    length = end - start + 1

    # Read the slice in one shot. Each request is small (a few hundred KB
    # while playing), so a single read is simpler and avoids any streaming
    # framing quirks that confuse the WebView's media decoder.
    with open(clip, "rb") as f:
        f.seek(start)
        data = f.read(length)

    return Response(
        content=data,
        status_code=206,
        headers={
            **base_headers,
            "Content-Range":   f"bytes {start}-{end}/{file_size}",
            "Content-Length":  str(length),
        },
    )


@router.post("/keepers/backfill")
def keepers_backfill():
    """
    One-shot: walk data/old_clips/ and link anything we can match back to a
    source VOD into output/keepers/<vod>/. Idempotent — skips clips that are
    already linked. Returns how many were linked, skipped, or unmatched.
    """
    linked = 0
    skipped = 0
    unmatched = 0
    for clip in paths.OLD_CLIPS_DIR.rglob("*.mp4"):
        vod_stem = _find_source_vod(clip.stem)
        if not vod_stem:
            unmatched += 1
            continue
        dest_dir = paths.KEEPERS_DIR / vod_stem
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / clip.name
        if dest.exists():
            skipped += 1
            continue
        try:
            import os as _os
            _os.link(str(clip), str(dest))
            linked += 1
        except OSError:
            try:
                shutil.copy2(str(clip), str(dest))
                linked += 1
            except Exception as e:
                log.warning(f"backfill copy failed for {clip.name}: {e}")
    log.info(f"Keepers backfill: linked={linked} skipped={skipped} unmatched={unmatched}")
    return {"linked": linked, "skipped": skipped, "unmatched": unmatched}


@router.get("/keepers/groups")
def keepers_groups():
    """
    List the per-stream keeper folders. Used by the Gallery "By stream" view.
    """
    root = paths.KEEPERS_DIR
    if not root.exists():
        return {"folder": str(root), "groups": []}
    groups = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        clips = sorted(entry.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        groups.append({
            "vod_stem": entry.name,
            "count":    len(clips),
            "folder":   str(entry),
            "clips": [
                {
                    "stem":   c.stem,
                    "name":   c.name,
                    "size_mb": round(c.stat().st_size / (1024 * 1024), 2),
                    "mtime":  c.stat().st_mtime,
                    "score":  _parse_score_from_name(c.stem),
                }
                for c in clips
            ],
        })
    # Most recently touched folder first.
    groups.sort(key=lambda g: -max((c["mtime"] for c in g["clips"]), default=0))
    return {"folder": str(root), "groups": groups}


@router.get("/keepers/{vod_stem}/{stem}/thumbnail")
def keeper_thumbnail(vod_stem: str, stem: str):
    clip = paths.KEEPERS_DIR / vod_stem / f"{stem}.mp4"
    if not clip.exists():
        raise HTTPException(404, "clip not found")
    from utils.thumbnail_utils import ensure_thumbnail
    thumb = ensure_thumbnail(clip, width=480)
    if not thumb or not thumb.exists():
        raise HTTPException(500, "thumbnail extraction failed")
    return FileResponse(str(thumb), media_type="image/jpeg")


@router.head("/keepers/{vod_stem}/{stem}/video.mp4")
@router.get("/keepers/{vod_stem}/{stem}/video.mp4")
@router.head("/keepers/{vod_stem}/{stem}/video")
@router.get("/keepers/{vod_stem}/{stem}/video")
def keeper_video(vod_stem: str, stem: str, request: Request):
    clip = paths.KEEPERS_DIR / vod_stem / f"{stem}.mp4"
    if not clip.exists():
        raise HTTPException(404, "clip not found")
    # Delegate to the existing range-aware response logic by reusing get_video's body.
    return _serve_video(clip, request)


def _serve_video(clip: Path, request: Request) -> Response:
    file_size = clip.stat().st_size
    range_header = request.headers.get("range")
    content_type = 'video/mp4; codecs="avc1.4d4029,mp4a.40.2"'
    base_headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-store",
        "Content-Type":  content_type,
        # Permit canvas read-back from the ambient-mode glow extractor.
        "Access-Control-Allow-Origin":  "*",
        "Cross-Origin-Resource-Policy": "cross-origin",
    }
    if not range_header:
        return FileResponse(str(clip), media_type=content_type, headers=base_headers)
    match = re.match(r"bytes=(\d+)-(\d*)$", range_header.strip())
    if not match:
        raise HTTPException(416, "invalid range")
    start = int(match.group(1))
    end_str = match.group(2)
    end = int(end_str) if end_str else file_size - 1
    end = min(end, file_size - 1)
    if start > end or start >= file_size:
        return Response(status_code=416, headers={
            **base_headers,
            "Content-Range": f"bytes */{file_size}",
        })
    length = end - start + 1
    with open(clip, "rb") as f:
        f.seek(start)
        data = f.read(length)
    return Response(
        content=data,
        status_code=206,
        headers={
            **base_headers,
            "Content-Range":  f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(length),
        },
    )


@router.get("/{bucket}/{stem}/details")
def clip_details(bucket: str, stem: str):
    """
    Rich detail-viewer payload:
      - cached transcript + vision caption text
      - generator (rule-based) score parsed from the filename
      - live quality-classifier probability, if the classifier is trained
      - per-signal trigger breakdown (audio_spike, repetition, …) if the clip
        was produced by the current pipeline and metadata is on disk
    """
    clip = _resolve_clip(bucket, stem)

    txt = paths.CLIP_TRANSCRIPTS_DIR / f"{stem}.txt"
    vis = paths.CLIP_TRANSCRIPTS_DIR / f"{stem}.vision.txt"
    transcript_text   = txt.read_text(encoding="utf-8") if txt.exists() else None
    visual_caption    = vis.read_text(encoding="utf-8") if vis.exists() else None

    # Live classifier prediction (only if model + transcript available).
    quality_prediction: Optional[float] = None
    try:
        from modules.quality_classifier.predictor import model_available, predict_quality
        if model_available() and transcript_text:
            quality_prediction = predict_quality(transcript_text, visual_caption=visual_caption)
    except Exception:
        quality_prediction = None

    # Hunt down the cut-time metadata for this clip (signals + triggers).
    signals: Optional[dict] = None
    triggers: list[str] = []
    peak_text: Optional[str] = None
    hazard_flags: list[str] = []
    entry = _metadata_for(stem)
    triggers = list(entry.get("triggers", []) or [])
    peak_text = entry.get("peak_text")
    hazard_flags = list(entry.get("hazard_flags", []) or [])
    if entry.get("peak_signals"):
        signals = dict(entry["peak_signals"])
        if entry.get("quality_score") is not None:
            signals["quality_score"] = entry["quality_score"]
        if entry.get("final_score") is not None:
            signals["final_score"] = entry["final_score"]
        signals["score"] = entry.get("score", signals.get("score"))

    return {
        "stem":               stem,
        "bucket":             bucket,
        "transcript":         transcript_text,
        "visual_caption":     visual_caption,
        "size_mb":            round(clip.stat().st_size / (1024 * 1024), 2),
        "score":              _parse_score_from_name(stem),
        "quality_prediction": quality_prediction,
        "signals":            signals,
        "triggers":           triggers,
        "peak_text":          peak_text,
        "hazard_flags":       hazard_flags,
        "review":             _get_review(stem),
    }


def _get_review(stem: str) -> Optional[dict]:
    try:
        from modules.clip_reviews import get_review
        return get_review(stem)
    except Exception:
        return None
