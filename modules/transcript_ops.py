"""Transcript-driven editing ops (WS3.2 — "edit the video by editing the text").

Typed, validated operations applied server-side to an Editor V2 project (agreed
contract with Codex: no arbitrary JSON patching from the frontend):

  {"type": "cut_ranges",      "ranges": [{"start": s, "end": e}, ...]}   # SOURCE seconds
  {"type": "remove_silences", "min_gap": 0.8, "pad": 0.15}
  {"type": "remove_fillers",  "words": ["um", "uh", ...], "pad": 0.05}

Each op resolves to source-time cut ranges on the project's primary asset, then
the timeline is rebuilt: items overlapping a cut are split into their kept
pieces and later items ripple left, so the result plays straight through.
Silence detection uses ffmpeg silencedetect (works for any source, no transcript
needed); filler removal uses word timestamps from the VOD transcript when
available. v1 applies to speed==1 items (others are left untouched + reported).
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("transcript_ops")

DEFAULT_FILLERS = ["um", "uh", "uhm", "erm", "like,"]
_SILENCE_RE = re.compile(r"silence_(start|end): ([0-9.]+)")


class TranscriptOpsError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Range helpers (all in SOURCE seconds of the primary asset)
# ---------------------------------------------------------------------------

def _merge_ranges(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for s, e in sorted((float(s), float(e)) for s, e in ranges):
        if e <= s:
            continue
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def _subtract(keep_start: float, keep_end: float,
              cuts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Pieces of [keep_start, keep_end) that survive the cut ranges."""
    pieces = [(keep_start, keep_end)]
    for cs, ce in cuts:
        nxt: list[tuple[float, float]] = []
        for ps, pe in pieces:
            if ce <= ps or cs >= pe:
                nxt.append((ps, pe))
                continue
            if cs > ps:
                nxt.append((ps, cs))
            if ce < pe:
                nxt.append((ce, pe))
        pieces = nxt
    return [(s, e) for s, e in pieces if e - s > 0.04]  # drop sub-frame slivers


# ---------------------------------------------------------------------------
# Silence + filler detection
# ---------------------------------------------------------------------------

def detect_silences(source: Path, *, min_gap: float = 0.8,
                    noise_db: float = -35.0) -> list[tuple[float, float]]:
    """ffmpeg silencedetect → [(start, end)] silence intervals ≥ min_gap."""
    cmd = ["ffmpeg", "-i", str(source), "-af",
           f"silencedetect=noise={noise_db}dB:d={max(0.1, float(min_gap))}",
           "-f", "null", "-"]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    text = r.stderr.decode(errors="replace")
    out: list[tuple[float, float]] = []
    start: Optional[float] = None
    for kind, value in _SILENCE_RE.findall(text):
        if kind == "start":
            start = float(value)
        elif kind == "end" and start is not None:
            out.append((start, float(value)))
            start = None
    return out


def filler_ranges_from_transcript(stem: str, words: list[str],
                                  pad: float = 0.05) -> list[tuple[float, float]]:
    """Word-level filler spans from the VOD transcript, when word timestamps exist."""
    import json
    from config import paths

    tpath = paths.TRANSCRIPTS_DIR / f"{stem}.json"
    if not tpath.exists():
        raise TranscriptOpsError(
            f"no transcript with word timing for {stem!r} — filler removal needs it")
    try:
        data = json.loads(tpath.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TranscriptOpsError(f"unreadable transcript for {stem!r}: {exc}")

    targets = {w.strip().lower().strip(".,!?") for w in words if w.strip()}
    spans: list[tuple[float, float]] = []
    found_words = False
    for seg in data.get("segments") or []:
        for w in seg.get("words") or []:
            found_words = True
            token = str(w.get("word") or "").strip().lower().strip(".,!?")
            if token in targets:
                spans.append((float(w["start"]) - pad, float(w["end"]) + pad))
    if not found_words:
        raise TranscriptOpsError(
            f"transcript for {stem!r} has no word timestamps — filler removal needs them")
    return spans


# ---------------------------------------------------------------------------
# Applying cuts to the project timeline
# ---------------------------------------------------------------------------

def _apply_cuts_to_project(project: dict[str, Any], asset_id: str,
                           cuts: list[tuple[float, float]]) -> dict[str, Any]:
    """Split items of `asset_id` around the cut source-ranges and ripple each
    track left so kept pieces butt together. Returns a report."""
    import uuid

    removed_total = 0.0
    split_items = 0
    skipped: list[str] = []

    for track in project.get("tracks", []):
        items = sorted(track.get("items", []), key=lambda i: float(i.get("timelineStart", 0)))
        rebuilt: list[dict[str, Any]] = []
        shift = 0.0  # accumulated timeline seconds removed on this track
        for item in items:
            start = float(item.get("timelineStart", 0)) - shift
            if item.get("assetId") != asset_id:
                item["timelineStart"] = start
                rebuilt.append(item)
                continue
            if float(item.get("speed", 1) or 1) != 1:
                skipped.append(item.get("id", "?"))  # v1: only speed==1 splits
                item["timelineStart"] = start
                rebuilt.append(item)
                continue
            s_in = float(item.get("sourceIn", 0))
            s_out = float(item.get("sourceOut", 0))
            kept = _subtract(s_in, s_out, cuts)
            if len(kept) == 1 and kept[0] == (s_in, s_out):
                item["timelineStart"] = start
                rebuilt.append(item)
                continue
            split_items += 1
            removed_here = (s_out - s_in) - sum(e - s for s, e in kept)
            cursor = start
            for piece_start, piece_end in kept:
                piece = {**item,
                         "id": f"itm_{uuid.uuid4().hex[:12]}",
                         "timelineStart": cursor,
                         "sourceIn": piece_start,
                         "sourceOut": piece_end}
                rebuilt.append(piece)
                cursor += piece_end - piece_start
            shift += removed_here
            removed_total = max(removed_total, shift)
        track["items"] = rebuilt

    return {"removed_seconds": round(removed_total, 3),
            "items_split": split_items, "skipped_items": skipped}


def _primary_asset(project: dict[str, Any]) -> tuple[str, Path]:
    assets = project.get("assets") or {}
    if not assets:
        raise TranscriptOpsError("project has no assets")
    asset_id, asset = next(iter(assets.items()))
    path = Path(str(asset.get("path") or ""))
    if not asset.get("path") or not path.is_file():
        # Clip/gallery-origin assets don't persist a raw path — use the editor's
        # own resolver (bucket+stem / media id / local-vod aware).
        try:
            from modules.editor_v2 import resolve_asset
            path = Path(str(resolve_asset(project, asset_id)))
        except Exception:  # noqa: BLE001 — callers handle a missing file
            pass
    return asset_id, path


def apply_ops(project: dict[str, Any], ops: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate + apply typed ops. Returns (mutated project, report)."""
    if not isinstance(ops, list) or not ops:
        raise TranscriptOpsError("ops must be a non-empty list")
    asset_id, source = _primary_asset(project)
    stem = Path(str(source)).stem

    cuts: list[tuple[float, float]] = []
    report: dict[str, Any] = {"ops": []}
    for op in ops:
        kind = str(op.get("type") or "")
        if kind == "cut_ranges":
            ranges = op.get("ranges") or []
            if not ranges:
                raise TranscriptOpsError("cut_ranges needs ranges")
            parsed = []
            for r in ranges:
                s, e = float(r.get("start", -1)), float(r.get("end", -1))
                if s < 0 or e <= s:
                    raise TranscriptOpsError(f"invalid range {r!r}")
                parsed.append((s, e))
            cuts.extend(parsed)
            report["ops"].append({"type": kind, "ranges": len(parsed)})
        elif kind == "remove_silences":
            if not source.is_file():
                raise TranscriptOpsError("source media not found for silence detection")
            pad = float(op.get("pad", 0.15))
            sil = detect_silences(source, min_gap=float(op.get("min_gap", 0.8)),
                                  noise_db=float(op.get("noise_db", -35.0)))
            trimmed = [(s + pad, e - pad) for s, e in sil if (e - pad) - (s + pad) > 0.1]
            cuts.extend(trimmed)
            report["ops"].append({"type": kind, "silences": len(trimmed)})
        elif kind == "remove_fillers":
            words = op.get("words") or DEFAULT_FILLERS
            spans = filler_ranges_from_transcript(stem, words, pad=float(op.get("pad", 0.05)))
            cuts.extend(spans)
            report["ops"].append({"type": kind, "fillers": len(spans)})
        else:
            raise TranscriptOpsError(f"unknown op type {kind!r}")

    merged = _merge_ranges(cuts)
    result = _apply_cuts_to_project(project, asset_id, merged)
    report.update(result)
    report["cut_ranges_applied"] = [[round(s, 3), round(e, 3)] for s, e in merged]
    # Bump the revision exactly once per successful mutation — this is what makes
    # the route's expected_revision 409 guard effective against stale clients
    # (Codex V&V finding 2026-07-05: neither apply_ops nor save_project bumped it).
    project["revision"] = int(project.get("revision", 0) or 0) + 1
    project["updatedAt"] = int(__import__("time").time() * 1000)
    return project, report


__all__ = ["apply_ops", "detect_silences", "filler_ranges_from_transcript",
           "TranscriptOpsError", "DEFAULT_FILLERS"]
