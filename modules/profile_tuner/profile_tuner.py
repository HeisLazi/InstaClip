# =============================================================================
# modules/profile_tuner/profile_tuner.py
# =============================================================================
# Use a local LLM (via Ollama) to look at the user's good clips vs bad clips
# and suggest changes to lek_profile.json. The user approves or rejects the
# changes in the GUI — we never auto-apply.
# =============================================================================

import json
import logging
import random
import urllib.error
import urllib.request
from pathlib import Path

from config import paths
from modules.clip_reviews import review_prompt_context
from utils.profile_editor import EDITABLE_DICT_LISTS, EDITABLE_LISTS

# publisher.py is excluded from the public edition; the tuner falls back to
# profile-only samples when posted-clips helpers are unavailable.
def posted_stems() -> set[str]:
    return set()


def posted_clip_paths() -> list[Path]:
    return []

log = logging.getLogger("profile_tuner")

OLLAMA_GENERATE = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5-coder:7b"
GEMINI_MODEL = "gemini-2.5-flash"
REQUEST_TIMEOUT = 240
MAX_TRANSCRIPT_CHARS = 400  # per clip snippet — keep prompt within context


# =============================================================================
# Gather transcript samples
# =============================================================================

def _gather_samples(directory: Path, limit: int) -> list[dict]:
    """
    Pick clips that already have a cached transcript at data/clip_transcripts/.
    Returns at most `limit` snippets.
    """
    if not directory.exists():
        return []
    posted = posted_stems()
    clips = list(directory.rglob("*.mp4"))
    posted_clips = [c for c in clips if c.stem in posted]
    other_clips = [c for c in clips if c.stem not in posted]
    random.shuffle(posted_clips)
    random.shuffle(other_clips)
    clips = posted_clips + other_clips

    samples = []
    for c in clips:
        cache = paths.CLIP_TRANSCRIPTS_DIR / f"{c.stem}.txt"
        if not cache.exists():
            continue
        text = cache.read_text(encoding="utf-8").strip()
        if not text:
            continue
        visual = paths.CLIP_TRANSCRIPTS_DIR / f"{c.stem}.vision.txt"
        samples.append({
            "name": c.stem,
            "text": text[:MAX_TRANSCRIPT_CHARS],
            "visual": visual.read_text(encoding="utf-8").strip()[:MAX_TRANSCRIPT_CHARS] if visual.exists() else "",
            "review": review_prompt_context(c.stem),
            "posted": c.stem in posted,
        })
        if len(samples) >= limit:
            break
    return samples


def _format_sample(sample: dict) -> str:
    tags = []
    if sample.get("posted"):
        tags.append("POSTED=high_value_positive")
    if sample.get("review"):
        tags.append(f"REVIEW: {sample['review']}")
    if sample.get("visual"):
        tags.append(f"VISUAL: {sample['visual']}")
    prefix = f"[{sample.get('name', 'clip')}]"
    if tags:
        prefix += " " + " | ".join(tags)
    return f"- {prefix}\n  transcript: {sample.get('text', '')}"


def _gather_posted_samples(limit: int) -> list[dict]:
    samples = []
    for c in posted_clip_paths():
        cache = paths.CLIP_TRANSCRIPTS_DIR / f"{c.stem}.txt"
        if not cache.exists():
            continue
        text = cache.read_text(encoding="utf-8").strip()
        if not text:
            continue
        visual = paths.CLIP_TRANSCRIPTS_DIR / f"{c.stem}.vision.txt"
        samples.append({
            "name": c.stem,
            "text": text[:MAX_TRANSCRIPT_CHARS],
            "visual": visual.read_text(encoding="utf-8").strip()[:MAX_TRANSCRIPT_CHARS] if visual.exists() else "",
            "review": review_prompt_context(c.stem),
            "posted": True,
        })
        if len(samples) >= limit:
            break
    return samples


# =============================================================================
# Prompt assembly
# =============================================================================

def _build_prompt(profile: dict,
                  good_samples: list[dict],
                  bad_samples: list[dict],
                  max_suggestions: int = 8) -> str:
    keys_doc = []
    for key, meta in EDITABLE_LISTS.items():
        keys_doc.append(f'  - "{key}" (list of single words) — {meta["desc"]}')
    for key, meta in EDITABLE_DICT_LISTS.items():
        keys_doc.append(f'  - "{key}" (list of short phrases) — {meta["desc"]}')
    keys_block = "\n".join(keys_doc)

    profile_slice = {
        k: profile.get(k, [])[:25]  # truncate big lists to fit the prompt
        for k in list(EDITABLE_LISTS) + list(EDITABLE_DICT_LISTS)
    }

    good_block = "\n".join(_format_sample(s) for s in good_samples)
    bad_block = "\n".join(_format_sample(s) for s in bad_samples)

    return f"""You are tuning a heuristic scoring profile used to find clip-worthy moments in a streamer's VODs.

The profile has these editable fields:
{keys_block}

Here is the current profile (truncated to first 25 entries per list):
```json
{json.dumps(profile_slice, indent=2)}
```

GOOD clip transcripts (moments the streamer kept as highlights):
{good_block}

BAD clip transcripts (moments the streamer rejected):
{bad_block}

Compare GOOD vs BAD. Posted clips are the strongest positive evidence because the user actually shared them. User review notes and caption notes are direct feedback; visual captions show what the vision model saw.
Suggest small, careful changes — at most {max_suggestions} total items across all lists.
Rules:
- Only suggest words/phrases you actually see in the samples above. No hallucinations.
- Prefer SHORT entries (1-3 words).
- Don't repeat anything already in the current profile.
- If a word appears in BOTH good and bad transcripts, do not add it.
- Treat POSTED clips as higher-value positives than ordinary good clips.
- Use caption notes to identify visual/caption patterns to favor or avoid, but only when the transcript or visual caption supports them.
- Lowercase everything.

Return ONLY this JSON, no commentary:
{{
  "add": {{
    "highlight_words": [...],
    "hype_phrases": [...],
    "penalized_words": [...],
    "background_words": [...],
    "low_energy_patterns": [...]
  }},
  "remove": {{
    "highlight_words": [...],
    "penalized_words": [...]
  }},
  "rationale": "one short sentence explaining the most important change"
}}

Omit any field you have no suggestions for. Do not wrap the JSON in markdown fences."""


# =============================================================================
# Ollama call
# =============================================================================

def _call_ollama(prompt: str, model: str) -> str | None:
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",   # force structured output
        "options": {"temperature": 0.2},
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_GENERATE,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            body = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        log.warning(f"Ollama call failed: {e}")
        return None
    return (body.get("response") or "").strip()


def _call_gemini(prompt: str) -> str | None:
    """Try the same Gemini keys the rest of the app uses. Returns None if no
    key is configured or every key fails, so the caller can fall back to Ollama."""
    try:
        from modules.clip_judge import _load_gemini_keys
        keys = _load_gemini_keys()
    except Exception as e:  # noqa: BLE001
        log.debug(f"no gemini keys: {e}")
        return None
    if not keys:
        return None

    from google import genai
    from google.genai import types

    for key in keys:
        try:
            # Must bind the client to a name before calling .models.generate_content —
            # chaining it inline lets the SDK's httpx transport get torn down mid-request
            # ("Cannot send a request, as the client has been closed").
            client = genai.Client(api_key=key)
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
            return (resp.text or "").strip()
        except Exception as e:  # noqa: BLE001
            blob = str(e).lower()
            if "429" in blob or "resource_exhausted" in blob or "quota" in blob:
                log.warning(f"gemini key exhausted, rotating: {e}")
                continue
            log.warning(f"Gemini tuner call failed: {e}")
            break
    return None


def _call_llm(prompt: str, ollama_model: str) -> str | None:
    """Prefer Gemini (already configured elsewhere in the app); fall back to the
    local Ollama model only if no Gemini key works. This is what was actually
    broken: DEFAULT_MODEL (qwen2.5-coder:7b) was never pulled locally, so every
    Ollama call 404'd and the tuner silently had nothing to show."""
    text = _call_gemini(prompt)
    if text:
        return text
    return _call_ollama(prompt, ollama_model)


# =============================================================================
# Patch parsing + sanitation
# =============================================================================

def _sanitize_patch(raw: dict, profile: dict) -> dict:
    """
    Clean up the LLM's suggestion: drop unknown keys, drop empty entries,
    drop suggestions that are already in the profile, lowercase strings.
    """
    valid_keys = set(EDITABLE_LISTS) | set(EDITABLE_DICT_LISTS)
    clean = {"add": {}, "remove": {}, "rationale": str(raw.get("rationale", ""))[:240]}

    def _existing(key):
        items = profile.get(key, []) or []
        if key in EDITABLE_DICT_LISTS:
            kf = EDITABLE_DICT_LISTS[key]["key_field"]
            return {(i.get(kf) if isinstance(i, dict) else i) for i in items}
        return set(items)

    for op in ("add", "remove"):
        bucket = raw.get(op) or {}
        if not isinstance(bucket, dict):
            continue
        for key, vals in bucket.items():
            if key not in valid_keys or not isinstance(vals, list):
                continue
            existing = _existing(key)
            cleaned_vals = []
            for v in vals:
                if not isinstance(v, str):
                    continue
                s = v.strip().lower()
                if not s or len(s) > 60:
                    continue
                # Adds: skip anything already present.
                # Removes: skip anything NOT present (model hallucinated it).
                if op == "add" and s in existing:
                    continue
                if op == "remove" and s not in existing:
                    continue
                cleaned_vals.append(s)
            if cleaned_vals:
                # Dedupe while preserving order.
                seen = set()
                unique = [x for x in cleaned_vals if not (x in seen or seen.add(x))]
                clean[op][key] = unique[:6]  # cap per category
    return clean


# =============================================================================
# Public API
# =============================================================================

# =============================================================================
# Review-driven prompt — LLM reads what the user wrote and extracts both
# concrete profile edits AND free-form context rules. The context rules can
# describe conditional behavior the flat profile can't represent (e.g.
# "silence during horror games is clippable, not dead air") — they get
# appended to data/user_notes.md so the chat LLM and the next tuner run see
# them as part of the user's standing instructions.
# =============================================================================

def _format_review_for_prompt(review: dict, transcript: str = "") -> str:
    bits = [f"[{review.get('stem')}]"]
    rating = review.get("rating")
    if rating:
        bits.append(f"rating={rating}/5")
    verdict = review.get("verdict")
    if verdict and verdict != "undecided":
        bits.append(f"verdict={verdict}")
    reasons = review.get("reasons") or []
    if reasons:
        bits.append(f"reasons=[{', '.join(reasons)}]")
    if transcript:
        bits.append(f"transcript=\"{transcript[:MAX_TRANSCRIPT_CHARS]}\"")
    notes = (review.get("notes") or "").strip()
    if notes:
        bits.append(f"USER NOTE: \"{notes[:600]}\"")
    cap = (review.get("caption_notes") or "").strip()
    if cap:
        bits.append(f"CAPTION NOTE: \"{cap[:300]}\"")
    return "  " + " | ".join(bits)


def _build_review_prompt(profile: dict,
                         reviews: list[dict],
                         max_suggestions: int = 10) -> str:
    keys_doc = []
    for key, meta in EDITABLE_LISTS.items():
        keys_doc.append(f'  - "{key}": {meta["desc"]}')
    for key, meta in EDITABLE_DICT_LISTS.items():
        keys_doc.append(f'  - "{key}": {meta["desc"]}')
    keys_block = "\n".join(keys_doc)

    profile_slice = {
        k: profile.get(k, [])[:25]
        for k in list(EDITABLE_LISTS) + list(EDITABLE_DICT_LISTS)
    }

    # Pull each review's transcript if cached, so the model can ground the
    # user's note against the actual text.
    enriched = []
    for r in reviews:
        stem = r.get("stem", "")
        transcript = ""
        cache = paths.CLIP_TRANSCRIPTS_DIR / f"{stem}.txt"
        if cache.exists():
            try:
                transcript = cache.read_text(encoding="utf-8").strip()
            except Exception:
                transcript = ""
        enriched.append(_format_review_for_prompt(r, transcript))
    reviews_block = "\n".join(enriched)

    return f"""You are tuning a clipping pipeline based on the streamer's own review notes.

The streamer reviews each clip with: a rating (1-5), a verdict (keeper/maybe/miss), reason chips, and FREE-TEXT NOTES explaining exactly why the clip is good or bad. Your job is to translate those notes into concrete changes to the pipeline so the same mistake stops happening (or the same kind of good clip happens more often).

The profile is a set of flat word/phrase lists you can edit:
{keys_block}

Current profile (truncated):
```json
{json.dumps(profile_slice, indent=2)}
```

RECENT REVIEWS (read the USER NOTE carefully — that's the streamer's direct feedback):
{reviews_block}

Your task — produce two kinds of output:

(A) PROFILE PATCHES — things you can map to the flat lists above. Examples of what to look for in the notes:
  - The user mentions a slang word the clipper missed → add to "highlight_words" (and maybe "hype_phrases" if multi-word).
  - The user complains about a phrase being clipped wrongly → add to "penalized_words" or "background_words".
  - The user describes a low-energy pattern that wastes clip slots → add to "low_energy_patterns".

(B) CONTEXT RULES — natural-language rules the flat profile cannot express, like "when I play horror games, silent running is clippable" or "my catchphrase 'standby' means I'm backup support, treat it as a setup signal". These go into a long-term instructions file the system reads on every clipping run.

Hard rules:
- Only suggest words/phrases that are actually grounded in the notes or transcripts above. No invention.
- Lowercase everything in add/remove lists. Keep entries short (1-3 words for highlight_words, up to 6 for hype_phrases).
- Don't add anything already in the current profile.
- At most {max_suggestions} total patch items across all lists.
- At most 8 context rules. Each rule must be one short sentence stating a condition and an action.
- If a note is too vague to act on, ignore it.

Return ONLY this JSON (no markdown fences, no commentary):
{{
  "add": {{
    "highlight_words":     [...],
    "hype_phrases":        [...],
    "penalized_words":     [...],
    "background_words":    [...],
    "low_energy_patterns": [...]
  }},
  "remove": {{
    "highlight_words": [...],
    "penalized_words": [...]
  }},
  "context_rules": [
    "When the user is playing a horror game, do not treat silent running as dead air.",
    "Treat 'standby' as a setup catchphrase meaning the user is acting as backup support."
  ],
  "slang_glossary": {{
    "standby": "user is acting as backup support in a fight or game",
    "iceman": "self-given nickname signalling a reaction segment"
  }},
  "avoid_patterns": [
    "audio spike with no joke setup"
  ],
  "rationale": "one short sentence on the most important change"
}}

Omit any field with no suggestions. Do not wrap the JSON in markdown fences."""


def suggest_changes_from_reviews(model: str = DEFAULT_MODEL,
                                 max_reviews: int = 25,
                                 max_suggestions: int = 10) -> dict:
    """
    Review-driven tuner. Reads recent reviews (especially their free-text
    notes) and asks the LLM to translate them into:
      - profile patches (add/remove on the editable lists)
      - context_rules (free-form sentences appended to user_notes.md when applied)

    Returns the same shape as suggest_changes() plus a `context_rules` list
    and an `n_reviews` count. The frontend should preview and let the user
    approve via /profile/apply (which will both apply the patch AND persist
    context_rules to user_notes.md).
    """
    from modules.clip_reviews import list_reviews
    from utils.profile_editor import load_profile

    profile = load_profile()
    if not profile:
        raise RuntimeError("No profile to tune. Build a profile first.")

    reviews = [r for r in list_reviews(limit=max_reviews * 4)
               if (r.get("notes") or "").strip() or (r.get("caption_notes") or "").strip()
               or (r.get("verdict") in ("keeper", "miss"))]
    reviews = reviews[:max_reviews]
    if len(reviews) < 1:
        raise RuntimeError(
            "No reviews with notes/verdicts yet. Add a note to at least one clip review and retry."
        )

    log.info(f"Review-tuner: reading {len(reviews)} reviews with model {model}...")
    prompt = _build_review_prompt(profile, reviews, max_suggestions=max_suggestions)

    raw_text = _call_llm(prompt, model)
    if not raw_text:
        raise RuntimeError("LLM returned no response.")

    try:
        raw_patch = json.loads(raw_text)
    except json.JSONDecodeError as e:
        log.warning(f"JSON parse failed ({e}); attempting recovery.")
        first = raw_text.find("{")
        last = raw_text.rfind("}")
        if first >= 0 and last > first:
            raw_patch = json.loads(raw_text[first:last + 1])
        else:
            raise RuntimeError(f"LLM output wasn't JSON: {raw_text[:200]}")

    clean_patch = _sanitize_patch(raw_patch, profile)

    # Pull free-form sections (context rules, slang glossary, avoid patterns)
    # the sanitizer doesn't touch. These flow to clip_memory.md on apply, not
    # to the flat profile.
    def _clean_string_list(raw, max_len: int, cap: int) -> list[str]:
        if not isinstance(raw, list):
            return []
        seen = set()
        out: list[str] = []
        for item in raw:
            if not isinstance(item, str):
                continue
            text = item.strip()
            if not text or len(text) > max_len:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
            if len(out) >= cap:
                break
        return out

    clean_patch["context_rules"] = _clean_string_list(
        raw_patch.get("context_rules"), max_len=300, cap=8
    )
    clean_patch["avoid_patterns"] = _clean_string_list(
        raw_patch.get("avoid_patterns"), max_len=200, cap=6
    )

    # slang_glossary is a dict — clean keys + values, drop anything already
    # present in the profile's highlight_words (no point double-storing).
    raw_glossary = raw_patch.get("slang_glossary") or {}
    glossary: dict[str, str] = {}
    if isinstance(raw_glossary, dict):
        existing_highlights = {w.lower() for w in (profile.get("highlight_words") or []) if isinstance(w, str)}
        for word, meaning in raw_glossary.items():
            if not isinstance(word, str) or not isinstance(meaning, str):
                continue
            w = word.strip().lower()
            m = meaning.strip()
            if not w or not m or len(w) > 40 or len(m) > 240:
                continue
            glossary[w] = m
            if len(glossary) >= 12:
                break
    clean_patch["slang_glossary"] = glossary
    clean_patch["n_reviews"] = len(reviews)
    clean_patch["model"] = model

    add_total = sum(len(v) for v in clean_patch["add"].values())
    rem_total = sum(len(v) for v in clean_patch["remove"].values())
    log.info(
        f"Review-tuner: {add_total} adds, {rem_total} removals, "
        f"{len(clean_patch['context_rules'])} context rules, "
        f"{len(clean_patch['slang_glossary'])} slang, "
        f"{len(clean_patch['avoid_patterns'])} avoid patterns."
    )
    return clean_patch


# =============================================================================
# Persistence helpers — delegate to the clip_memory module so all writes go
# to data/clip_memory.md, the canonical AI memory file.
# =============================================================================

def append_context_rules(rules: list[str]) -> int:
    """Persist new conditional clipping rules to clip_memory.md."""
    from modules.clip_memory import append_context_rules as _impl
    return _impl(rules or [])


def append_learned_slang(glossary: dict[str, str]) -> int:
    """Persist slang word → meaning entries to clip_memory.md."""
    from modules.clip_memory import append_learned_slang as _impl
    return _impl(glossary or {})


def append_avoid_patterns(patterns: list[str]) -> int:
    """Persist patterns the user has flagged as never-clip."""
    from modules.clip_memory import append_avoid_patterns as _impl
    return _impl(patterns or [])


def suggest_changes(model: str = DEFAULT_MODEL,
                    good_samples_count: int = 12,
                    bad_samples_count: int = 12,
                    max_suggestions: int = 8) -> dict:
    """
    Returns a sanitized patch dict the GUI can preview / apply.
      {"add": {...}, "remove": {...}, "rationale": "...", "n_good": N, "n_bad": N}
    """
    from utils.profile_editor import load_profile

    profile = load_profile()
    if not profile:
        raise RuntimeError("No profile to tune. Build a profile first.")

    posted_good = _gather_posted_samples(good_samples_count)
    good = posted_good + _gather_samples(paths.OLD_CLIPS_DIR, good_samples_count)
    seen_names = set()
    good = [
        s for s in good
        if not (s.get("name") in seen_names or seen_names.add(s.get("name")))
    ][:good_samples_count]
    bad = _gather_samples(paths.OUTPUT_DIR / "notclips", bad_samples_count)
    if len(good) < 3 or len(bad) < 3:
        raise RuntimeError(
            f"Not enough cached clip transcripts (good={len(good)}, bad={len(bad)}). "
            "Train the quality classifier at least once so clip transcripts get cached, "
            "then retry."
        )

    log.info(f"Tuner: comparing {len(good)} good vs {len(bad)} bad with model {model}...")
    prompt = _build_prompt(profile, good, bad, max_suggestions=max_suggestions)

    raw_text = _call_llm(prompt, model)
    if not raw_text:
        raise RuntimeError("LLM returned no response.")

    try:
        raw_patch = json.loads(raw_text)
    except json.JSONDecodeError as e:
        # Last-ditch: try to extract the first {...} block.
        log.warning(f"JSON parse failed ({e}); attempting recovery.")
        first = raw_text.find("{")
        last = raw_text.rfind("}")
        if first >= 0 and last > first:
            raw_patch = json.loads(raw_text[first:last + 1])
        else:
            raise RuntimeError(f"LLM output wasn't JSON: {raw_text[:200]}")

    clean_patch = _sanitize_patch(raw_patch, profile)
    clean_patch["n_good"] = len(good)
    clean_patch["n_bad"] = len(bad)
    clean_patch["model"] = model

    add_total = sum(len(v) for v in clean_patch["add"].values())
    rem_total = sum(len(v) for v in clean_patch["remove"].values())
    log.info(f"Tuner: {add_total} adds, {rem_total} removals suggested.")
    return clean_patch


if __name__ == "__main__":
    import sys
    model = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    print(json.dumps(suggest_changes(model=model), indent=2))
