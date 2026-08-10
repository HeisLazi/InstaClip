"""Extend an Editor V2 project's clip beyond its current bounds (Lazarus
2026-07-06: "the ability to extend clips in editor").

Two cases:
  - The project's asset IS the source VOD (episode projects): just widen the
    first/last items' source window within the VOD.
  - The asset is a rendered CLIP FILE: the file physically ends at its bounds, so
    we find the source VOD + the clip's window (clip-room candidate by stem),
    re-cut a WIDER file, swap the asset, and remap item source times.

Endpoint contract: POST /edit/v2/projects/{id}/extend {before, after} →
{project, report}. Ripple-safe: when the head grows, item source times shift by
the added amount so everything still lines up.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("clip_extend")


class ExtendError(ValueError):
    pass


def _candidate_for_stem(session, creator_id, stem: str):
    """Resolve the ClipCandidate for a stem, tolerating BOTH naming schemes.

    AI-cut clip FILES are named `GEN_<score>_<slug>` while the candidate's `stem`
    is `<vod>_NNN` — so a direct `get_by_stem` misses every auto-generated clip
    (the reported "source VOD isn't linked" bug). But the rendered file IS
    recorded as a `ClipVersion` (path/stem = the GEN file) that points back at its
    candidate, so we resolve through the version first, then fall back to the
    candidate stem for episode/manual projects that carry it directly.
    """
    from sqlalchemy import select

    from db.models import ClipVersion
    from db.repository import ClipCandidateRepo, ClipVersionRepo

    direct = ClipCandidateRepo(session, creator_id).get_by_stem(stem)
    if direct is not None:
        return direct

    vrepo = ClipVersionRepo(session, creator_id)
    version = session.scalar(vrepo._select().where(ClipVersion.stem == stem))
    if version is None:
        # The asset stem may be the file basename while the version stored a full
        # path — match on the path's basename too.
        for v in vrepo.list():
            if v.path and Path(v.path).stem == stem:
                version = v
                break
    if version is not None and version.candidate_id:
        return ClipCandidateRepo(session, creator_id).get(version.candidate_id)
    return None


def _vod_for_stem(stem: str) -> Optional[tuple[Path, float, float]]:
    """(vod_path, clip_start, clip_end) for a clip stem via the clip-room DB."""
    try:
        from db.base import DEFAULT_CREATOR_ID, SessionLocal
        from db.repository import VodRepo, session_scope
        from modules.vod_resolver import resolve_vod_path
        with session_scope(SessionLocal) as s:
            cand = _candidate_for_stem(s, DEFAULT_CREATOR_ID, stem)
            if cand is None or not cand.vod_id:
                return None
            vod = VodRepo(s, DEFAULT_CREATOR_ID).get(cand.vod_id)
            if vod is None or not vod.path:
                return None
            resolved = resolve_vod_path(vod.path)
            if resolved is None:
                return None
            return Path(resolved), float(cand.start or 0.0), float(cand.end or 0.0)
    except Exception as exc:  # noqa: BLE001
        log.warning("vod lookup for %s failed: %s", stem, exc)
        return None


def _recut_wider(vod: Path, start: float, end: float, stem: str) -> Path:
    """Cut [start, end] of the VOD into editor media; returns the new file."""
    from modules.cutter.cutter import cut_clip
    from modules.editor import MEDIA_DIR
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    out = MEDIA_DIR / f"{stem}_ext_{uuid.uuid4().hex[:6]}.mp4"
    ok = cut_clip(vod_path=vod, start=start, end=end, output_path=out)
    if not ok or not out.is_file():
        raise ExtendError("re-cut from the source VOD failed")
    return out


def extend_project(project: dict[str, Any], before: float, after: float) -> tuple[dict[str, Any], dict[str, Any]]:
    """Widen the project's primary-asset window by `before`/`after` seconds.
    Mutates + returns (project, report). Raises ExtendError when impossible."""
    before = max(0.0, float(before))
    after = max(0.0, float(after))
    if before == 0 and after == 0:
        raise ExtendError("nothing to extend — give before and/or after seconds")

    assets = project.get("assets") or {}
    if not assets:
        raise ExtendError("project has no assets")
    asset_id, asset = next(iter(assets.items()))
    duration = float(asset.get("duration") or 0.0)
    items = [i for t in project.get("tracks", []) for i in t.get("items", [])
             if i.get("assetId") == asset_id]
    if not items:
        raise ExtendError("no timeline items use the primary asset")
    head = min(items, key=lambda i: float(i.get("sourceIn", 0)))
    tail = max(items, key=lambda i: float(i.get("sourceOut", 0)))

    origin = str(asset.get("origin") or "")
    # Clip/gallery assets don't persist a raw `path` (they resolve via bucket+stem),
    # so prefer the asset's `stem` field; fall back to the path basename for
    # local-vod/import assets that do carry a path.
    stem = str(asset.get("stem") or "") or Path(str(asset.get("path") or "")).stem
    report: dict[str, Any] = {"requested": {"before": before, "after": after}}

    head_room = float(head.get("sourceIn", 0))
    tail_room = duration - float(tail.get("sourceOut", 0))

    fits_in_asset = head_room >= before and tail_room >= after
    vod_link = None if (origin == "local-vod" or fits_in_asset) else _vod_for_stem(stem)

    if origin == "local-vod" or fits_in_asset or (
            vod_link is None and (head_room > 0 or tail_room > 0)):
        # Widen inside the current asset — fully when there's room, partially as
        # a graceful fallback when the source VOD isn't linked.
        got_before = min(before, head_room)
        got_after = min(after, tail_room)
        head["sourceIn"] = float(head["sourceIn"]) - got_before
        head["timelineStart"] = max(0.0, float(head.get("timelineStart", 0)) - got_before)
        tail["sourceOut"] = min(duration, float(tail["sourceOut"]) + got_after)
        report.update({"mode": "widened_in_asset",
                       "granted": {"before": round(got_before, 3), "after": round(got_after, 3)}})
    else:
        # Clip file too small — go back to the source VOD and re-cut wider.
        if vod_link is None:
            raise ExtendError(
                "this clip's source VOD isn't linked — extend needs the original "
                "stream file (clip-room clips have it; imported files may not)")
        vod, clip_start, clip_end = vod_link
        from modules.editor import probe
        vod_dur = float(probe(vod).get("duration") or 0.0) or (clip_end + after)
        new_start = max(0.0, clip_start - before)
        new_end = min(vod_dur, clip_end + after)
        got_before = clip_start - new_start
        got_after = new_end - clip_end
        new_file = _recut_wider(vod, new_start, new_end, stem)
        info = probe(new_file)

        # Repoint the asset at the wider file. It lives in editor_media, so switch
        # the asset to an `import` origin (resolve_asset globs MEDIA_DIR by mediaId)
        # — otherwise resolve_clip(bucket, stem) would keep serving the OLD narrow
        # clip and the extend would render nothing new.
        asset["origin"] = "import"
        asset["mediaId"] = new_file.stem
        asset["path"] = str(new_file)
        asset["name"] = new_file.name
        asset.pop("bucket", None)
        asset["duration"] = float(info.get("duration") or (new_end - new_start))
        # Old file time t == new file time t + got_before: remap every item.
        for item in items:
            item["sourceIn"] = float(item.get("sourceIn", 0)) + got_before
            item["sourceOut"] = float(item.get("sourceOut", 0)) + got_before
        head["sourceIn"] = max(0.0, float(head["sourceIn"]) - got_before)
        head["timelineStart"] = max(0.0, float(head.get("timelineStart", 0)) - got_before)
        tail["sourceOut"] = min(asset["duration"], float(tail["sourceOut"]) + got_after)
        report.update({"mode": "recut_from_vod",
                       "granted": {"before": round(got_before, 3), "after": round(got_after, 3)},
                       "new_source_window": [round(new_start, 3), round(new_end, 3)]})

    project["revision"] = int(project.get("revision", 0) or 0) + 1
    return project, report


__all__ = ["extend_project", "ExtendError"]
