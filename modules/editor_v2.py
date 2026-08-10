"""Persistent multitrack projects and FFmpeg rendering for Editor V2."""

from __future__ import annotations

import array
import hashlib
import json
import math
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from config import paths
from modules import editor
from utils.clip_files import find_clip_file, safe_folder_name

SCHEMA_VERSION = 2
TRANSITION_KINDS = {"fade_black", "fade_white", "mix"}
BUCKET_DIRS = {
    "output": paths.CLIPS_DIR,
    "positives": paths.OLD_CLIPS_DIR,
    "negatives": paths.NOTCLIPS_DIR,
    "edited": editor.EDITED_DIR,
}


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _project_path(project_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", project_id):
        raise ValueError("invalid project id")
    return paths.EDITOR_PROJECTS_DIR / f"{project_id}.json"


def validate_project(project: dict[str, Any]) -> dict[str, Any]:
    if project.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("unsupported editor project schema")
    if not isinstance(project.get("id"), str) or not project["id"]:
        raise ValueError("project id is required")
    if not isinstance(project.get("assets"), dict) or not isinstance(project.get("tracks"), list):
        raise ValueError("project assets and tracks are required")
    for asset in project["assets"].values():
        # Audio-only assets can use MP4/M4A containers; origin is authoritative.
        if asset.get("origin") == "sound-bin":
            asset["kind"] = "audio"
            asset["hasAudio"] = True
    track_ids = {track.get("id") for track in project["tracks"]}
    item_ids: set[str] = set()
    for track in project["tracks"]:
        if track.get("kind") not in {"video", "audio", "caption"}:
            raise ValueError("invalid track kind")
        for item in track.get("items", []):
            if item.get("id") in item_ids:
                raise ValueError(f"duplicate timeline item: {item.get('id')}")
            item_ids.add(item.get("id"))
            if item.get("trackId") not in track_ids or item.get("trackId") != track.get("id"):
                raise ValueError(f"timeline item has invalid track: {item.get('id')}")
            if item.get("assetId") not in project["assets"]:
                raise ValueError(f"timeline item has missing asset: {item.get('id')}")
            if float(item.get("sourceOut", 0)) <= float(item.get("sourceIn", 0)):
                raise ValueError(f"timeline item has invalid source range: {item.get('id')}")
            speed = float(item.get("speed", 1))
            if not 0.25 <= speed <= 4:
                raise ValueError(f"timeline item speed is outside 0.25-4x: {item.get('id')}")
            if track.get("kind") == "caption":
                caption = item.get("caption")
                if not isinstance(caption, dict) or not str(caption.get("text") or "").strip():
                    raise ValueError(f"caption item has no text: {item.get('id')}")
    for transition in project.get("transitions", []):
        if transition.get("kind") not in TRANSITION_KINDS:
            raise ValueError(f"invalid transition kind: {transition.get('kind')}")
        if transition.get("fromItemId") not in item_ids or transition.get("toItemId") not in item_ids:
            raise ValueError("transition references a missing timeline item")
        duration = float(transition.get("duration", 0))
        if not 0.1 <= duration <= 5:
            raise ValueError("transition duration must be between 0.1 and 5 seconds")
    return project


def save_project(project: dict[str, Any]) -> dict[str, Any]:
    validate_project(project)
    destination = _project_path(project["id"])
    if destination.exists():
        try:
            stored = json.loads(destination.read_text(encoding="utf-8"))
            if int(project.get("revision", 0)) < int(stored.get("revision", 0)):
                raise ValueError(
                    f"stale project revision {project.get('revision')}; current revision is {stored.get('revision')}"
                )
        except json.JSONDecodeError:
            pass
    project["updatedAt"] = int(time.time() * 1000)
    _atomic_json(destination, project)
    return project


def load_project(project_id: str) -> dict[str, Any]:
    path = _project_path(project_id)
    if not path.exists():
        raise FileNotFoundError(project_id)
    return validate_project(json.loads(path.read_text(encoding="utf-8")))


def list_projects() -> list[dict[str, Any]]:
    paths.EDITOR_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    projects: list[dict[str, Any]] = []
    for path in paths.EDITOR_PROJECTS_DIR.glob("*.json"):
        try:
            project = load_project(path.stem)
            content_mode = project.get("contentMode")
            if content_mode not in {"short_form", "long_form"}:
                is_long_local = any(asset.get("origin") == "local-vod" for asset in project.get("assets", {}).values()) and project_duration(project) >= 300
                content_mode = "long_form" if is_long_local else "short_form"
            projects.append({
                "id": project["id"],
                "name": project.get("name", "Untitled"),
                "revision": project.get("revision", 0),
                "updatedAt": project.get("updatedAt", 0),
                "duration": project_duration(project),
                "contentMode": content_mode,
                "strategy": project.get("longformPlan", {}).get("strategy"),
                "chapterCount": len(project.get("longformPlan", {}).get("chapters", [])),
                "storyBeatCount": len(project.get("longformPlan", {}).get("storyGraph", {}).get("beats", [])),
                "captionCount": int(project.get("longformPlan", {}).get("captionsGenerated", 0) or 0),
            })
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return sorted(projects, key=lambda item: item["updatedAt"], reverse=True)


def delete_project(project_id: str) -> None:
    path = _project_path(project_id)
    if not path.exists():
        raise FileNotFoundError(project_id)
    path.unlink()


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    payload = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode()
    return hashlib.sha1(payload).hexdigest()


def resolve_clip(bucket: str, stem: str) -> Path:
    root = BUCKET_DIRS.get(bucket)
    if root is None:
        raise ValueError(f"unknown bucket: {bucket}")
    result = find_clip_file(root, stem)
    if result is None:
        raise FileNotFoundError(stem)
    return result


def resolve_media(media_id: str) -> Path:
    if Path(media_id).name != media_id:
        raise ValueError("invalid media id")
    for candidate in editor.MEDIA_DIR.glob(f"{media_id}.*"):
        if candidate.is_file() and editor.media_kind(candidate):
            return candidate
    raise FileNotFoundError(media_id)


def resolve_asset(project: dict[str, Any], asset_id: str) -> Path:
    asset = project.get("assets", {}).get(asset_id)
    if not asset:
        raise FileNotFoundError(asset_id)
    origin = asset.get("origin")
    if origin in {"source", "gallery"}:
        return resolve_clip(asset.get("bucket", "output"), asset.get("stem", ""))
    if origin == "import":
        return resolve_media(asset.get("mediaId", ""))
    if origin == "sound-bin":
        result = editor.sound_path(asset.get("stem") or asset.get("name", ""))
        if result is None:
            raise FileNotFoundError(asset_id)
        return result
    if origin == "local-vod":
        path = Path(str(asset.get("path") or "")).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(asset_id)
        return path
    raise ValueError(f"unsupported asset origin: {origin}")


def _asset_urls(project_id: str, asset_id: str) -> dict[str, str]:
    base = f"http://127.0.0.1:8765/edit/v2/projects/{project_id}/assets/{asset_id}"
    return {
        "streamUrl": f"{base}/stream",
        "thumbnailUrl": f"{base}/thumbnail",
        "audioProxyUrl": f"{base}/audio-proxy",
        "videoProxyUrl": f"{base}/video-proxy",
        "waveformUrl": f"{base}/waveform?points=1200",
    }


def asset_from_path(
    project_id: str,
    source: Path,
    *,
    origin: str,
    bucket: Optional[str] = None,
    stem: Optional[str] = None,
    media_id: Optional[str] = None,
) -> dict[str, Any]:
    info = editor.probe(source)
    kind = "audio" if origin == "sound-bin" else editor.media_kind(source) or "audio"
    asset_id = f"ast_{uuid.uuid4().hex[:12]}"
    asset = {
        "id": asset_id,
        "kind": kind,
        "origin": origin,
        "name": source.name,
        "duration": float(info["duration"]),
        "width": int(info["width"]) or None,
        "height": int(info["height"]) or None,
        "hasAudio": bool(info["has_audio"] or kind == "audio"),
        "fingerprint": _fingerprint(source),
        **_asset_urls(project_id, asset_id),
    }
    if bucket:
        asset["bucket"] = bucket
    if stem:
        asset["stem"] = stem
    if media_id:
        asset["mediaId"] = media_id
    return asset


def _create_project(
    source: Path,
    *,
    name: Optional[str],
    origin: str,
    bucket: Optional[str] = None,
    stem: Optional[str] = None,
    local_path: Optional[str] = None,
    reuse_existing: bool = True,
) -> dict[str, Any]:
    info = editor.probe(source)
    if float(info["duration"]) <= 0:
        raise ValueError("clip duration is 0; ffprobe could not read the source")

    paths.EDITOR_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    if reuse_existing:
        for summary in list_projects():
            try:
                existing = load_project(summary["id"])
                if any(
                    asset.get("origin") == origin
                    and (not bucket or asset.get("bucket") == bucket)
                    and (not stem or asset.get("stem") == stem)
                    and (not local_path or asset.get("path") == local_path)
                    for asset in existing.get("assets", {}).values()
                ):
                    return existing
            except (OSError, ValueError):
                continue

    now = int(time.time() * 1000)
    project_id = f"prj_{uuid.uuid4().hex[:12]}"
    asset = asset_from_path(project_id, source, origin=origin, bucket=bucket, stem=stem)
    if local_path:
        asset["path"] = local_path
    landscape = int(info["width"]) >= int(info["height"]) and int(info["width"]) > 0
    # Canvas follows CONTENT MODE, not source orientation (Lazarus 2026-07-06:
    # short clips were rendering in "yt aspect ratio"). Short-form = 9:16 social
    # canvas even from a landscape VOD (the source letterboxes via fit:contain
    # until reframed); long-form YouTube edits = 16:9.
    long_form = origin == "local-vod" and asset["duration"] >= 300
    canvas_width, canvas_height = (1920, 1080) if long_form else (1080, 1920)
    video_item = {
        "id": f"itm_{uuid.uuid4().hex[:12]}",
        "assetId": asset["id"],
        "trackId": "trk_v1",
        "timelineStart": 0,
        "sourceIn": 0,
        "sourceOut": asset["duration"],
        "speed": 1,
        "linkedGroupId": None,
        "enabled": True,
        "video": {
            "x": 0, "y": 0, "width": canvas_width, "height": canvas_height,
            "rotation": 0, "opacity": 1, "crop": None, "fit": "contain",
        },
        "audio": {
            "volume": 1, "pan": 0, "fadeIn": 0, "fadeOut": 0, "normalize": False,
        } if asset["hasAudio"] else None,
    }
    if video_item["audio"] is None:
        video_item.pop("audio")
    project = {
        "schemaVersion": SCHEMA_VERSION,
        "id": project_id,
        "name": name or stem or source.stem,
        "revision": 1,
        "createdAt": now,
        "updatedAt": now,
        "contentMode": "long_form" if long_form else "short_form",
        "canvas": {"width": canvas_width, "height": canvas_height, "fps": 30, "background": "#000000"},
        "assets": {asset["id"]: asset},
        "tracks": [
            {"id": "trk_v1", "kind": "video", "name": "V1", "order": 0, "muted": False, "solo": False, "locked": False, "hidden": False, "items": [video_item]},
            {"id": "trk_v2", "kind": "video", "name": "V2", "order": 1, "muted": False, "solo": False, "locked": False, "hidden": False, "items": []},
            {"id": "trk_v3", "kind": "video", "name": "V3", "order": 2, "muted": False, "solo": False, "locked": False, "hidden": False, "items": []},
            {"id": "trk_a1", "kind": "audio", "name": "A1", "order": 10, "muted": False, "solo": False, "locked": False, "hidden": False, "items": []},
            {"id": "trk_a2", "kind": "audio", "name": "A2", "order": 11, "muted": False, "solo": False, "locked": False, "hidden": False, "items": []},
            {"id": "trk_a3", "kind": "audio", "name": "A3", "order": 12, "muted": False, "solo": False, "locked": False, "hidden": False, "items": []},
            {"id": "trk_c1", "kind": "caption", "name": "C1", "order": 20, "muted": False, "solo": False, "locked": False, "hidden": False, "items": []},
        ],
        "selection": {"itemIds": [], "focusedTrackId": "trk_v1"},
        "view": {"pixelsPerSecond": 64, "scrollLeft": 0},
        "playhead": 0,
        "inPoint": None,
        "outPoint": None,
        "transitions": [],
        "export": {
            "outputName": f"{stem or source.stem}_edit", "width": canvas_width, "height": canvas_height,
            "fps": 30, "quality": "standard", "range": "full",
        },
    }
    return save_project(project)


def create_project_from_clip(bucket: str, stem: str, name: Optional[str] = None) -> dict[str, Any]:
    return _create_project(
        resolve_clip(bucket, stem), name=name, origin="source", bucket=bucket, stem=stem,
    )


def create_project_from_legacy_spec(spec: dict[str, Any]) -> dict[str, Any]:
    bucket = str(spec.get("bucket") or "output")
    stem = str(spec.get("stem") or "")
    if not stem:
        raise ValueError("legacy spec requires stem")
    project = create_project_from_clip(bucket, stem, name=spec.get("name"))

    video_item = None
    for track in project.get("tracks", []):
        if track.get("kind") == "video" and track.get("items"):
            video_item = track["items"][0]
            break

    if video_item:
        trim = spec.get("trim")
        if isinstance(trim, dict):
            if "start" in trim:
                video_item["sourceIn"] = max(0.0, float(trim["start"]))
            if "end" in trim and float(trim["end"]) > video_item["sourceIn"]:
                video_item["sourceOut"] = float(trim["end"])
        if isinstance(spec.get("crop"), list) and len(spec["crop"]) == 4:
            video_item["video"]["crop"] = spec["crop"]
        if spec.get("fit") in {"contain", "cover", "stretch"}:
            video_item["video"]["fit"] = spec["fit"]
        if spec.get("audio_normalize"):
            if video_item.get("audio"):
                video_item["audio"]["normalize"] = True
        if spec.get("audio_boost_db") is not None:
            boost = float(spec["audio_boost_db"])
            if video_item.get("audio"):
                video_item["audio"]["volume"] = round(10 ** (boost / 20.0), 4)

    sound_fx = spec.get("sound_fx")
    if isinstance(sound_fx, list) and sound_fx:
        audio_track = next((t for t in project["tracks"] if t.get("kind") == "audio"), None)
        if not audio_track:
            audio_track = {"id": "trk_a1", "kind": "audio", "name": "A1", "order": 10, "muted": False, "solo": False, "locked": False, "hidden": False, "items": []}
            project["tracks"].append(audio_track)

        for fx in sound_fx:
            if not isinstance(fx, dict):
                continue
            sound_name = str(fx.get("name") or "")
            if not sound_name:
                continue
            sound_path = editor.sound_path(sound_name)
            if sound_path is None:
                continue
            asset = asset_from_path(project["id"], sound_path, origin="sound-bin", stem=sound_path.stem)
            project["assets"][asset["id"]] = asset
            timeline_start = max(0.0, float(fx.get("at", 0.0)))
            gain = max(0.0, float(fx.get("gain", 1.0)))
            item = {
                "id": f"itm_{uuid.uuid4().hex[:12]}",
                "assetId": asset["id"],
                "trackId": audio_track["id"],
                "timelineStart": timeline_start,
                "sourceIn": 0,
                "sourceOut": asset["duration"],
                "speed": 1,
                "linkedGroupId": None,
                "enabled": True,
                "audio": {"volume": gain, "pan": 0, "fadeIn": 0, "fadeOut": 0, "normalize": False},
            }
            audio_track["items"].append(item)

    return save_project(project)


def create_project_from_local(path: str, name: Optional[str] = None, *, reuse_existing: bool = True) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(path)
    if editor.media_kind(source) != "video":
        raise ValueError("local editor source must be a video file")
    return _create_project(
        source, name=name, origin="local-vod", stem=source.stem, local_path=str(source), reuse_existing=reuse_existing,
    )


def add_asset(project: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
    project["assets"][asset["id"]] = asset
    project["revision"] = int(project.get("revision", 0)) + 1
    save_project(project)
    return asset


def project_duration(project: dict[str, Any]) -> float:
    ends = [
        float(item.get("timelineStart", 0))
        + max(0, float(item.get("sourceOut", 0)) - float(item.get("sourceIn", 0)))
        / max(0.25, float(item.get("speed", 1)))
        for track in project.get("tracks", [])
        for item in track.get("items", [])
        if item.get("enabled", True)
    ]
    return max(ends, default=0.0)


def waveform_for(source: Path, fingerprint: str, points: int) -> dict[str, Any]:
    points = max(32, min(5000, int(points)))
    cache = paths.EDITOR_WAVEFORMS_DIR / f"{fingerprint}_{points}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    duration = max(0.1, float(editor.probe(source)["duration"]))
    sample_rate = max(200, min(4000, math.ceil(points * 8 / duration)))
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "f32le", "pipe:1"],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode(errors="replace")[-500:])
    samples = array.array("f")
    samples.frombytes(result.stdout[: len(result.stdout) - len(result.stdout) % 4])
    per_bin = max(1, math.ceil(len(samples) / points))
    peaks = [max((abs(value) for value in samples[i:i + per_bin]), default=0.0) for i in range(0, len(samples), per_bin)]
    peaks = peaks[:points]
    maximum = max(peaks, default=1.0) or 1.0
    payload = {"duration": duration, "points": len(peaks), "peaks": [round(value / maximum, 4) for value in peaks]}
    _atomic_json(cache, payload)
    return payload


def timeline_thumbnail_for(source: Path, fingerprint: str, at: float, width: int = 180) -> Path:
    """Return a cached source frame for Editor timeline filmstrips."""
    if editor.media_kind(source) == "image":
        return source
    info = editor.probe(source)
    duration = max(0.0, float(info.get("duration") or 0))
    if duration <= 0:
        raise ValueError("asset duration is 0")
    width = max(96, min(480, int(width)))
    quantized = min(max(0.0, round(float(at) * 2) / 2), max(0.0, duration - 0.05))
    cache_dir = paths.DATA_DIR / "editor_timeline_thumbnails"
    cache_dir.mkdir(parents=True, exist_ok=True)
    output = cache_dir / f"{fingerprint}_{int(round(quantized * 2)):08d}_{width}.jpg"
    if output.exists() and output.stat().st_size > 0:
        return output
    temporary = output.with_suffix(".tmp.jpg")
    temporary.unlink(missing_ok=True)
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-ss", f"{quantized:.3f}", "-i", str(source),
            "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", str(temporary),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0 or not temporary.exists() or temporary.stat().st_size == 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"timeline thumbnail failed: {result.stderr.decode(errors='replace')[-300:]}")
    temporary.replace(output)
    return output


def audio_proxy_for(source: Path, fingerprint: str) -> Path:
    paths.EDITOR_AUDIO_PROXIES_DIR.mkdir(parents=True, exist_ok=True)
    output = paths.EDITOR_AUDIO_PROXIES_DIR / f"{fingerprint}.m4a"
    if output.exists() and output.stat().st_size > 0:
        return output
    temporary = output.with_suffix(".tmp.m4a")
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-vn", "-ac", "2", "-ar", "44100", "-c:a", "aac", "-b:a", "192k", str(temporary)],
        capture_output=True,
    )
    if result.returncode != 0 or not temporary.exists():
        temporary.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.decode(errors="replace")[-500:])
    temporary.replace(output)
    return output


def video_proxy_for(source: Path, fingerprint: str) -> Path:
    """Create a seekable review proxy; final rendering always resolves the source."""
    paths.EDITOR_VIDEO_PROXIES_DIR.mkdir(parents=True, exist_ok=True)
    output = paths.EDITOR_VIDEO_PROXIES_DIR / f"{fingerprint}.mp4"
    if output.exists() and output.stat().st_size > 0:
        return output
    temporary = output.with_suffix(".tmp.mp4")
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(source),
            "-vf", "scale='min(1280,iw)':-2", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "30", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
            str(temporary),
        ],
        capture_output=True,
    )
    if result.returncode != 0 or not temporary.exists():
        temporary.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.decode(errors="replace")[-500:])
    temporary.replace(output)
    return output


def _number(value: Any, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


def _atempo(speed: float) -> str:
    values: list[float] = []
    while speed < 0.5:
        values.append(0.5)
        speed /= 0.5
    while speed > 2:
        values.append(2)
        speed /= 2
    values.append(speed)
    return ",".join(f"atempo={value:.6g}" for value in values)


def _safe_color(value: Any, fallback: str) -> str:
    color = str(value or "")
    return color if re.fullmatch(r"#[0-9a-fA-F]{6}", color) else fallback


def _filter_color(value: Any, fallback: str) -> str:
    return "0x" + _safe_color(value, fallback)[1:]


def _drawtext_text(value: Any) -> str:
    text = str(value or "").replace("\\", r"\\").replace("'", "\u2019")
    return text.replace(":", r"\:").replace("\r", "").replace("\n", r"\n")[:2000]


def _drawtext_font(bold: bool) -> str:
    names = ("arialbd.ttf", "arial.ttf") if bold else ("arial.ttf", "arialbd.ttf")
    for name in names:
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            # A drive-root path avoids FFmpeg filter-script colon escaping on Windows.
            return f"/Windows/Fonts/{name}"
    return ""


def build_render_command(
    project: dict[str, Any],
    output: Path,
    resolver: Callable[[dict[str, Any], str], Path] = resolve_asset,
) -> list[str]:
    validate_project(project)
    canvas = project["canvas"]
    export = project.get("export", {})
    width = max(16, int(export.get("width") or canvas.get("width", 1080))) // 2 * 2
    height = max(16, int(export.get("height") or canvas.get("height", 1920))) // 2 * 2
    fps = _number(export.get("fps", 30), 1, 120)
    duration = project_duration(project)
    if duration <= 0:
        raise ValueError("project timeline is empty")
    background = str(canvas.get("background", "#000000"))
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", background):
        background = "#000000"

    tracks = sorted(project["tracks"], key=lambda track: float(track.get("order", 0)))
    transitions = project.get("transitions", [])
    transition_from = {transition["fromItemId"]: transition for transition in transitions}
    transition_to = {transition["toItemId"]: transition for transition in transitions}
    entries: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any], int, bool]] = []
    command = ["ffmpeg", "-y"]
    for track in tracks:
        for item in track.get("items", []):
            if not item.get("enabled", True) or track.get("kind") == "caption":
                continue
            asset = project["assets"][item["assetId"]]
            if asset.get("kind") == "caption":
                continue
            source = resolver(project, item["assetId"])
            if asset.get("kind") == "image":
                command += ["-loop", "1"]
                input_seeked = False
            else:
                source_in = max(0, float(item.get("sourceIn", 0)))
                source_out = max(source_in + 0.001, float(item.get("sourceOut", 0)))
                command += ["-ss", f"{source_in:.6f}", "-t", f"{source_out - source_in:.6f}"]
                input_seeked = True
            command += ["-i", str(source)]
            entries.append((track, item, asset, len(entries), input_seeked))

    filters: list[str] = [f"color=c={background}:s={width}x{height}:r={fps:g}:d={duration:.6f}[base0]"]
    visual_index = 0
    base_label = "base0"
    for track, item, asset, input_index, input_seeked in entries:
        video = item.get("video")
        if track.get("kind") != "video" or track.get("hidden") or not video:
            continue
        source_in = max(0, float(item.get("sourceIn", 0)))
        source_out = max(source_in + 0.001, float(item.get("sourceOut", 0)))
        speed = _number(item.get("speed", 1), 0.25, 4)
        box_w = max(2, int(video.get("width", width)))
        box_h = max(2, int(video.get("height", height)))
        trim_start = 0 if input_seeked else source_in
        trim_end = source_out - source_in if input_seeked else source_out
        chain = f"[{input_index}:v]trim=start={trim_start:.6f}:end={trim_end:.6f},setpts=(PTS-STARTPTS)/{speed:.6f}"
        crop = video.get("crop")
        if isinstance(crop, list) and len(crop) == 4:
            cx, cy, cw, ch = [max(0, int(value)) for value in crop]
            if cw > 1 and ch > 1:
                chain += f",crop={cw}:{ch}:{cx}:{cy}"
        fit = video.get("fit", "contain")
        if fit == "cover":
            chain += f",scale={box_w}:{box_h}:force_original_aspect_ratio=increase,crop={box_w}:{box_h}"
        elif fit == "stretch":
            chain += f",scale={box_w}:{box_h}"
        else:
            chain += f",scale={box_w}:{box_h}:force_original_aspect_ratio=decrease,pad={box_w}:{box_h}:(ow-iw)/2:(oh-ih)/2:color=black@0"
        rotation = float(video.get("rotation", 0))
        if abs(rotation) > 0.01:
            chain += f",rotate={rotation:.4f}*PI/180:c=none:ow=rotw(iw):oh=roth(ih)"
        blur = _number(video.get("blur", 0), 0, 100)
        if blur > 0:
            chain += f",boxblur={blur:.4f}"
        opacity = _number(video.get("opacity", 1), 0, 1)
        timeline_start = max(0, float(item.get("timelineStart", 0)))
        rendered_duration = (source_out - source_in) / speed
        incoming = transition_to.get(item.get("id"))
        outgoing = transition_from.get(item.get("id"))
        for transition, direction in ((incoming, "in"), (outgoing, "out")):
            if not transition or transition.get("kind") == "mix":
                continue
            fade_duration = min(rendered_duration, float(transition["duration"]) / 2)
            color = "white" if transition["kind"] == "fade_white" else "black"
            start = 0 if direction == "in" else max(0, rendered_duration - fade_duration)
            chain += f",fade=t={direction}:st={start:.6f}:d={fade_duration:.6f}:color={color}"
        chain += ",format=rgba"
        for transition, direction in ((incoming, "in"), (outgoing, "out")):
            if not transition or transition.get("kind") != "mix":
                continue
            fade_duration = min(rendered_duration, float(transition["duration"]))
            start = 0 if direction == "in" else max(0, rendered_duration - fade_duration)
            chain += f",fade=t={direction}:st={start:.6f}:d={fade_duration:.6f}:alpha=1"
        chain += f",colorchannelmixer=aa={opacity:.4f},setpts=PTS+{timeline_start:.6f}/TB[v{visual_index}]"
        filters.append(chain)
        next_base = f"base{visual_index + 1}"
        x = int(video.get("x", 0))
        y = int(video.get("y", 0))
        filters.append(f"[{base_label}][v{visual_index}]overlay=x={x}:y={y}:eof_action=pass:repeatlast=0:format=auto[{next_base}]")
        base_label = next_base
        visual_index += 1

    audio_labels: list[str] = []
    has_audio_solo = any(track.get("kind") == "audio" and track.get("solo") for track in tracks)
    for track, item, asset, input_index, input_seeked in entries:
        audio = item.get("audio")
        is_audio_track = track.get("kind") == "audio"
        if not audio or not asset.get("hasAudio") or track.get("muted"):
            continue
        if is_audio_track and has_audio_solo and not track.get("solo"):
            continue
        volume = _number(audio.get("volume", 1), 0, 4)
        if volume <= 0:
            continue
        source_in = max(0, float(item.get("sourceIn", 0)))
        source_out = max(source_in + 0.001, float(item.get("sourceOut", 0)))
        speed = _number(item.get("speed", 1), 0.25, 4)
        rendered_duration = (source_out - source_in) / speed
        label = f"a{len(audio_labels)}"
        trim_start = 0 if input_seeked else source_in
        trim_end = source_out - source_in if input_seeked else source_out
        chain = f"[{input_index}:a]atrim=start={trim_start:.6f}:end={trim_end:.6f},asetpts=PTS-STARTPTS,{_atempo(speed)}"
        if audio.get("normalize"):
            chain += ",loudnorm=I=-14:TP=-1.5:LRA=11"
        chain += f",volume={volume:.5f}"
        fade_in = _number(audio.get("fadeIn", 0), 0, rendered_duration)
        fade_out = _number(audio.get("fadeOut", 0), 0, rendered_duration)
        incoming = transition_to.get(item.get("id"))
        outgoing = transition_from.get(item.get("id"))
        if incoming:
            transition_duration = float(incoming["duration"]) if incoming["kind"] == "mix" else float(incoming["duration"]) / 2
            fade_in = max(fade_in, min(rendered_duration, transition_duration))
        if outgoing:
            transition_duration = float(outgoing["duration"]) if outgoing["kind"] == "mix" else float(outgoing["duration"]) / 2
            fade_out = max(fade_out, min(rendered_duration, transition_duration))
        if fade_in > 0:
            chain += f",afade=t=in:st=0:d={fade_in:.5f}"
        if fade_out > 0:
            chain += f",afade=t=out:st={max(0, rendered_duration - fade_out):.5f}:d={fade_out:.5f}"
        pan = _number(audio.get("pan", 0), -1, 1)
        left = 1 if pan <= 0 else 1 - pan
        right = 1 if pan >= 0 else 1 + pan
        chain += f",pan=stereo|c0={left:.5f}*c0|c1={right:.5f}*c1"
        delay = round(max(0, float(item.get("timelineStart", 0))) * 1000)
        chain += f",adelay={delay}:all=1[{label}]"
        filters.append(chain)
        audio_labels.append(label)

    if audio_labels:
        filters.append("".join(f"[{label}]" for label in audio_labels) + f"amix=inputs={len(audio_labels)}:duration=longest:normalize=0,atrim=0:{duration:.6f}[aout]")
    else:
        filters.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{duration:.6f}[aout]")

    caption_label = base_label
    caption_index = 0
    for track in tracks:
        if track.get("kind") != "caption" or track.get("hidden"):
            continue
        for item in track.get("items", []):
            caption = item.get("caption")
            if not item.get("enabled", True) or not isinstance(caption, dict):
                continue
            start = max(0, float(item.get("timelineStart", 0)))
            end = start + max(0.001, (float(item.get("sourceOut", 0)) - float(item.get("sourceIn", 0))) / max(0.25, float(item.get("speed", 1))))
            font_size = int(_number(caption.get("fontSize", 64), 12, 240) * height / max(1, int(canvas.get("height", height))))
            position = caption.get("position", "bottom")
            y = "h*0.08" if position == "top" else "(h-text_h)/2" if position == "center" else "h-text_h-h*0.08"
            variant = caption.get("variant", "subtitle")
            x = "w*0.06" if variant == "lower_third" else "(w-text_w)/2"
            opacity = _number(caption.get("backgroundOpacity", 0.65), 0, 1)
            font_file = _drawtext_font(bool(caption.get("bold", True)))
            font_option = f":fontfile='{font_file}'" if font_file else ""
            next_label = f"caption{caption_index}"
            animation = ""
            if caption.get("animation") == "fade" and end - start >= 0.4:
                fade = min(0.35, (end - start) / 3)
                animation = (
                    f":alpha='if(lt(t\\,{start + fade:.6f})\\,(t-{start:.6f})/{fade:.6f}"
                    f"\\,if(gt(t\\,{end - fade:.6f})\\,({end:.6f}-t)/{fade:.6f}\\,1))'"
                )
            filters.append(
                f"[{caption_label}]drawtext=text='{_drawtext_text(caption.get('text'))}'"
                f"{font_option}:expansion=none:fontsize={max(12, font_size)}:fontcolor={_filter_color(caption.get('color'), '#ffffff')}"
                f":borderw={int(_number(caption.get('strokeWidth', 3), 0, 12))}"
                f":bordercolor={_filter_color(caption.get('strokeColor'), '#000000')}"
                f":box=1:boxcolor={_filter_color(caption.get('backgroundColor'), '#000000')}@{opacity:.3f}"
                f":boxborderw={max(4, int(font_size * 0.18))}:x={x}:y={y}{animation}"
                f":enable=between(t\\,{start:.6f}\\,{end:.6f}),null[{next_label}]"
            )
            caption_label = next_label
            caption_index += 1

    filters.append(f"[{caption_label}]format=yuv420p[vout]")
    quality = export.get("quality", "standard")
    crf = {"draft": "27", "standard": "21", "high": "17"}.get(quality, "21")
    preset = {"draft": "veryfast", "standard": "fast", "high": "slow"}.get(quality, "fast")
    command += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]"]
    if export.get("range") == "in-out" and project.get("inPoint") is not None and project.get("outPoint") is not None:
        start = max(0, float(project["inPoint"]))
        end = min(duration, max(start + 0.001, float(project["outPoint"])))
        command += ["-ss", f"{start:.6f}", "-t", f"{end - start:.6f}"]
    else:
        command += ["-t", f"{duration:.6f}"]
    command += ["-r", f"{fps:g}", "-c:v", "libx264", "-preset", preset, "-crf", crf, "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output)]
    return command


def render_project(project: dict[str, Any]) -> Path:
    editor.EDITED_DIR.mkdir(parents=True, exist_ok=True)
    raw_name = str(project.get("export", {}).get("outputName") or project.get("name") or "editor_v2")
    if raw_name.lower().endswith(".mp4"):
        raw_name = raw_name[:-4]
    stem = safe_folder_name(raw_name.replace(".", "_"), fallback="editor_v2")
    output = editor.EDITED_DIR / f"{stem}.mp4"
    output.unlink(missing_ok=True)
    command = build_render_command(project, output)
    filter_script: Optional[Path] = None
    if "-filter_complex" in command:
        filter_index = command.index("-filter_complex")
        filter_script = output.with_suffix(".filters.txt")
        filter_script.write_text(command[filter_index + 1], encoding="utf-8")
        command[filter_index:filter_index + 2] = ["-filter_complex_script", str(filter_script)]
    try:
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    finally:
        if filter_script is not None:
            filter_script.unlink(missing_ok=True)
    if result.returncode != 0 or not output.exists() or output.stat().st_size == 0:
        raise RuntimeError(result.stderr.decode(errors="replace")[-1200:])
    return output
