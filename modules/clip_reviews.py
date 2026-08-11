"""Persistent human clip reviews used by the UI and LLM profile tuner."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from config import paths

REVIEW_VERSION = 1

REASON_PRESETS = [
    "strong reaction",
    "clean setup",
    "funny line",
    "good pacing",
    "visual context helps",
    "dead air",
    "weak payoff",
    "bad crop",
    "caption missed context",
    "wrong speaker",
]

# Sort/folder tags for the gallery, split by polarity. Clips can carry any of
# these (or custom tags). "good" tags apply to positives, "bad" to negatives.
TAG_TAXONOMY: dict[str, list[str]] = {
    "good": [
        "posting these",
        "lwk good clip",
        "compilation clip",
        "standalone",
        "edited example",
        "raw example",
    ],
    "bad": [
        "bad trim good clip",
        "missed the point",
        "not funny",
        "complete miss",
        "micro clip",
    ],
}

BOUNDARY_FAILURE_TAGS = {"bad trim good clip"}
CONTEXT_FAILURE_TAGS = {"missed the point"}
TRUE_NEGATIVE_TAGS = {"not funny", "complete miss", "micro clip"}
POSITIVE_TASTE_TAGS = {"posting these", "lwk good clip", "compilation clip", "standalone"}

_TRUE_NEGATIVE_NOTE_RE = re.compile(
    r"\b(?:ain'?t a clip|not (?:really )?a clip|random moment|complete miss|not funny)\b",
    re.IGNORECASE,
)
_BOUNDARY_NOTE_RE = re.compile(
    r"(?:cut (?:off|out|too short)|cut right before|too short|ends? too early|"
    r"extend(?:ed)?|a lil bit longer|a little bit longer|add (?:in )?the beginning|"
    r"add more to the end|beginning and end|missing? (?:the )?(?:setup|ending|context)|"
    r"missed the part|lost conte(?:x|c)t due to being cut|before the good part|"
    r"needs? (?:the )?(?:music|other clip|more)|more later|where the joke lands|"
    r"no payoff|finish the word|land fully)",
    re.IGNORECASE,
)


def classify_review_signal(review: dict[str, Any] | None) -> str:
    """Classify what a review teaches without confusing cut quality with taste.

    ``boundary`` and ``context`` mean the selected moment may be useful, but the
    generated clip failed around it. ``null`` means the creator rejected the
    item without teaching us why, so it must not become taste evidence. Only
    ``negative`` is safe negative evidence for semantic/profile training.
    """
    if not review:
        return "unreviewed"

    tags = {str(tag).strip().lower() for tag in (review.get("tags") or []) if tag}
    reasons = {str(reason).strip().lower() for reason in (review.get("reasons") or []) if reason}
    notes = str(review.get("notes") or "").strip()
    verdict = str(review.get("verdict") or "undecided").strip().lower()

    if tags & BOUNDARY_FAILURE_TAGS:
        return "boundary"
    if tags & TRUE_NEGATIVE_TAGS:
        return "negative"
    if _TRUE_NEGATIVE_NOTE_RE.search(notes):
        return "negative"
    if _BOUNDARY_NOTE_RE.search(notes):
        return "boundary"
    if tags & CONTEXT_FAILURE_TAGS or reasons & {"wrong speaker", "caption missed context"}:
        return "context"
    if verdict == "keeper" or tags & POSITIVE_TASTE_TAGS:
        return "positive"
    if verdict in {"miss", "bad"} and not tags and not reasons and not notes:
        return "null"
    if verdict in {"miss", "bad"}:
        return "negative"
    if verdict == "maybe":
        return "maybe"
    return "uncertain"


def _empty_store() -> dict[str, Any]:
    return {"version": REVIEW_VERSION, "reviews": {}}


def _read_store() -> dict[str, Any]:
    if not paths.CLIP_REVIEWS_FILE.exists():
        return _empty_store()
    try:
        with open(paths.CLIP_REVIEWS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(data, dict):
        return _empty_store()
    reviews = data.get("reviews")
    if not isinstance(reviews, dict):
        data["reviews"] = {}
    data.setdefault("version", REVIEW_VERSION)
    return data


def _write_store(data: dict[str, Any]) -> None:
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = paths.CLIP_REVIEWS_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, paths.CLIP_REVIEWS_FILE)


def _clean_text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").strip()
    return text[:limit]


def _clean_reasons(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    seen = set()
    for value in values:
        text = _clean_text(value, 80).lower()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out[:12]


def _clean_tags(values: Any) -> list[str]:
    # Same shape as reasons: short, lowercased, deduped, capped.
    return _clean_reasons(values)


def get_review(stem: str) -> dict[str, Any] | None:
    review = _read_store()["reviews"].get(stem)
    return dict(review) if isinstance(review, dict) else None


def list_reviews(limit: int = 500) -> list[dict[str, Any]]:
    reviews = [
        dict(v)
        for v in _read_store()["reviews"].values()
        if isinstance(v, dict)
    ]
    reviews.sort(key=lambda r: float(r.get("updated_at") or r.get("created_at") or 0), reverse=True)
    return reviews[:limit]


def save_review(stem: str, bucket: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = _read_store()
    reviews = data["reviews"]
    now = time.time()
    existing = reviews.get(stem) if isinstance(reviews.get(stem), dict) else {}

    rating_raw = payload.get("rating")
    rating = None
    if rating_raw not in (None, ""):
        rating = max(1, min(5, int(rating_raw)))

    verdict = _clean_text(payload.get("verdict") or "undecided", 32).lower()
    if verdict not in {"keeper", "maybe", "miss", "undecided"}:
        verdict = "undecided"

    review = {
        "stem": stem,
        "bucket": bucket,
        "rating": rating,
        "verdict": verdict,
        "reasons": _clean_reasons(payload.get("reasons")),
        # Preserve existing tags when a review save doesn't carry them.
        "tags": _clean_tags(payload.get("tags", existing.get("tags", []))),
        "notes": _clean_text(payload.get("notes"), 4000),
        "caption_notes": _clean_text(payload.get("caption_notes"), 3000),
        "created_at": float(existing.get("created_at") or now),
        "updated_at": now,
    }
    reviews[stem] = review
    _write_store(data)
    return review


def set_clip_tags(stem: str, bucket: str, tags: Any) -> dict[str, Any]:
    """Upsert only the tags for a clip, preserving any existing review fields."""
    data = _read_store()
    reviews = data["reviews"]
    now = time.time()
    existing = reviews.get(stem) if isinstance(reviews.get(stem), dict) else {}
    record = dict(existing)
    record["stem"] = stem
    record["bucket"] = bucket or record.get("bucket", "")
    record.setdefault("rating", None)
    record.setdefault("verdict", "undecided")
    record.setdefault("reasons", [])
    record.setdefault("notes", "")
    record.setdefault("caption_notes", "")
    record["tags"] = _clean_tags(tags)
    record["created_at"] = float(existing.get("created_at") or now)
    record["updated_at"] = now
    reviews[stem] = record
    _write_store(data)
    return record


def get_clip_tags(stem: str) -> list[str]:
    review = get_review(stem)
    return list(review.get("tags") or []) if review else []


def tags_index() -> dict[str, list[str]]:
    """stem -> tags, for clips that have any. One store read for the whole gallery."""
    return {
        stem: list(r.get("tags") or [])
        for stem, r in _read_store()["reviews"].items()
        if isinstance(r, dict) and r.get("tags")
    }


def review_prompt_context(stem: str) -> str:
    review = get_review(stem)
    if not review:
        return ""
    parts: list[str] = []
    if review.get("rating"):
        parts.append(f"rating={review['rating']}/5")
    if review.get("verdict") and review["verdict"] != "undecided":
        parts.append(f"verdict={review['verdict']}")
    if review.get("reasons"):
        parts.append("reasons=" + ", ".join(review["reasons"]))
    if review.get("tags"):
        parts.append("tags=" + ", ".join(review["tags"]))
    parts.append("learning_signal=" + classify_review_signal(review))
    if review.get("notes"):
        parts.append("notes=" + str(review["notes"])[:500])
    if review.get("caption_notes"):
        parts.append("caption_notes=" + str(review["caption_notes"])[:400])
    return " | ".join(parts)


def summarize_reviews_for_llm(
    max_keepers: int = 6,
    max_misses: int = 6,
    notes_chars: int = 240,
    max_context: int = 10,
) -> str:
    """
    Format the user's review history as a context block for the chat LLM.

    The goal is to teach the model — in plain text — what THIS user calls
    a good clip versus a bad one, by showing concrete examples (notes +
    reasons + rating) plus aggregated patterns. The model can then reason
    about new clips, transcripts, or suggestions using the same vocabulary
    the user uses in reviews.
    """
    reviews = list_reviews(limit=500)
    if not reviews:
        return ""

    def _example(r: dict) -> str:
        bits = [f"  - \"{r.get('stem')}\""]
        verdict = r.get("verdict")
        if verdict and verdict != "undecided":
            bits.append(f"verdict: {verdict}")
        rating = r.get("rating")
        if rating:
            bits.append(f"rating {rating}/5")
        tags = [str(tag) for tag in (r.get("tags") or []) if tag]
        if tags:
            bits.append("tags: " + ", ".join(tags))
        reasons = r.get("reasons") or []
        if reasons:
            bits.append("reasons: " + ", ".join(reasons))
        notes = (r.get("notes") or "").strip()
        if notes:
            bits.append(f"notes: \"{notes[:notes_chars]}\"")
        cap_notes = (r.get("caption_notes") or "").strip()
        if cap_notes:
            bits.append(f"caption notes: \"{cap_notes[:notes_chars]}\"")
        return ". ".join(bits)

    keepers = [r for r in reviews if classify_review_signal(r) == "positive"][:max_keepers]
    boundary_failures = [
        r for r in reviews if classify_review_signal(r) in {"boundary", "context"}
    ][:max_misses]
    misses = [
        r
        for r in reviews
        if r.get("verdict") == "miss" and classify_review_signal(r) == "negative"
    ][:max_misses]
    context_notes = [
        r
        for r in reviews
        if (r.get("notes") or "").strip()
        and classify_review_signal(r) in {"context", "uncertain", "maybe"}
    ][:max_context]

    # Aggregated reason / rating patterns across the full history.
    keeper_reason_counts: dict[str, int] = {}
    miss_reason_counts:   dict[str, int] = {}
    rating_buckets = {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0}
    for r in reviews:
        signal = classify_review_signal(r)
        for reason in (r.get("reasons") or []):
            if signal == "positive":
                keeper_reason_counts[reason] = keeper_reason_counts.get(reason, 0) + 1
            elif signal == "negative":
                miss_reason_counts[reason] = miss_reason_counts.get(reason, 0) + 1
        rating = r.get("rating")
        if rating in (1, 2, 3, 4, 5):
            rating_buckets[str(rating)] += 1

    top_keeper_reasons = sorted(keeper_reason_counts.items(), key=lambda x: -x[1])[:5]
    top_miss_reasons   = sorted(miss_reason_counts.items(),   key=lambda x: -x[1])[:5]

    blocks: list[str] = []
    blocks.append(
        f"USER CLIP REVIEWS ({len(reviews)} total). Verdict and tags define the "
        "learning signal. Ratings describe usefulness/postability and MUST NOT "
        "override an explicit verdict. A bad trim/context failure is evidence to "
        "fix the window or interpretation, NOT evidence that the moment itself is bad:"
    )
    if keepers:
        blocks.append("KEEPERS (clips the user wants more of):\n" +
                      "\n".join(_example(r) for r in keepers))
    if boundary_failures:
        blocks.append(
            "BOUNDARY / CONTEXT FAILURES (keep looking around this moment; widen or reinterpret it):\n" +
            "\n".join(_example(r) for r in boundary_failures)
        )
    if misses:
        blocks.append("TRUE MISSES (bad moment/selection; safe negative taste evidence):\n" +
                      "\n".join(_example(r) for r in misses))
    if context_notes:
        blocks.append(
            "RECENT USER CONTEXT / SLANG (applies even when the verdict is undecided):\n" +
            "\n".join(_example(r) for r in context_notes)
        )
    if top_keeper_reasons or top_miss_reasons:
        pattern_parts = []
        if top_keeper_reasons:
            pattern_parts.append(
                "  positive signals (from keepers): " +
                ", ".join(f"{name} ({count})" for name, count in top_keeper_reasons)
            )
        if top_miss_reasons:
            pattern_parts.append(
                "  negative signals (from misses): " +
                ", ".join(f"{name} ({count})" for name, count in top_miss_reasons)
            )
        blocks.append("RECURRING PATTERNS:\n" + "\n".join(pattern_parts))
    rated = sum(rating_buckets.values())
    if rated:
        blocks.append(
            "RATING DISTRIBUTION: " +
            ", ".join(f"{star}★={rating_buckets[star]}" for star in ("5", "4", "3", "2", "1"))
        )
    return "\n\n".join(blocks)
