"""Creator Language Pack — the creator's slang / terms / multilingual glossary so
the AI UNDERSTANDS how they actually talk (Namibian + Afrikaans + Oshiwambo +
in-group slang), instead of judging a slang clip as "no context / off-topic".

Two jobs:
  - `glossary_for_llm()` — a compact "term = meaning" block injected into the LLM
    taste judge and chat co-pilot so it reads slang the way the creator means it.
  - `whisper_hotwords()` — the terms as a transcription bias (initial_prompt).

`seed_from_reviews()` mines the creator's own review NOTES — they've been defining
their slang there ("tsek = go away", "shanyok = ... in oshiwambo") — so the pack
starts grounded in what they've already taught the system.

Storage is a plain JSON file (like caption templates / clip memory); export/import
is declarative and secret-free, aligning with the shareable `.lekprofile` vision.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Optional

from config import paths

log = logging.getLogger("language_pack")

PACK_FILE = paths.DATA_DIR / "language_pack.json"

# A term is at most 3 short words; these never START a real slang term (they mark
# a sentence, not a word being defined) — cheap guard against extracting phrases.
_TERM_STOPWORDS = {
    "while", "when", "cause", "because", "so", "tell", "way", "that", "this",
    "the", "i", "he", "she", "they", "it", "and", "but", "also", "just", "like",
    "here", "there", "what", "why", "how", "then", "said", "im", "its", "a",
    "btw", "ok", "yea", "yeah", "nah", "lol", "lmao", "fr", "ig", "u", "to", "of",
    "him", "her", "them", "my", "his", "our", "we", "you", "is", "was",
    "which", "who", "where", "tought", "thought", "call", "calls", "called",
}
# "<term> <connector> <meaning>" — the creator's own definitions in review notes.
_DEF_RE = re.compile(
    r"(?P<term>[a-zÀ-ɏ'][a-zÀ-ɏ' ]{1,24})\s+"
    r"(?:=|means|meaning|which is|which means|is short for|is basically|is like)\s+"
    r"(?P<meaning>[a-zÀ-ɏ].{2,70})",
    re.IGNORECASE,
)


def _load() -> dict[str, Any]:
    if PACK_FILE.exists():
        try:
            data = json.loads(PACK_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("terms"), list):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {"terms": [], "updated_at": 0.0}


def _save(data: dict[str, Any]) -> None:
    data["updated_at"] = time.time()
    PACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    PACK_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _norm(term: str) -> str:
    return " ".join(str(term).strip().lower().split())


def list_terms() -> list[dict[str, Any]]:
    return _load()["terms"]


def add_term(term: str, meaning: str, *, lang: str = "", aliases: Optional[list[str]] = None,
             source: str = "manual", confidence: float = 1.0) -> Optional[dict[str, Any]]:
    key = _norm(term)
    if not key or not str(meaning).strip():
        return None
    data = _load()
    entry = {
        "term": key,
        "meaning": str(meaning).strip()[:200],
        "lang": str(lang).strip()[:20],
        "aliases": sorted({_norm(a) for a in (aliases or []) if _norm(a)}),
        "source": source,
        "confidence": max(0.0, min(1.0, float(confidence))),
    }
    terms = [t for t in data["terms"] if _norm(t.get("term", "")) != key]
    # A manual definition always wins over a previously derived one.
    existing = next((t for t in data["terms"] if _norm(t.get("term", "")) == key), None)
    if existing and existing.get("source") == "manual" and source != "manual":
        return existing
    terms.append(entry)
    data["terms"] = sorted(terms, key=lambda t: t["term"])
    _save(data)
    return entry


def delete_term(term: str) -> bool:
    key = _norm(term)
    data = _load()
    before = len(data["terms"])
    data["terms"] = [t for t in data["terms"] if _norm(t.get("term", "")) != key]
    if len(data["terms"]) == before:
        return False
    _save(data)
    return True


def whisper_hotwords(max_terms: int = 200) -> list[str]:
    """Terms + aliases to bias transcription toward the creator's vocabulary."""
    words: list[str] = []
    for t in list_terms():
        words.append(t["term"])
        words.extend(t.get("aliases") or [])
    # Preserve order, drop dups, cap length.
    seen, out = set(), []
    for w in words:
        if w and w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) >= max_terms:
            break
    return out


def glossary_for_llm(max_chars: int = 1500) -> str:
    """A compact glossary block for the taste judge / chat so it understands slang."""
    terms = list_terms()
    if not terms:
        return ""
    lines = ["Creator slang glossary — read these clips in THEIR meaning, don't call "
             "a moment 'no context' just because it uses slang:"]
    for t in terms:
        alias = f" (aka {', '.join(t['aliases'])})" if t.get("aliases") else ""
        lang = f" [{t['lang']}]" if t.get("lang") else ""
        lines.append(f"- {t['term']}{alias}{lang} = {t['meaning']}")
    return "\n".join(lines)[:max_chars]


def _trim_term(raw: str) -> str:
    """The coined term trails the filler: keep only what comes AFTER the last
    stop/filler word, then the last ≤3 words. "its ma se poes" -> "ma se poes",
    "so i tought him tsek" -> "tsek", "jacking it" -> "" (dropped)."""
    words = _norm(raw).split()
    last_stop = max((i for i, w in enumerate(words) if w in _TERM_STOPWORDS), default=-1)
    words = words[last_stop + 1:]
    while words and words[-1] in _TERM_STOPWORDS:
        words.pop()
    return " ".join(words[-3:])


def _looks_like_term(term: str) -> bool:
    words = term.split()
    if not (1 <= len(words) <= 3):
        return False
    if words[0] in _TERM_STOPWORDS:
        return False
    # Reject if it's mostly stopwords (a sentence fragment, not a coined term).
    if sum(w in _TERM_STOPWORDS for w in words) > len(words) // 2:
        return False
    return True


def _clean_meaning(meaning: str) -> str:
    # Keep just the definition clause, before the creator moves on to clip notes
    # or trails off into filler ("btw", "fr", "lmao", "also just", "but this").
    m = re.split(
        r"[.;]| btw | fr | lmao| lol| but this | also just | clip | so yea| and i ",
        meaning, maxsplit=1,
    )[0]
    words = m.strip().split()
    while words and words[-1] in {"btw", "fr", "lol", "lmao", "yea", "ig", "tho", "though"}:
        words.pop()
    return " ".join(words)[:120]


def seed_from_reviews() -> dict[str, Any]:
    """Mine review notes for slang the creator already defined and add them as
    derived terms (curatable in the Studio). Idempotent (upserts by term)."""
    try:
        from modules.clip_reviews import list_reviews
    except Exception as exc:  # noqa: BLE001
        log.warning("cannot seed language pack: %s", exc)
        return {"added": 0}

    added = 0
    for r in list_reviews(limit=5000):
        note = str(r.get("notes") or "")
        for m in _DEF_RE.finditer(note):
            term = _trim_term(m.group("term"))
            meaning = _clean_meaning(m.group("meaning"))
            if not _looks_like_term(term) or len(meaning) < 3:
                continue
            lang = ""
            low = meaning.lower()
            for name in ("afrikaans", "oshiwambo", "oshivambo"):
                if name in low:
                    lang = name
            if add_term(term, meaning, lang=lang, source="derived_reviews", confidence=0.6):
                added += 1
    log.info("seeded %d slang terms from reviews", added)
    return {"added": added, "total": len(list_terms())}


def export_pack() -> dict[str, Any]:
    """A declarative, secret-free pack for sharing (no voiceprint/media/creds)."""
    return {"kind": "lek_language_pack", "version": 1, "terms": list_terms()}


def import_pack(data: dict[str, Any], *, mode: str = "merge") -> dict[str, Any]:
    incoming = data.get("terms") if isinstance(data, dict) else None
    if not isinstance(incoming, list):
        raise ValueError("invalid language pack: missing 'terms' list")
    if mode == "replace":
        _save({"terms": []})
    added = 0
    for t in incoming:
        if isinstance(t, dict) and add_term(
            t.get("term", ""), t.get("meaning", ""), lang=t.get("lang", ""),
            aliases=t.get("aliases"), source="imported",
            confidence=float(t.get("confidence", 1.0) or 1.0),
        ):
            added += 1
    return {"imported": added, "total": len(list_terms()), "mode": mode}


__all__ = [
    "list_terms", "add_term", "delete_term", "whisper_hotwords", "glossary_for_llm",
    "seed_from_reviews", "export_pack", "import_pack", "PACK_FILE",
]
