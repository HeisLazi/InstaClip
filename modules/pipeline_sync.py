"""Bridge the live pipeline into the relational Clip Room (blueprint Phase 2).

After a VOD runs through the pipeline it has written
`output/metadata/<vod>_highlights.json` (detected moments) and
`<vod>_results.json` (what got cut). This module ingests those into the database
as `ClipCandidate` / `ClipVersion` rows and **auto-promotes the top-N** candidates
(DETECTED -> CANDIDATE) so they're queued for the Discord Clip Room to send.

It reuses the exact same importers as the one-off JSON->DB migration
(`db.migrate_json`), so a freshly-run VOD lands in the DB identically to a
back-filled one — and re-running is idempotent (importers skip existing rows).

Called from `main.run_pipeline` after the cutter; failures are non-fatal (the
file-based pipeline keeps working even if the DB sync hiccups).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from config import paths
from db.base import DEFAULT_CREATOR_ID, SessionLocal
from db.migrate_json import import_highlights_file, import_results_file
from db.repository import ClipCandidateRepo, VodRepo, session_scope
from db.state_machine import ClipState, InvalidTransition
from modules.candidate_budget import DEFAULT_AUTO_CUT_TOP

log = logging.getLogger("pipeline_sync")

DEFAULT_AUTO_PROMOTE_TOP = DEFAULT_AUTO_CUT_TOP


def _auto_promote(vod_stem: str, top_n: int, factory, creator_id: str) -> list[str]:
    """Promote the top-N highest-scoring DETECTED candidates for this VOD to
    CANDIDATE (the bot sends CANDIDATE clips to #clips). Returns the ids actually
    promoted, in rank order (best first)."""
    if top_n <= 0:
        return []
    with session_scope(factory) as s:
        vod = VodRepo(s, creator_id).get_by_stem(vod_stem)
        if vod is None:
            return []
        # The Director reads the creator's Clip DNA (blueprint Phase 3) and ranks by
        # a memory-adjusted score, not the raw detector score — so repeat/filler
        # "non-moments" (Lazarus's NULL rule) sink below real moments. Take the
        # top-N, promote only those still DETECTED. Idempotent: once the top-N are
        # promoted, a re-run promotes nobody (instead of dragging in the next tier).
        from modules.director import rank_candidates
        candidates = ClipCandidateRepo(s, creator_id).for_vod(vod.id)
        judged = rank_candidates(candidates, factory=factory, creator_id=creator_id)
        top_ids = [c.id for c, _ in judged[:top_n] if c.state == ClipState.DETECTED]

    from modules.clip_room import ClipRoom
    room = ClipRoom(session_factory=factory, creator_id=creator_id)
    promoted_ids: list[str] = []
    for cid in top_ids:
        try:
            room.promote(cid, actor="pipeline")
            promoted_ids.append(cid)
        except InvalidTransition:
            pass  # already advanced by someone else — fine
    return promoted_ids


def sync_vod(
    vod_name: str,
    *,
    vod_path: Optional[str] = None,
    auto_promote_top: int = DEFAULT_AUTO_PROMOTE_TOP,
    judge_top: int = 0,
    metadata_dir: Optional[Path] = None,
    factory=SessionLocal,
    creator_id: str = DEFAULT_CREATOR_ID,
) -> dict[str, Any]:
    """Ingest one VOD's pipeline output into the DB + auto-promote top-N.

    `judge_top > 0` runs the LLM taste judge on that many of the promoted
    candidates (the ones that reach Discord) and records a verdict on each. It's
    off by default so tests never make network calls; the live pipeline turns it on.

    Idempotent: safe to call again for the same VOD (only new rows are added).
    """
    md = metadata_dir or paths.METADATA_DIR
    stem = Path(vod_name).stem
    report = {"vod": stem, "candidates": 0, "versions": 0, "promoted": 0}

    highlights = md / f"{stem}_highlights.json"
    results = md / f"{stem}_results.json"

    if highlights.exists():
        with session_scope(factory) as s:
            report["candidates"] = import_highlights_file(
                s, highlights, creator_id, vod_path=vod_path
            )["created"]
    else:
        log.warning("no highlights file for %s — nothing to sync", stem)
        return report

    if results.exists():
        with session_scope(factory) as s:
            report["versions"] = import_results_file(s, results, creator_id)["created"]

    promoted_ids = _auto_promote(stem, auto_promote_top, factory, creator_id)
    report["promoted"] = len(promoted_ids)

    # LLM taste judge on the promoted top-N (the clips that reach Discord). Non-fatal:
    # no API key / network hiccup just means no verdicts, never a broken sync.
    if judge_top > 0 and promoted_ids:
        try:
            from modules.director import judge_and_record
            report["judged"] = judge_and_record(
                promoted_ids[:judge_top], factory=factory, creator_id=creator_id
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("LLM taste judge skipped for %s: %s", stem, exc)

    log.info(
        "synced %s -> +%d candidates, +%d versions, %d promoted to CANDIDATE",
        stem, report["candidates"], report["versions"], report["promoted"],
    )
    return report


__all__ = ["sync_vod", "DEFAULT_AUTO_PROMOTE_TOP"]
