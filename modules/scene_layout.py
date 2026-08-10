"""Camera/scene layout-change detection (Lazarus: "I change cam position and
transition from full to short cam a lot — that needs to be recognised").

Stream scene switches (full cam ↔ small-cam+content) are hard cuts, so ffmpeg's
scene-change score finds them cheaply — no ML needed. `detect_layout_segments`
returns contiguous segments between switches for a clip window, so:
  - the editor can show switch markers and auto-split items at them,
  - reframe/crop can be set PER SEGMENT instead of one layout for the whole clip
    (a clip spanning a switch currently gets the wrong facecam crop for part
    of it),
  - candidates spanning a switch can carry a `layout_switch` flag for review.

Optional classification: when the face detector is available, each segment is
sampled once and labelled by face size — `fullcam` (face dominates the frame),
`smallcam` (small face box, corner cam + content), or `noface`.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("scene_layout")

# Stream layout switches are hard cuts; 0.30 catches them while ignoring normal
# in-scene motion (tested threshold range 0.25-0.4 in ffmpeg docs/practice).
DEFAULT_SCENE_THRESHOLD = 0.30
MIN_SEGMENT_SECONDS = 1.5  # collapse jitter: a "scene" shorter than this merges

_PTS_RE = re.compile(r"pts_time:([0-9.]+)")


def _scene_change_times(source: Path, start: float, end: float,
                        threshold: float) -> list[float]:
    """ffmpeg select=gt(scene,t) → absolute source times of hard scene changes."""
    duration = max(0.1, end - start)
    cmd = [
        "ffmpeg", "-ss", f"{max(0.0, start):.3f}", "-t", f"{duration:.3f}",
        "-i", str(source),
        "-vf", f"select='gt(scene,{threshold})',metadata=print",
        "-an", "-f", "null", "-",
    ]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    text = r.stderr.decode(errors="replace")
    times = [start + float(m) for m in _PTS_RE.findall(text)]
    # de-jitter: drop changes closer than MIN_SEGMENT_SECONDS to the previous one
    out: list[float] = []
    for t in sorted(times):
        if not out or t - out[-1] >= MIN_SEGMENT_SECONDS:
            out.append(t)
    return out


def _classify_segment(source: Path, at_time: float) -> str:
    """Label one segment by face size: fullcam / smallcam / noface. Best-effort —
    any failure returns 'unknown' and never breaks detection."""
    try:
        from modules.face_locator import locate_faces
        faces = locate_faces(source, at_time)
        if not faces:
            return "noface"
        # locate_faces returns largest-first with a precomputed area_ratio.
        return "fullcam" if faces[0]["area_ratio"] >= 0.04 else "smallcam"
    except Exception as exc:  # noqa: BLE001
        log.debug("face classify failed at %.1fs: %s", at_time, exc)
        return "unknown"


def detect_layout_segments(source: str | Path, start: float = 0.0,
                           end: Optional[float] = None, *,
                           threshold: float = DEFAULT_SCENE_THRESHOLD,
                           classify: bool = True,
                           scene_times: Optional[list[float]] = None) -> dict[str, Any]:
    """Segments between camera/scene switches in [start, end].

    Returns {"segments": [{start, end, layout}], "switches": [t, ...]}.
    `scene_times` is injectable for tests (skips ffmpeg).
    """
    src = Path(str(source))
    if end is None:
        from modules.editor import probe
        end = float(probe(src).get("duration") or 0.0)
    if end <= start:
        return {"segments": [], "switches": []}

    times = scene_times if scene_times is not None else _scene_change_times(
        src, float(start), float(end), threshold)
    times = [t for t in times if start < t < end]

    bounds = [float(start)] + times + [float(end)]
    segments = []
    for seg_start, seg_end in zip(bounds, bounds[1:]):
        if seg_end - seg_start < 0.05:
            continue
        seg: dict[str, Any] = {"start": round(seg_start, 3), "end": round(seg_end, 3)}
        if classify:
            seg["layout"] = _classify_segment(src, (seg_start + seg_end) / 2)
        segments.append(seg)

    # Merge neighbours that classified identically (a flash the scene filter
    # caught that wasn't a real layout change).
    merged: list[dict[str, Any]] = []
    for seg in segments:
        if (merged and classify
                and seg.get("layout") == merged[-1].get("layout")
                and seg.get("layout") not in (None, "unknown")):
            merged[-1]["end"] = seg["end"]
        else:
            merged.append(seg)

    return {"segments": merged, "switches": [round(t, 3) for t in times],
            "has_layout_switch": len(merged) > 1}


__all__ = ["detect_layout_segments", "DEFAULT_SCENE_THRESHOLD"]
