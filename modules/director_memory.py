"""Director Memory — the persistent, structured knowledge the Content Director
(CPT Shanyok) reads so its decisions reflect the creator over time (blueprint
Phase 3).

Layers (blueprint): brand, clip_dna, audience, operational, performance.
Every entry records provenance (`source`) and is visible/editable/deletable by the
creator (non-negotiable rule #6). The chat co-pilot injects `context_block()` into
its prompt, so what the Director "knows" is exactly what's stored here.

`derive_clip_dna_from_reviews()` seeds the Clip DNA layer from the real review
signals (which already encode the boundary≠negative taste), so the memory starts
grounded in the creator's actual decisions rather than empty.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from db.base import DEFAULT_CREATOR_ID, SessionLocal
from db.repository import MemoryRepo, session_scope

log = logging.getLogger("director_memory")

LAYERS = ("brand", "clip_dna", "audience", "operational", "performance")


def _entry_dict(e) -> dict[str, Any]:
    return {
        "id": e.id,
        "layer": e.layer,
        "key": e.key,
        "value": e.value,
        "source": e.source,
        "confidence": e.confidence,
        "pinned": e.pinned,
        "updated_at": e.updated_at,
    }


def remember(layer: str, key: str, value: str, *, source: str = "manual",
             confidence: float = 1.0, pinned: bool = False,
             factory=SessionLocal, creator_id: str = DEFAULT_CREATOR_ID) -> dict[str, Any]:
    """Upsert a fact into a memory layer (by layer+key)."""
    if layer not in LAYERS:
        raise ValueError(f"unknown memory layer {layer!r} (expected one of {LAYERS})")
    with session_scope(factory) as s:
        e = MemoryRepo(s, creator_id).upsert(
            layer, key, value=value, source=source, confidence=confidence, pinned=pinned,
        )
        return _entry_dict(e)


def recall(layer: Optional[str] = None, *, limit: Optional[int] = None,
           factory=SessionLocal, creator_id: str = DEFAULT_CREATOR_ID) -> list[dict[str, Any]]:
    with session_scope(factory) as s:
        repo = MemoryRepo(s, creator_id)
        entries = repo.by_layer(layer, limit=limit) if layer else repo.list(limit=limit)
        return [_entry_dict(e) for e in entries]


def forget(entry_id: str, *, factory=SessionLocal, creator_id: str = DEFAULT_CREATOR_ID) -> bool:
    with session_scope(factory) as s:
        repo = MemoryRepo(s, creator_id)
        e = repo.get(entry_id)
        if e is None:
            return False
        repo.delete(e)
        return True


def context_block(*, max_chars: int = 4000, factory=SessionLocal,
                  creator_id: str = DEFAULT_CREATOR_ID) -> str:
    """A compact memory digest for the Director's system prompt. Pinned entries
    first, then by layer; truncated to max_chars."""
    entries = recall(factory=factory, creator_id=creator_id)
    if not entries:
        return ""
    entries.sort(key=lambda e: (not e["pinned"], e["layer"], e["key"]))
    lines = ["What you know about this creator (Director memory):"]
    current_layer = None
    for e in entries:
        if e["layer"] != current_layer:
            current_layer = e["layer"]
            lines.append(f"\n[{current_layer.upper()}]")
        lines.append(f"- {e['key']}: {e['value']}")
    block = "\n".join(lines)
    return block[:max_chars]


def _is_null_review(review: dict[str, Any]) -> bool:
    """Lazarus's rule: a bad/miss verdict with no written reason (no tags, reasons,
    or notes) is NULL — a duplicate, a non-postable moment, or not even a clip — not
    a taste-miss. It must not count as negative evidence."""
    verdict = str(review.get("verdict") or "").strip().lower()
    if verdict not in ("miss", "bad"):
        return False
    has_reason = bool(
        (review.get("tags") or [])
        or (review.get("reasons") or [])
        or str(review.get("notes") or "").strip()
    )
    return not has_reason


_BOUNDARY_END_KW = ("end", "ending", "finish", "payoff", "lands", "land", "last",
                    "before the good", "cut out", "cut off", "complete", "word")
_BOUNDARY_START_KW = ("begin", "beginning", "start", "before this", "intro",
                      "context", "the part where", "setup")
_BOUNDARY_LONGER_KW = ("longer", "extend", "expand", "more time", "more to",
                       "a bit more", "few more", "too short", "needs more")


def _boundary_direction(reviews: list[dict[str, Any]]) -> dict[str, int]:
    """Mine the boundary-review notes for WHICH edge fails: the end (payoff cut),
    the start (missing setup/context), or just 'make it longer'. This turns the
    generic 'boundaries are #1' into an actionable, directional rule."""
    try:
        from modules.clip_reviews import classify_review_signal
    except Exception:  # noqa: BLE001
        return {"total": 0, "end": 0, "start": 0, "longer": 0}
    counts = {"total": 0, "end": 0, "start": 0, "longer": 0}
    for r in reviews:
        if classify_review_signal(r) != "boundary":
            continue
        counts["total"] += 1
        note = str(r.get("notes") or "").lower()
        if any(k in note for k in _BOUNDARY_END_KW):
            counts["end"] += 1
        if any(k in note for k in _BOUNDARY_START_KW):
            counts["start"] += 1
        if any(k in note for k in _BOUNDARY_LONGER_KW):
            counts["longer"] += 1
    return counts


def derive_clip_dna_from_reviews(*, factory=SessionLocal,
                                 creator_id: str = DEFAULT_CREATOR_ID) -> dict[str, Any]:
    """Seed the clip_dna layer from real review signals so memory starts grounded
    in the creator's actual keep/miss/boundary decisions. Idempotent (upserts)."""
    import collections

    try:
        from modules.clip_reviews import classify_review_signal, list_reviews
    except Exception as exc:  # noqa: BLE001
        log.warning("cannot derive clip DNA: %s", exc)
        return {"written": 0}

    reviews = list_reviews(limit=5000)
    if not reviews:
        return {"written": 0}

    signals = collections.Counter(classify_review_signal(r) for r in reviews)
    reasons = collections.Counter(
        x for r in reviews if classify_review_signal(r) == "positive"
        for x in (r.get("reasons") or [])
    )
    total = len(reviews)
    boundary = signals.get("boundary", 0)
    # `classify_review_signal` owns the NULL distinction. Keep the defensive
    # review-shape check for older imported records, but never subtract NULLs from
    # the already-clean negative count.
    null_junk = signals.get("null", sum(1 for r in reviews if _is_null_review(r)))
    true_miss = signals.get("negative", 0)

    facts: list[tuple[str, str, bool]] = [
        ("review_summary",
         f"{total} reviews so far: {signals.get('positive',0)} keepers, "
         f"{boundary} boundary (good moment, bad cut), {true_miss} true misses, "
         f"{null_junk} null (dupe/not-postable/not-a-clip).",
         False),
    ]
    if boundary:
        d = _boundary_direction(reviews)
        # Direction from the actual notes: which edge is cut wrong, and how often.
        edge = ""
        if d["total"]:
            if d["end"] >= d["start"] and d["end"]:
                edge = (f" The END is the usual culprit ({d['end']}/{d['total']} boundary "
                        "notes mention the payoff/last word/joke landing getting cut) — "
                        "extend the TAIL so the clip finishes ON the payoff, not before it.")
            elif d["start"]:
                edge = (f" The START is the usual culprit ({d['start']}/{d['total']} notes "
                        "need more lead-in/context) — extend the HEAD so the setup is present.")
            if d["longer"]:
                edge += (f" {d['longer']}/{d['total']} explicitly say the clip was too short — "
                         "when unsure, err longer, never clip mid-sentence.")
        facts.append((
            "boundaries",
            f"Boundaries are the #1 issue ({boundary} clips were good moments cut wrong)."
            f"{edge} A clip cut before the payoff is a BOUNDARY failure, not a bad moment — "
            "never treat it as negative taste evidence.",
            True,
        ))
    facts.append((
        "null_rejections",
        "A clip rated bad with NO written reason is NULL, not a taste-miss: it's "
        "almost always a repeat/duplicate, a moment that makes no sense to post, or "
        "not even a real clip. Treat it as noise — drop it, never learn 'this kind of "
        "moment is bad' from it. Only explained misses are real negative signal.",
        True,
    ))
    if reasons:
        top = ", ".join(f"{r}" for r, _ in reasons.most_common(5))
        facts.append(("what_makes_a_keeper", f"Keepers tend to have: {top}.", False))

    existing = {entry["key"]: entry for entry in recall(
        "clip_dna", factory=factory, creator_id=creator_id,
    )}
    written = 0
    preserved = 0
    for key, value, pinned in facts:
        if existing.get(key, {}).get("source") == "manual":
            preserved += 1
            continue
        remember("clip_dna", key, value, source="derived_reviews",
                 pinned=pinned, factory=factory, creator_id=creator_id)
        written += 1
    log.info("derived %d clip_dna memory entries from %d reviews", written, total)
    return {
        "written": written, "reviews": total, "signals": dict(signals),
        "true_miss": true_miss, "null_junk": null_junk,
        "preserved_manual": preserved,
    }


__all__ = ["LAYERS", "remember", "recall", "forget", "context_block",
           "derive_clip_dna_from_reviews"]
