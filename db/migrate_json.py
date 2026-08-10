"""Backfill the legacy file-based JSON into the relational tables (Phase 1).

The app has years of clip data in flat JSON. This module imports it into the
SQLAlchemy schema so the relational layer reflects real history, not an empty
shell. It is the bridge between "file-based JSON/MD" and the durable DB.

Mappings (faithful to the current 6-table schema):
- `output/metadata/<vod>_highlights.json` -> `vods` + `clip_candidates`
  (each detected highlight becomes a DETECTED candidate keyed by its clip_id).
- `output/metadata/<vod>_results.json`    -> `clip_versions`
  (each successfully cut clip becomes a raw rendered version, linked back to its
  candidate by clip_id).
- `data/clip_reviews.json`                -> `workflow_events`
  (a human review is an audit action; stored append-only, lossless via payload).
- `output/publish_queue.json`             -> SKIPPED for now. There is no
  publication table in the starter schema (blueprint Phase 6); importing it would
  need `publication_jobs`/`published_posts`. Reported as skipped, not dropped.

Every importer is **idempotent at the row level** (skip-if-exists), so the whole
migration is safe to re-run and only picks up new data. It is driven through
`job_store.run("migrate_json", ...)` so each run is a durable, audited job.

Run:  python -m db.migrate_json
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from config import paths
from db.base import DEFAULT_CREATOR_ID, SessionLocal
from db.repository import (
    ClipCandidateRepo,
    ClipVersionRepo,
    VodRepo,
    WorkflowEventRepo,
    session_scope,
)
from db.state_machine import ClipState

log = logging.getLogger("db.migrate")

REVIEW_ENTITY = "review"


def _load(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _vod_stem(vod_name: str) -> str:
    return Path(vod_name).stem if vod_name else ""


# -----------------------------------------------------------------------------
# Per-file importers (pure: take a live session, return counts — testable)
# -----------------------------------------------------------------------------

def _full_vod_path(vod_name: str, explicit: Optional[str] = None) -> str:
    """Prefer a full on-disk path over the bare filename so previews/renders can
    find the source without re-resolving every time."""
    if explicit:
        return explicit
    try:
        from modules.vod_resolver import resolve_vod_path
        resolved = resolve_vod_path(vod_name)
        if resolved:
            return str(resolved)
    except Exception:  # noqa: BLE001
        pass
    return vod_name


def import_highlights_file(session, path: Path, creator_id: str = DEFAULT_CREATOR_ID,
                           *, vod_path: Optional[str] = None) -> dict:
    data = _load(path)
    vod_name = data.get("vod") or ""
    stem = _vod_stem(vod_name)
    vods = VodRepo(session, creator_id)
    cands = ClipCandidateRepo(session, creator_id)

    # Store a full, resolvable path (upsert updates an existing bare-filename row too).
    vod = vods.upsert_by_stem(stem, path=_full_vod_path(vod_name, vod_path)) if stem else None
    created = skipped = 0
    for h in data.get("highlights", []) or []:
        clip_id = h.get("clip_id")
        if not clip_id:
            skipped += 1
            continue
        if cands.get_by_stem(clip_id) is not None:
            skipped += 1
            continue
        cands.create(
            stem=clip_id,
            vod_id=vod.id if vod is not None else None,
            state=ClipState.DETECTED,
            score=float(h.get("peak_score") or 0.0),
            start=float(h.get("start") or 0.0),
            end=float(h.get("end") or 0.0),
            reason=str(h.get("peak_text") or ""),
            # `triggers` are ephemeral scoring signals (audio_spike, repetition…),
            # NOT content hazards — legacy highlights carry no hazard data.
            hazards=[],
        )
        created += 1
    return {"vod": stem, "created": created, "skipped": skipped}


def import_results_file(session, path: Path, creator_id: str = DEFAULT_CREATOR_ID) -> dict:
    data = _load(path)
    vods = VodRepo(session, creator_id)
    cands = ClipCandidateRepo(session, creator_id)
    versions = ClipVersionRepo(session, creator_id)

    # A cut clip and its source highlight use DIFFERENT id schemes
    # (results: GEN_<slug>, highlights: <vod>_NNN) but share the EXACT start time,
    # so we link a version back to its candidate by (vod, start), not by id.
    vod_stem = _vod_stem(data.get("vod") or "")
    vod = vods.get_by_stem(vod_stem) if vod_stem else None
    by_start: dict[float, Any] = {}
    if vod is not None:
        for cand in cands.for_vod(vod.id):
            by_start[round(float(cand.start), 2)] = cand

    created = skipped = 0
    for c in data.get("clips", []) or []:
        if not c.get("success"):
            skipped += 1
            continue
        stem = c.get("clip_id")  # GEN_<slug> == the output filename stem
        if not stem:
            skipped += 1
            continue
        if versions.list(stem=stem):  # already imported this cut
            skipped += 1
            continue
        candidate = by_start.get(round(float(c.get("start") or 0.0), 2))
        versions.create(
            candidate_id=candidate.id if candidate is not None else None,
            stem=stem,
            kind="raw",
            bucket="output",
            path=str(c.get("output") or ""),
            edit_plan=None,
        )
        created += 1
    return {"vod": vod_stem, "created": created, "skipped": skipped}


def import_reviews(session, path: Path, creator_id: str = DEFAULT_CREATOR_ID) -> dict:
    data = _load(path)
    reviews = data.get("reviews") or {}
    events = WorkflowEventRepo(session, creator_id)

    created = skipped = 0
    for stem, rv in reviews.items():
        if events.for_entity(REVIEW_ENTITY, stem):  # already imported
            skipped += 1
            continue
        verdict = rv.get("verdict")
        events.append(
            entity_type=REVIEW_ENTITY,
            entity_id=stem,
            actor="lazi",
            to_state=verdict,
            reason=f"{verdict or 'review'} rating={rv.get('rating')}",
            payload=rv,
        )
        created += 1
    return {"created": created, "skipped": skipped}


# -----------------------------------------------------------------------------
# Orchestration
# -----------------------------------------------------------------------------

def backfill_vod_paths(*, factory=SessionLocal, creator_id: str = DEFAULT_CREATOR_ID) -> dict:
    """One-time fix: turn existing bare-filename VOD paths into full on-disk paths
    (for candidates imported before the pipeline started storing full paths)."""
    from pathlib import Path as _Path

    from modules.vod_resolver import resolve_vod_path

    fixed = unresolved = 0
    with session_scope(factory) as s:
        for vod in VodRepo(s, creator_id).list():
            if not vod.path or _Path(vod.path).is_file():
                continue  # already a real path
            resolved = resolve_vod_path(vod.path)
            if resolved is not None:
                vod.path = str(resolved)
                fixed += 1
            else:
                unresolved += 1
    log.info("backfill_vod_paths: fixed %d, unresolved %d", fixed, unresolved)
    return {"fixed": fixed, "unresolved": unresolved}


def migrate_all(creator_id: str = DEFAULT_CREATOR_ID, factory=SessionLocal) -> dict:
    """Import every metadata + review file. One transaction per file so partial
    progress survives a mid-run failure and a re-run resumes cleanly."""
    report: dict[str, Any] = {
        "highlights_files": 0,
        "results_files": 0,
        "candidates_created": 0,
        "versions_created": 0,
        "reviews_created": 0,
        "publish_queue": "skipped (no publication table yet — blueprint Phase 6)",
    }

    metadata_dir = paths.METADATA_DIR
    if metadata_dir.exists():
        for p in sorted(metadata_dir.glob("*_highlights.json")):
            with session_scope(factory) as s:
                res = import_highlights_file(s, p, creator_id)
            report["highlights_files"] += 1
            report["candidates_created"] += res["created"]
        # Results after highlights so versions can link to the candidates above.
        for p in sorted(metadata_dir.glob("*_results.json")):
            with session_scope(factory) as s:
                res = import_results_file(s, p, creator_id)
            report["results_files"] += 1
            report["versions_created"] += res["created"]

    reviews_file = paths.CLIP_REVIEWS_FILE
    if reviews_file.exists():
        with session_scope(factory) as s:
            res = import_reviews(s, reviews_file, creator_id)
        report["reviews_created"] = res["created"]

    return report


def run_migration_job(creator_id: str = DEFAULT_CREATOR_ID) -> dict:
    """Run the migration as a durable, audited job (real `job_store.run` usage).

    No idempotency_key: the importers dedup at the row level, so each invocation
    is allowed to run and pick up new data, while leaving a job + WorkflowEvent
    audit trail of every migration pass.
    """
    from db.job_store import job_store

    snap = job_store.run(
        "migrate_json",
        lambda: migrate_all(creator_id),
        payload={"sources": ["output/metadata/*", "data/clip_reviews.json"]},
    )
    return snap


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    from db import init_db

    init_db()
    result = run_migration_job()
    print(json.dumps(result, indent=2, default=str))
