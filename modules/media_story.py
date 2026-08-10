"""Cached low-cost media signals for long-form story analysis."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from config import paths

MEDIA_SIGNAL_VERSION = 1
_SCENE_TIME_RE = re.compile(r"pts_time:([0-9.]+)")
_SCENE_SCORE_RE = re.compile(r"lavfi\.scene_score=([0-9.]+)")
_BLACK_RE = re.compile(
    r"black_start:([0-9.]+)\s+black_end:([0-9.]+)\s+black_duration:([0-9.]+)"
)


def _fingerprint(video_path: Path) -> str:
    stat = video_path.stat()
    value = f"{MEDIA_SIGNAL_VERSION}|{video_path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _cache_path(video_path: Path) -> Path:
    return paths.STORY_MEDIA_SIGNALS_DIR / f"{_fingerprint(video_path)}.json"


def _parse_ffmpeg_output(output: str) -> dict[str, Any]:
    scene_cuts: list[dict[str, float]] = []
    pending_time: float | None = None
    for line in output.splitlines():
        time_match = _SCENE_TIME_RE.search(line)
        if time_match:
            pending_time = float(time_match.group(1))
        score_match = _SCENE_SCORE_RE.search(line)
        if score_match and pending_time is not None:
            scene_cuts.append({
                "at": round(pending_time, 3),
                "score": round(float(score_match.group(1)), 4),
            })
            pending_time = None
    black_segments = [
        {
            "start": round(float(match.group(1)), 3),
            "end": round(float(match.group(2)), 3),
            "duration": round(float(match.group(3)), 3),
        }
        for match in _BLACK_RE.finditer(output)
    ]
    return {"sceneCuts": scene_cuts, "blackSegments": black_segments}


def analyze_media_signals(video_path: Path, *, force: bool = False) -> dict[str, Any]:
    """Sample one frame per second and cache major cuts/black-frame ranges."""
    video_path = video_path.expanduser().resolve()
    if not video_path.is_file():
        raise FileNotFoundError(str(video_path))
    cache_path = _cache_path(video_path)
    if cache_path.exists() and not force:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("version") == MEDIA_SIGNAL_VERSION:
                return cached
        except (OSError, json.JSONDecodeError):
            pass

    command = [
        "ffmpeg", "-hide_banner", "-nostdin", "-i", str(video_path),
        "-vf", "fps=1,blackdetect=d=0.3:pix_th=0.10,select='gt(scene,0.18)',metadata=print:file=-",
        "-an", "-f", "null", "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "ffmpeg media analysis failed")[-1200:]
        raise RuntimeError(detail)
    parsed = _parse_ffmpeg_output(f"{result.stdout}\n{result.stderr}")
    payload = {
        "version": MEDIA_SIGNAL_VERSION,
        "source": str(video_path),
        "fingerprint": _fingerprint(video_path),
        **parsed,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(cache_path)
    return payload


def enrich_story_with_media(story_graph: dict[str, Any], signals: dict[str, Any]) -> dict[str, Any]:
    """Attach explainable visual-activity hints to transcript beats in place."""
    scene_cuts = list(signals.get("sceneCuts", []))
    black_segments = list(signals.get("blackSegments", []))
    deictic_terms = {"look", "see", "show", "showing", "watch", "screen", "chat", "here"}
    for beat in story_graph.get("beats", []):
        start = float(beat.get("start") or 0)
        end = float(beat.get("end") or 0)
        duration = max(1.0, end - start)
        cuts = [cut for cut in scene_cuts if start <= float(cut.get("at") or 0) < end]
        blacks = [
            segment for segment in black_segments
            if float(segment.get("end") or 0) > start and float(segment.get("start") or 0) < end
        ]
        words = set(re.findall(r"[a-z0-9']+", str(beat.get("text") or "").lower()))
        activity = min(1.0, len(cuts) / max(1.0, duration / 20.0))
        dependency = "high" if len(words & deictic_terms) >= 2 or activity >= 0.75 else "low"
        beat["visualDependency"] = dependency
        beat["mediaSignals"] = {
            "sceneCuts": len(cuts),
            "strongestSceneScore": round(max((float(cut.get("score") or 0) for cut in cuts), default=0), 4),
            "blackSegments": len(blacks),
            "visualActivity": round(activity, 4),
        }
    story_graph["mediaAnalysis"] = {
        "version": signals.get("version", MEDIA_SIGNAL_VERSION),
        "sceneCutCount": len(scene_cuts),
        "blackSegmentCount": len(black_segments),
        "fingerprint": signals.get("fingerprint", ""),
    }
    return story_graph


__all__ = ["MEDIA_SIGNAL_VERSION", "analyze_media_signals", "enrich_story_with_media"]
