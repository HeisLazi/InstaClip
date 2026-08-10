"""
Persistent clipping memory the AI maintains across sessions.

This is a single markdown file at data/clip_memory.md, structured so a local
LLM can quickly parse it on every run and so future tuner passes can read
their own prior output. Sections:

  ## Context rules           conditional rules the flat profile can't express
                             (e.g. "silent horror running is clippable, not dead air")
  ## Slang glossary          word -> meaning entries learned from review notes
  ## Twitch-validated moments summarized from data/twitch_clip_notes.json
                             (clips viewers/streamer made on Twitch — strong positives)
  ## Patterns to avoid       things the user has flagged as never-clip

Producers:
  modules/profile_tuner    review-driven tuner writes context_rules + slang
Consumers:
  future engine upgrades   can read individual sections programmatically

Note: twitch_fetcher is not included in the public edition; the Twitch section
is preserved for compatibility but will remain empty unless populated manually.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from config import paths

log = logging.getLogger("clip_memory")

MEMORY_FILE = paths.DATA_DIR / "clip_memory.md"
TWITCH_NOTES_FILE = paths.DATA_DIR / "twitch_clip_notes.json"

SECTION_CONTEXT_RULES = "## Context rules"
SECTION_SLANG         = "## Slang glossary"
SECTION_TWITCH        = "## Twitch-validated moments"
SECTION_AVOID         = "## Patterns to avoid"

_HEADER = (
    "# Clip Intelligence Memory\n\n"
    "Auto-maintained by the profile tuner and twitch sync. The chat LLM "
    "reads this on every conversation; future clipping runs read the "
    "structured sections. Edit by hand only if you understand the section "
    "layout — automated writes preserve unknown content where possible."
)

_KNOWN_SECTIONS = [SECTION_CONTEXT_RULES, SECTION_SLANG, SECTION_TWITCH, SECTION_AVOID]


def _ensure_file() -> None:
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not MEMORY_FILE.exists():
        body = _HEADER + "\n\n" + "\n\n".join(f"{h}\n" for h in _KNOWN_SECTIONS) + "\n"
        MEMORY_FILE.write_text(body, encoding="utf-8")


def _read_text() -> str:
    if not MEMORY_FILE.exists():
        return ""
    try:
        return MEMORY_FILE.read_text(encoding="utf-8")
    except Exception as e:
        log.warning(f"Could not read {MEMORY_FILE}: {e}")
        return ""


def _split_sections(text: str) -> dict[str, str]:
    """
    Parse the markdown into {section_header: body} where body is everything
    between this header and the next ## one. Content before the first ##
    header is stored under the key "__preamble__".
    """
    sections: dict[str, str] = {"__preamble__": ""}
    current = "__preamble__"
    lines = text.splitlines()
    buf: list[str] = []
    for line in lines:
        if line.startswith("## "):
            sections[current] = "\n".join(buf).rstrip()
            current = line.strip()
            buf = []
        else:
            buf.append(line)
    sections[current] = "\n".join(buf).rstrip()
    return sections


def _serialize_sections(sections: dict[str, str]) -> str:
    parts: list[str] = []
    preamble = sections.get("__preamble__", "").strip()
    if preamble:
        parts.append(preamble)
    # Emit known sections in canonical order, then any unknown ones.
    ordered_keys = [k for k in _KNOWN_SECTIONS if k in sections]
    ordered_keys += [k for k in sections.keys() if k not in _KNOWN_SECTIONS and k != "__preamble__" and k not in ordered_keys]
    for key in ordered_keys:
        body = sections.get(key, "").rstrip()
        parts.append(key + ("\n" + body if body else ""))
    return "\n\n".join(parts).rstrip() + "\n"


def _replace_section(section_header: str, new_body: str) -> None:
    _ensure_file()
    text = _read_text()
    sections = _split_sections(text)
    if not sections.get("__preamble__"):
        sections["__preamble__"] = _HEADER
    sections[section_header] = new_body.rstrip()
    MEMORY_FILE.write_text(_serialize_sections(sections), encoding="utf-8")


def _append_to_section(section_header: str, additions: list[str]) -> int:
    """
    Append lines to a section, skipping duplicates (case-insensitive).
    Returns number of lines actually added.
    """
    if not additions:
        return 0
    _ensure_file()
    text = _read_text()
    sections = _split_sections(text)
    if not sections.get("__preamble__"):
        sections["__preamble__"] = _HEADER
    body = sections.get(section_header, "")
    body_lower = body.lower()
    new_lines = []
    for entry in additions:
        entry = entry.strip()
        if not entry:
            continue
        if entry.lower() in body_lower:
            continue
        new_lines.append(entry)
    if not new_lines:
        return 0
    combined_body = body.rstrip()
    if combined_body:
        combined_body += "\n"
    combined_body += "\n".join(new_lines)
    sections[section_header] = combined_body
    MEMORY_FILE.write_text(_serialize_sections(sections), encoding="utf-8")
    return len(new_lines)


# =============================================================================
# Public writers
# =============================================================================

def append_context_rules(rules: list[str]) -> int:
    """Add new conditional clipping rules. Duplicate-safe."""
    formatted = [f"- {r}" for r in rules if isinstance(r, str) and r.strip()]
    return _append_to_section(SECTION_CONTEXT_RULES, formatted)


def append_learned_slang(glossary: dict[str, str]) -> int:
    """
    Add word -> meaning entries learned from review notes. Skips entries
    where the word is already present (case-insensitive on the word).
    """
    if not isinstance(glossary, dict) or not glossary:
        return 0
    _ensure_file()
    text = _read_text()
    sections = _split_sections(text)
    body = sections.get(SECTION_SLANG, "")
    body_lower = body.lower()

    new_entries = []
    for word, meaning in glossary.items():
        if not isinstance(word, str) or not isinstance(meaning, str):
            continue
        w = word.strip().lower()
        m = meaning.strip()
        if not w or not m:
            continue
        if f"**{w}**" in body_lower or f"- **{w}**" in body_lower:
            continue
        new_entries.append(f"- **{w}** — {m}")
    return _append_to_section(SECTION_SLANG, new_entries)


def append_avoid_patterns(patterns: list[str]) -> int:
    """Add patterns the user has flagged as never-clip."""
    formatted = [f"- {p}" for p in patterns if isinstance(p, str) and p.strip()]
    return _append_to_section(SECTION_AVOID, formatted)


def refresh_twitch_summary(max_clips: int = 30) -> int:
    """
    Read data/twitch_clip_notes.json and rewrite the Twitch section of
    clip_memory.md with the top clips by view count. Returns the number of
    clips summarized.
    """
    if not TWITCH_NOTES_FILE.exists():
        return 0
    try:
        notes = json.loads(TWITCH_NOTES_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning(f"Could not parse {TWITCH_NOTES_FILE}: {e}")
        return 0
    clips = notes.get("clips", []) if isinstance(notes, dict) else []
    if not clips:
        _replace_section(SECTION_TWITCH, "(none yet — run a twitch sync to populate)")
        return 0

    # Sort by view_count desc — these are the strongest positive signal.
    clips_sorted = sorted(
        clips,
        key=lambda c: int(c.get("view_count") or 0),
        reverse=True,
    )[:max_clips]

    lines = [
        "These are clips that viewers or the streamer made directly on Twitch — strong evidence that the moment was clippable. When the same VOD comes through the pipeline, prioritise these timestamps.",
        "",
    ]
    by_vod: dict[str, list[dict]] = {}
    for c in clips_sorted:
        vod = c.get("video_id") or "(unknown vod)"
        by_vod.setdefault(vod, []).append(c)

    for vod_id, group in by_vod.items():
        lines.append(f"### VOD {vod_id}")
        for c in group:
            offset = c.get("vod_offset")
            duration = c.get("duration")
            title = (c.get("title") or "").strip() or "(no title)"
            views = c.get("view_count") or 0
            creator = c.get("creator_name") or ""
            offset_str = f"{int(offset)}s" if isinstance(offset, (int, float)) else "?"
            dur_str = f"{float(duration):.0f}s" if isinstance(duration, (int, float)) else "?"
            line = f"- @{offset_str} ({dur_str}) · {views} views · \"{title}\""
            if creator:
                line += f" — clipped by {creator}"
            lines.append(line)
        lines.append("")

    lines.append(f"_summary refreshed {datetime.now().strftime('%Y-%m-%d %H:%M')}_")
    _replace_section(SECTION_TWITCH, "\n".join(lines))
    return len(clips_sorted)


# =============================================================================
# Public reader
# =============================================================================

def read_memory_for_llm() -> str:
    """
    Return the full memory file as a string, suitable for dropping into a
    system prompt. Returns empty string if the file doesn't exist yet.
    """
    if not MEMORY_FILE.exists():
        return ""
    text = _read_text().strip()
    return text


def memory_stats() -> dict:
    """Lightweight summary for the GUI."""
    if not MEMORY_FILE.exists():
        return {"exists": False}
    sections = _split_sections(_read_text())
    def _count(header: str) -> int:
        body = sections.get(header, "")
        return sum(1 for line in body.splitlines() if line.strip().startswith("- "))
    return {
        "exists": True,
        "path": str(MEMORY_FILE),
        "context_rules": _count(SECTION_CONTEXT_RULES),
        "slang_entries": _count(SECTION_SLANG),
        "twitch_entries": _count(SECTION_TWITCH),
        "avoid_patterns": _count(SECTION_AVOID),
    }
