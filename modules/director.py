"""The Content Director's memory-aware judgement over clip candidates
(blueprint Phase 3 — "the Director reads memory").

`derive`/`director_memory` builds what the Director KNOWS. This module is where it
ACTS on it: before the pipeline auto-promotes the top-N candidates to the Discord
Clip Room, the Director re-ranks them through the creator's Clip DNA rules instead
of trusting the raw detector score alone.

Today the grounded, explainable signal is Lazarus's NULL rule: a moment that is a
repeat / makes no sense to post / "isn't even a clip" should be de-prioritised. In
the real data those low-value candidates are exactly the ones whose transcript is
dominated by stutter/filler ("catch on, catch on, catch on…", "anyways anyways
anyways", "swear swear swear") — no setup, no payoff. The Director down-weights
them and records WHY, so every pick is explainable.

Every adjustment carries a rationale (transparency rule). The score is only nudged,
never overridden — the detector's confidence still leads; memory breaks ties and
pushes obvious non-moments down. This is the seam an LLM taste-judge (reads the
transcript + `director_memory.context_block()`) plugs into later.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from db.base import DEFAULT_CREATOR_ID, SessionLocal

log = logging.getLogger("director")

# How hard memory is allowed to move a candidate's raw score. Kept small so the
# detector still leads; the Director breaks ties and sinks obvious non-moments.
MAX_PENALTY = 0.30

_WORD_RE = re.compile(r"[a-z0-9']+")


@dataclass
class Judgement:
    """The Director's memory-grounded read on one candidate."""
    base_score: float
    adjustment: float
    notes: list[str] = field(default_factory=list)

    @property
    def adjusted_score(self) -> float:
        return self.base_score + self.adjustment

    @property
    def is_null_like(self) -> bool:
        return self.adjustment <= -0.15

    def as_dict(self) -> dict[str, Any]:
        return {
            "base_score": round(self.base_score, 4),
            "adjustment": round(self.adjustment, 4),
            "adjusted_score": round(self.adjusted_score, 4),
            "null_like": self.is_null_like,
            "notes": list(self.notes),
        }


def _repetition_ratio(text: str) -> float:
    """Fraction of words that are redundant. 0.0 = all distinct, →1.0 = one word
    repeated. "catch on catch on catch on" ≈ 0.67."""
    words = _WORD_RE.findall(text.lower())
    if len(words) < 6:
        return 0.0
    return 1.0 - (len(set(words)) / len(words))


def _max_run(text: str) -> int:
    """Longest run of the same word repeated back-to-back ("swear swear swear" = 3)."""
    words = _WORD_RE.findall(text.lower())
    best = run = 0
    prev = None
    for w in words:
        run = run + 1 if w == prev else 1
        best = max(best, run)
        prev = w
    return best


def _rules_active(memory_rules: Optional[dict[str, str]]) -> bool:
    """The null/repeat de-prioritisation runs only when the creator's memory holds
    the rule that justifies it — so the Director acts on what it KNOWS, not on a
    hardcoded opinion. Defaults to on when memory is unavailable."""
    if memory_rules is None:
        return True
    return "null_rejections" in memory_rules


def evaluate_candidate(
    candidate: Any,
    *,
    memory_rules: Optional[dict[str, str]] = None,
) -> Judgement:
    """Score one candidate against the creator's Clip DNA. `candidate` may be a
    ClipCandidate ORM row or a plain dict with `score`/`reason`."""
    if isinstance(candidate, dict):
        base = float(candidate.get("score") or 0.0)
        reason = str(candidate.get("reason") or "")
    else:
        base = float(getattr(candidate, "score", 0.0) or 0.0)
        reason = str(getattr(candidate, "reason", "") or "")

    j = Judgement(base_score=base, adjustment=0.0)
    if not _rules_active(memory_rules):
        return j

    rep = _repetition_ratio(reason)
    run = _max_run(reason)
    words = _WORD_RE.findall(reason.lower())

    # NULL rule applied at selection time: stutter/filler-dominated moments are
    # almost never real clips. Penalty scales with how repetitive the moment is.
    if rep >= 0.45 or run >= 4:
        penalty = min(MAX_PENALTY, 0.18 + rep * 0.25)
        j.adjustment -= penalty
        j.notes.append(
            f"null-like: repetitive/filler transcript (repeat ratio {rep:.0%}, "
            f"longest run {run}) — likely a non-moment, not your taste."
        )
    elif 0 < len(words) < 3:
        # A nearly empty descriptor with a low base score is usually a thin moment.
        if base < 0.6:
            j.adjustment -= 0.05
            j.notes.append("thin: very little going on around this moment.")

    return j


def _load_memory_rules(factory, creator_id: str) -> Optional[dict[str, str]]:
    try:
        from modules.director_memory import recall
        return {e["key"]: e["value"] for e in recall("clip_dna", factory=factory,
                                                      creator_id=creator_id)}
    except Exception as exc:  # noqa: BLE001 — memory must never break promotion
        log.warning("director could not read memory: %s", exc)
        return None


def rank_candidates(
    candidates: list[Any],
    *,
    factory=SessionLocal,
    creator_id: str = DEFAULT_CREATOR_ID,
    memory_rules: Optional[dict[str, str]] = None,
) -> list[tuple[Any, Judgement]]:
    """Rank candidates by memory-adjusted score (desc). Reads Clip DNA once and
    applies it to every candidate. Returns (candidate, judgement) pairs so callers
    can promote the top-N AND explain each pick."""
    if memory_rules is None:
        memory_rules = _load_memory_rules(factory, creator_id)
    judged = [(c, evaluate_candidate(c, memory_rules=memory_rules)) for c in candidates]
    judged.sort(key=lambda pair: pair[1].adjusted_score, reverse=True)
    return judged


# =============================================================================
# LLM taste judge (blueprint Phase 3) — the Director actually READS a candidate's
# transcript + the creator's memory and rates taste-fit in their voice. Runs
# automatically on the promoted top-N (see pipeline_sync). Every step is non-fatal:
# no API key / a bad response just means no verdict, never a broken pipeline.
# =============================================================================

import json

LLM_JUDGE_MODEL = "gemini-2.5-flash"
_VERDICTS = ("keep", "maybe", "skip")
_LLM_VERDICT_REASON = "llm taste verdict"


def _judge_system(memory_block: str) -> str:
    base = (
        "You are the creator's clip taste judge. Decide whether a candidate clip is "
        "worth posting to their socials, in THEIR taste. Judge the MOMENT's potential, "
        "not the raw cut: a great moment cut a little short is still a keep (a human can "
        "fix the trim); a repeat/filler line or a moment that makes no sense to post is a "
        "skip. Be honest and concise.\n"
    )
    if memory_block:
        base += f"\n{memory_block}\n"
    base += (
        '\nReturn ONLY JSON: {"fit": <0.0-1.0>, "verdict": "keep"|"maybe"|"skip", '
        '"why": "<one short sentence in plain language>"}.'
    )
    return base


def _candidate_content(candidate: Any, transcript: str = "") -> str:
    if isinstance(candidate, dict):
        score = candidate.get("score"); reason = candidate.get("reason") or ""
        start = candidate.get("start") or 0.0; end = candidate.get("end") or 0.0
    else:
        score = getattr(candidate, "score", None); reason = getattr(candidate, "reason", "") or ""
        start = getattr(candidate, "start", 0.0) or 0.0; end = getattr(candidate, "end", 0.0) or 0.0
    text = (transcript or reason or "").strip()
    dur = max(0.0, float(end) - float(start))
    return (f"Candidate clip — detector score {score}, duration {dur:.0f}s.\n"
            f"What happens / transcript:\n{text[:1600]}")


def _normalize_verdict(data: Any) -> Optional[dict[str, Any]]:
    if not isinstance(data, dict):
        return None
    try:
        fit = float(data.get("fit", 0.0))
    except (TypeError, ValueError):
        fit = 0.0
    fit = max(0.0, min(1.0, fit))
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in _VERDICTS:
        verdict = "keep" if fit >= 0.66 else "skip" if fit < 0.4 else "maybe"
    why = str(data.get("why", "")).strip()[:400]
    return {"fit": round(fit, 3), "verdict": verdict, "why": why}


def _default_llm_call(system: str, user: str) -> Optional[str]:
    """One synchronous Gemini JSON call, rotating across the creator's keys. Returns
    the raw JSON text, or None if no key works (same key source as the clip judge)."""
    try:
        from modules.clip_judge import _load_gemini_keys
    except Exception:  # noqa: BLE001
        return None
    keys = _load_gemini_keys()
    if not keys:
        return None
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        log.info("google-genai not installed — LLM taste judge disabled")
        return None
    last = None
    for key in keys:
        try:
            client = genai.Client(api_key=key)
            resp = client.models.generate_content(
                model=LLM_JUDGE_MODEL,
                contents=[f"{system}\n\n{user}"],
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            return resp.text
        except Exception as exc:  # noqa: BLE001 - try the next key / give up quietly
            last = exc
    log.warning("LLM taste judge: all Gemini keys failed (%s)", last)
    return None


def llm_judge_candidate(candidate: Any, *, memory_block: str = "", transcript: str = "",
                        client_call=None) -> Optional[dict[str, Any]]:
    """Ask the LLM whether a candidate fits the creator's taste, given the Director
    memory. Returns {"fit", "verdict", "why"} or None if the LLM is unavailable /
    unparseable. Non-fatal by contract. `client_call(system, user)->str|None` is
    injectable for tests."""
    caller = client_call or _default_llm_call
    try:
        raw = caller(_judge_system(memory_block), _candidate_content(candidate, transcript))
    except Exception as exc:  # noqa: BLE001
        log.warning("LLM taste judge call failed: %s", exc)
        return None
    if not raw:
        return None
    try:
        data = raw if isinstance(raw, dict) else json.loads(raw)
    except (TypeError, ValueError):
        return None
    return _normalize_verdict(data)


def _candidate_transcript(stem: str) -> str:
    """The clip's transcript text if we have one cached (best-effort)."""
    try:
        from config import paths
        f = paths.CLIP_TRANSCRIPTS_DIR / f"{stem}.txt"
        if f.is_file():
            return f.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def judge_and_record(candidate_ids: list[str], *, factory=SessionLocal,
                     creator_id: str = DEFAULT_CREATOR_ID, client_call=None) -> int:
    """Run the LLM taste judge on each candidate and record the verdict as an
    append-only WorkflowEvent (so the card / audit / 'why this pick' can show it).
    Non-fatal per candidate. Returns how many verdicts were recorded."""
    from db.repository import ClipCandidateRepo, WorkflowEventRepo, session_scope
    from modules.director_memory import context_block

    memory_block = context_block(factory=factory, creator_id=creator_id)
    # Add the creator's slang glossary so the judge reads slang in THEIR meaning
    # instead of scoring a slang moment as "no context / off-topic".
    try:
        from modules.language_pack import glossary_for_llm
        glossary = glossary_for_llm()
        if glossary:
            memory_block = f"{memory_block}\n\n{glossary}" if memory_block else glossary
    except Exception as exc:  # noqa: BLE001
        log.debug("no language glossary: %s", exc)
    recorded = 0
    for cid in candidate_ids:
        with session_scope(factory) as s:
            c = ClipCandidateRepo(s, creator_id).get(cid)
            if c is None:
                continue
            snap = {"score": c.score, "reason": c.reason, "start": c.start,
                    "end": c.end, "stem": c.stem}
        verdict = llm_judge_candidate(
            snap, memory_block=memory_block,
            transcript=_candidate_transcript(snap["stem"]), client_call=client_call,
        )
        if verdict is None:
            continue
        with session_scope(factory) as s:
            WorkflowEventRepo(s, creator_id).append(
                entity_type="clip_candidate", entity_id=cid, actor="director-llm",
                reason=_LLM_VERDICT_REASON, payload=verdict,
            )
        recorded += 1
    log.info("LLM taste judge recorded %d/%d verdicts", recorded, len(candidate_ids))
    return recorded


def latest_verdict(candidate_id: str, *, factory=SessionLocal,
                   creator_id: str = DEFAULT_CREATOR_ID) -> Optional[dict[str, Any]]:
    """The most recent LLM taste verdict recorded for a candidate, if any."""
    from db.repository import WorkflowEventRepo, session_scope

    with session_scope(factory) as s:
        events = WorkflowEventRepo(s, creator_id).for_entity("clip_candidate", candidate_id)
        for ev in reversed(events):
            if ev.reason == _LLM_VERDICT_REASON and ev.payload:
                return dict(ev.payload)
    return None


__all__ = [
    "Judgement", "evaluate_candidate", "rank_candidates", "MAX_PENALTY",
    "llm_judge_candidate", "judge_and_record", "latest_verdict", "LLM_JUDGE_MODEL",
]
