"""
Clip Judge — taste-calibrated clip selection (test harness + first cut of the real judge).

What it does:
  Reads a VOD transcript, asks an LLM to find the moments *Lazi* would clip — judged
  against the taste rubric in data/clip_taste.md (NOT audio spikes) — and writes ranked
  picks with suggested in/out points and a one-line reason for each.

This is the calibration loop:
  1. run it on a stream you've already clipped by hand
  2. compare its picks to the clips you actually chose
  3. correct data/clip_taste.md where it's wrong
  4. re-run — it gets sharper each pass

Engines:
  --engine claude   (default)  Claude reads the transcript and selects moments. Fast, cheap,
                               the core "does it understand my taste" test. Needs ANTHROPIC key.
  --engine gemini              Gemini Flash *watches the actual video* around each candidate and
                               gives a visual verdict. Needs GEMINI key + the source VOD on disk.
  --engine both                Claude proposes from text, Gemini watches each pick to confirm.

Keys (either works):
  - env: ANTHROPIC_API_KEY / GEMINI_API_KEY (or GOOGLE_API_KEY)
  - file: data/ai_credentials.json  ->  {"anthropic_api_key": "...", "gemini_api_key": "..."}

Examples:
  python -m modules.clip_judge "2026-01-21 00-01-17 VOD" --engine claude
  python -m modules.clip_judge "2026-01-21 00-01-17 VOD" --engine claude --minutes 30
  python -m modules.clip_judge "data/transcripts/2026-01-21 00-01-17 VOD.json" --engine both
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from config import cfg, paths

log = logging.getLogger("clip_judge")

try:
    from utils.progress_events import emit as emit_progress  # routes to the job's WS channel
except Exception:  # standalone / no backend running
    def emit_progress(**_kw):
        pass

RUBRIC_PATH = paths.DATA_DIR / "clip_taste.md"
DEFAULT_CLAUDE_MODEL = "claude-opus-4-8"   # best judge; use claude-sonnet-4-6 for ~5x cheaper
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"  # 2.0-flash has 0 free-tier quota on some accounts; configurable via --gemini-model

# Per-call transcript window. Long streams are chunked so each call stays focused.
CHUNK_SECONDS = 720      # 12 min of transcript per Claude call
CHUNK_OVERLAP = 60       # carry 60s into the next chunk so bits on a boundary aren't lost
BOUNDARY_PRE_PAD_SECONDS = 2.0
BOUNDARY_POST_PAD_SECONDS = 4.0
BOUNDARY_COMPLETION_MAX_SECONDS = 12.0
BOUNDARY_PAUSE_SECONDS = 1.1


def _pad_candidate_window(
    start: float,
    end: float,
    transcript_end: float = 0.0,
    *,
    pre_seconds: float = BOUNDARY_PRE_PAD_SECONDS,
    post_seconds: float = BOUNDARY_POST_PAD_SECONDS,
):
    padded_start = max(0.0, start - max(0.0, pre_seconds))
    padded_end = end + max(0.0, post_seconds)
    if transcript_end > 0:
        padded_end = min(padded_end, transcript_end)
    return padded_start, padded_end


def _complete_candidate_end(
    target_end: float,
    segments: list[dict[str, Any]],
    transcript_end: float = 0.0,
    *,
    max_extension: float = BOUNDARY_COMPLETION_MAX_SECONDS,
    pause_seconds: float = BOUNDARY_PAUSE_SECONDS,
) -> tuple[float, str]:
    """Snap a padded clip end to the next sentence or natural transcript pause."""
    if not segments:
        return target_end, "no_transcript"

    hard_end = target_end + max(0.0, max_extension)
    if transcript_end > 0:
        hard_end = min(hard_end, transcript_end)

    ordered = sorted(segments, key=lambda segment: float(segment.get("start") or 0.0))
    start_index = next((
        index for index, segment in enumerate(ordered)
        if float(segment.get("start") or 0.0) - 0.05 <= target_end
        <= float(segment.get("end") or segment.get("start") or 0.0) + 0.05
    ), None)
    if start_index is None:
        return min(target_end, hard_end), "existing_pause"

    fallback = min(target_end, hard_end)
    for index in range(start_index, len(ordered)):
        segment = ordered[index]
        segment_end = float(segment.get("end") or segment.get("start") or 0.0)
        if segment_end > hard_end:
            break

        fallback = segment_end
        text = str(segment.get("text") or "").strip()
        if re.search(r"[.!?](?:[\"']+)?$", text):
            return segment_end, "sentence_end"

        next_start = hard_end
        if index + 1 < len(ordered):
            next_start = float(ordered[index + 1].get("start") or segment_end)
        if next_start - segment_end >= max(0.0, pause_seconds):
            return segment_end, "natural_pause"

    return fallback, "segment_boundary" if fallback > target_end else "extension_cap"


def _candidate_padding(pick: dict[str, Any]) -> tuple[float, float]:
    """Choose edit-safe handles based on how much surrounding context the bit needs."""
    clip_type = str(pick.get("clip_type") or "").lower()
    kind = str(pick.get("kind") or "").lower()
    description = " ".join(
        str(pick.get(key) or "").lower() for key in ("the_bit", "why")
    )

    if pick.get("needs_context") or kind.startswith("a_") or "setup" in kind:
        return 10.0, 14.0
    if clip_type in {"reaction", "music"} or any(
        word in description for word in ("music", "song", "track", "rapper", "reaction")
    ):
        return 8.0, 12.0
    if not bool(pick.get("compilation")):
        return 6.0, 10.0
    return 3.0, 7.0


# ---------------------------------------------------------------------------
# Keys + rubric
# ---------------------------------------------------------------------------

def _clipper_edition() -> bool:
    """Tester/clipper builds must never read local owner credentials — all cloud
    AI goes through the quota gateway (WS1 credential hygiene)."""
    return os.environ.get("INSTACLIP_EDITION", "").strip().lower() == "clipper"


def _load_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    creds = paths.DATA_DIR / "ai_credentials.json"
    if _clipper_edition():
        return {"anthropic": "", "gemini": ""}
    if creds.exists():
        try:
            data = json.loads(creds.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                keys.update({k: str(v) for k, v in data.items() if v})
        except (OSError, json.JSONDecodeError):
            pass
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or keys.get("anthropic_api_key")
    gemini_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
                  or keys.get("gemini_api_key") or keys.get("google_api_key"))
    return {"anthropic": anthropic_key or "", "gemini": gemini_key or ""}


def _load_gemini_keys() -> list[str]:
    """All Gemini keys, in priority order — supports multiple Google accounts so the
    judge can rotate to a fresh free-tier quota when one key 429s. Sources:
    data/ai_credentials.json "gemini_api_keys": ["...","..."] (list) and/or single
    "gemini_api_key"/"google_api_key"; env GEMINI_API_KEY / GOOGLE_API_KEY (may be
    comma-separated). Duplicates are dropped, order preserved."""
    out: list[str] = []

    def add(v):
        v = (str(v).strip() if v else "")
        if v and v not in out:
            out.append(v)

    if _clipper_edition():
        return []  # testers use the cloud gateway, never local keys

    creds = paths.DATA_DIR / "ai_credentials.json"
    if creds.exists():
        try:
            data = json.loads(creds.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # Any of these may be a single string OR a list of keys.
                for field in ("gemini_api_keys", "google_api_keys",
                              "gemini_api_key", "google_api_key"):
                    val = data.get(field)
                    if isinstance(val, list):
                        for v in val:
                            add(v)
                    elif val:
                        add(val)
        except (OSError, json.JSONDecodeError):
            pass
    for env in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        for part in (os.environ.get(env) or "").split(","):
            add(part)
    return out


def _load_rubric() -> str:
    parts: list[str] = []
    if RUBRIC_PATH.exists():
        parts.append(RUBRIC_PATH.read_text(encoding="utf-8"))
    else:
        parts.append("(no clip_taste.md found — judge on general comedic setup->payoff structure)")
    # Fold in the running-bits / slang memory if it exists, so callbacks get caught.
    try:
        from modules.clip_memory import read_memory_for_llm
        mem = read_memory_for_llm()
        if mem:
            parts.append("\n\n# Running bits / slang memory (for callbacks & bilingual jokes)\n" + mem)
    except Exception:
        pass
    # Human reviews are the freshest taste and boundary signal. Including them
    # here matters because the configured app pipeline uses this judge directly.
    try:
        from modules.clip_reviews import summarize_reviews_for_llm
        reviews = summarize_reviews_for_llm(max_keepers=8, max_misses=8)
        if reviews:
            parts.append("\n\n# Recent human clip reviews\n" + reviews)
    except Exception:
        pass
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Transcript loading + chunking
# ---------------------------------------------------------------------------

def _resolve_transcript(arg: str) -> Path:
    p = Path(arg)
    if p.exists() and p.suffix == ".json":
        return p
    # treat as a VOD name / stem
    stem = Path(arg).stem
    cand = paths.TRANSCRIPTS_DIR / f"{stem}.json"
    if cand.exists():
        return cand
    raise FileNotFoundError(
        f"No transcript for '{arg}'. Pass a transcript .json path, or a VOD whose transcript "
        f"is cached in {paths.TRANSCRIPTS_DIR}. Run the listener on the VOD first if missing."
    )


def _fmt_ts(sec: float) -> str:
    s = int(sec)
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _chunk(segments: list[dict], chunk_sec: int, overlap: int,
           start_sec: float, end_sec: Optional[float]) -> list[list[dict]]:
    segs = [s for s in segments if s.get("end", 0) >= start_sec
            and (end_sec is None or s.get("start", 0) <= end_sec)]
    if not segs:
        return []
    chunks: list[list[dict]] = []
    win_start = segs[0]["start"]
    cur: list[dict] = []
    for s in segs:
        if s["start"] - win_start > chunk_sec and cur:
            chunks.append(cur)
            # start next window `overlap` seconds back
            back = s["start"] - overlap
            cur = [x for x in cur if x["end"] >= back]
            win_start = cur[0]["start"] if cur else s["start"]
        cur.append(s)
    if cur:
        chunks.append(cur)
    return chunks


def _chunk_text(segs: list[dict]) -> str:
    lines = []
    for s in segs:
        t = (s.get("text") or "").strip()
        if t:
            lines.append(f"[{_fmt_ts(s['start'])}] {t}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Claude judge
# ---------------------------------------------------------------------------

_CLAUDE_SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "start timestamp H:MM:SS (include the setup)"},
                    "end": {"type": "string", "description": "end timestamp H:MM:SS (just after the payoff)"},
                    "the_bit": {"type": "string", "description": "one sentence naming the joke/payoff"},
                    "why": {"type": "string", "description": "why it lands for Lazi"},
                    "clip_type": {"type": "string"},
                    "confidence": {"type": "number"},
                    "compilation_only": {"type": "boolean"},
                    "needs_context": {"type": "boolean"},
                },
                "required": ["start", "end", "the_bit", "why", "clip_type",
                             "confidence", "compilation_only", "needs_context"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}

_CLAUDE_SYSTEM_TMPL = """You are Lazi's personal clip judge. Lazi is a Namibian streamer. Your only job is to find the moments in a stream transcript that Lazi would actually clip and post — judged against the taste rubric below, NOT by loudness or audio spikes.

Hard rules:
- A loud or repetitive moment is NOT a clip. There must be a setup -> payoff and the bit must land.
- Pick the in/out so the SETUP is included and it ends just after the payoff. Wrong boundaries ruin a good bit.
- Bilingual (Oshiwambo/Namlish) wordplay and callbacks to running bits are prime clips — use the memory.
- Be selective. A 2-3 hour stream usually has a handful of real clips, not dozens. Better to miss a weak one than pad the list. Sort best first.
- Timestamps are given as [H:MM:SS] at the start of each line; use them for start/end.

=== TASTE RUBRIC ===
{rubric}
=== END RUBRIC ===
"""


def judge_with_claude(transcript: dict, rubric: str, model: str,
                      start_sec: float, end_sec: Optional[float], key: str) -> list[dict]:
    import anthropic

    client = anthropic.Anthropic(api_key=key)
    segments = transcript.get("segments", [])
    chunks = _chunk(segments, CHUNK_SECONDS, CHUNK_OVERLAP, start_sec, end_sec)
    if not chunks:
        log.warning("No transcript segments in the requested range.")
        return []

    system = [{
        "type": "text",
        "text": _CLAUDE_SYSTEM_TMPL.format(rubric=rubric),
        "cache_control": {"type": "ephemeral"},  # rubric is reused across every chunk -> cache it
    }]

    all_picks: list[dict] = []
    for i, chunk in enumerate(chunks, 1):
        body = _chunk_text(chunk)
        if not body.strip():
            continue
        span = f"{_fmt_ts(chunk[0]['start'])}–{_fmt_ts(chunk[-1]['end'])}"
        print(f"  [claude] chunk {i}/{len(chunks)} ({span})…", flush=True)
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=8000,
                thinking={"type": "adaptive"},
                output_config={"effort": "high", "format": {"type": "json_schema", "schema": _CLAUDE_SCHEMA}},
                system=system,
                messages=[{"role": "user", "content":
                           f"Transcript window {span}. Find Lazi's clips:\n\n{body}"}],
            )
        except Exception as e:
            log.error(f"Claude call failed on chunk {i}: {e}")
            continue
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            picks = json.loads(text).get("clips", [])
        except json.JSONDecodeError:
            log.warning(f"chunk {i}: could not parse JSON")
            picks = []
        for p in picks:
            p["_chunk"] = i
            p["engine"] = "claude"
            all_picks.append(p)

    return _dedupe(all_picks)


def _to_sec(ts: Any) -> float:
    if isinstance(ts, (int, float)):
        return float(ts)
    try:
        parts = [int(x) for x in str(ts).split(":")]
    except ValueError:
        return 0.0
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts[-3], parts[-2], parts[-1]
    return h * 3600 + m * 60 + s


def _salvage_clips(text: str) -> list[dict]:
    """Recover complete clip objects from a truncated JSON response (Gemini cut off
    mid-array when it over-generated). Returns whatever full {...} objects parsed."""
    if not text:
        return []
    i = text.find("[")
    if i == -1:
        return []
    out, depth, start = [], 0, None
    for j in range(i, len(text)):
        ch = text[j]
        if ch == "{":
            if depth == 0:
                start = j
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    out.append(json.loads(text[start:j + 1]))
                except json.JSONDecodeError:
                    pass
                start = None
    return out


_DEDUPE_STOPWORDS = {
    "after", "before", "clip", "from", "into", "lazi", "reacts", "says",
    "that", "the", "this", "then", "with", "while", "where", "when",
}


def _pick_tokens(pick: dict) -> set[str]:
    text = " ".join(str(pick.get(key) or "") for key in ("the_bit", "why")).lower()
    return {
        token
        for token in re.findall(r"[a-z0-9']+", text)
        if len(token) > 2 and token not in _DEDUPE_STOPWORDS
    }


def _same_nearby_bit(pick: dict, other: dict, max_gap: float = 12.0) -> bool:
    ps, pe = _to_sec(pick.get("start")), _to_sec(pick.get("end"))
    qs, qe = _to_sec(other.get("start")), _to_sec(other.get("end"))
    gap = max(0.0, max(ps, qs) - min(pe, qe))
    if gap > max_gap:
        return False

    pick_type = str(pick.get("clip_type") or "").lower()
    other_type = str(other.get("clip_type") or "").lower()
    pick_kind = str(pick.get("kind") or "").lower()
    other_kind = str(other.get("kind") or "").lower()
    same_shape = bool(
        (pick_type and pick_type == other_type)
        or (pick_kind and pick_kind == other_kind)
    )
    if not same_shape:
        return False

    left, right = _pick_tokens(pick), _pick_tokens(other)
    if not left or not right:
        return False
    similarity = len(left & right) / len(left | right)
    return similarity >= 0.45


def _merge_duplicate_window(keeper: dict, duplicate: dict) -> None:
    keeper["start"] = min(_to_sec(keeper.get("start")), _to_sec(duplicate.get("start")))
    keeper["end"] = max(_to_sec(keeper.get("end")), _to_sec(duplicate.get("end")))
    keeper["needs_context"] = bool(
        keeper.get("needs_context") or duplicate.get("needs_context")
    )
    keeper["compilation"] = bool(
        keeper.get("compilation") and duplicate.get("compilation")
    )
    keeper["hazards"] = list(dict.fromkeys(
        list(keeper.get("hazards") or []) + list(duplicate.get("hazards") or [])
    ))
    keeper["merged_candidates"] = int(keeper.get("merged_candidates") or 1) + 1


def _dedupe(picks: list[dict]) -> list[dict]:
    """Consolidate duplicate windows while preserving distinct nearby one-liners."""
    out: list[dict] = []
    for p in sorted(picks, key=lambda x: float(x.get("confidence") or 0), reverse=True):
        ps, pe = _to_sec(p.get("start")), _to_sec(p.get("end"))
        for q in out:
            qs, qe = _to_sec(q.get("start")), _to_sec(q.get("end"))
            overlap = max(0, min(pe, qe) - max(ps, qs))
            strong_overlap = overlap > 0.5 * max(1, min(pe - ps, qe - qs))
            if strong_overlap or _same_nearby_bit(p, q):
                # Union the windows instead of dropping one. Review history shows
                # duplicate offset cuts often omit opposite sides of the same bit.
                _merge_duplicate_window(q, p)
                break
        else:
            out.append(p)
    out.sort(key=lambda x: float(x.get("confidence") or 0), reverse=True)
    return out


# ---------------------------------------------------------------------------
# Gemini judge (watches the actual video around a pick)
# ---------------------------------------------------------------------------

def _resolve_vod(transcript: dict) -> Optional[Path]:
    vp = transcript.get("vod_path")
    if vp and Path(vp).exists():
        return Path(vp)
    name = transcript.get("vod_name")
    if name:
        cand = Path(cfg.fetcher.local_vod_dir) / name
        if cand.exists():
            return cand
    return None


def _cut_window(vod: Path, start: float, end: float) -> Optional[Path]:
    dur = max(1.0, end - start)
    tmp = Path(tempfile.gettempdir()) / f"judge_{int(start)}_{int(end)}.mp4"
    cmd = ["ffmpeg", "-y", "-ss", str(round(start, 2)), "-i", str(vod),
           "-t", str(round(dur, 2)), "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "28", "-vf", "scale=-2:480", "-c:a", "aac", str(tmp)]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, timeout=180)
        return tmp if tmp.exists() else None
    except Exception as e:
        log.warning(f"window cut failed: {e}")
        return None


def gemini_watch(pick: dict, vod: Path, rubric: str, model: str, key: str) -> dict:
    from google import genai

    client = genai.Client(api_key=key)
    start, end = _to_sec(pick.get("start")), _to_sec(pick.get("end"))
    clip = _cut_window(vod, start, end)
    if not clip:
        return {"verdict": "error", "note": "could not cut window"}
    f = None
    try:
        f = client.files.upload(file=str(clip))
        # video files need to finish processing before use
        for _ in range(30):
            f = client.files.get(name=f.name)
            if getattr(f.state, "name", str(f.state)) == "ACTIVE":
                break
            time.sleep(1)
        prompt = (
            "You are watching a short stream clip. Using the taste guide below, say whether this is "
            "actually a good standalone clip to post. Reply as JSON: "
            '{"good_clip": true/false, "what_happens": "...", "lands": true/false, "note": "..."}\n\n'
            + rubric[:4000]
        )
        resp = client.models.generate_content(model=model, contents=[f, prompt])
        txt = (resp.text or "").strip().strip("`")
        if txt.startswith("json"):
            txt = txt[4:].strip()
        try:
            return json.loads(txt)
        except json.JSONDecodeError:
            return {"verdict": "raw", "note": txt[:300]}
    except Exception as e:
        return {"verdict": "error", "note": str(e)}
    finally:
        try:
            clip.unlink()
        except OSError:
            pass
        # Privacy hygiene (WS1): don't leave the user's clip sitting in Google's
        # Files store after judging — delete the remote upload best-effort.
        if f is not None:
            try:
                client.files.delete(name=f.name)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _print_report(picks: list[dict], transcript: dict) -> None:
    print("\n" + "=" * 78)
    print(f"JUDGE PICKS — {transcript.get('vod_name', '?')}  ({len(picks)} clips)")
    print("=" * 78)
    if not picks:
        print("No clips found. If that's wrong, the rubric is too strict — loosen data/clip_taste.md.")
        return
    for i, p in enumerate(picks, 1):
        conf = float(p.get("confidence") or 0)
        flags = []
        if p.get("compilation_only"):
            flags.append("comp-only")
        if p.get("needs_context"):
            flags.append("needs-context")
        g = p.get("gemini")
        flag_str = f"  [{', '.join(flags)}]" if flags else ""
        print(f"\n[{i}] {p.get('start')}–{p.get('end')}  conf {conf:.2f}  ({p.get('clip_type','?')}){flag_str}")
        print(f"    bit: {p.get('the_bit','')}")
        print(f"    why: {p.get('why','')}")
        if g:
            print(f"    gemini: good={g.get('good_clip')} lands={g.get('lands')} — {g.get('what_happens', g.get('note',''))[:120]}")
    print("\n" + "=" * 78)


def run(arg: str, engine: str, claude_model: str, gemini_model: str,
        start_min: float, minutes: Optional[float], gemini_top: int) -> None:
    keys = _load_keys()
    rubric = _load_rubric()
    tpath = _resolve_transcript(arg)
    transcript = json.loads(tpath.read_text(encoding="utf-8"))
    start_sec = start_min * 60
    end_sec = None if minutes is None else start_sec + minutes * 60

    picks: list[dict] = []

    if engine in ("claude", "both"):
        if not keys["anthropic"]:
            print("ERROR: no Anthropic key. Set ANTHROPIC_API_KEY or add it to data/ai_credentials.json.")
            sys.exit(1)
        print(f"Judging with Claude ({claude_model})…")
        picks = judge_with_claude(transcript, rubric, claude_model, start_sec, end_sec, keys["anthropic"])

    if engine == "gemini" and not picks:
        # Pure-gemini mode still needs candidate windows; without Claude we can't propose them yet,
        # so gemini mode currently verifies Claude's picks. Fall back to claude proposal.
        print("Gemini mode watches candidate windows. Proposing candidates with Claude first…")
        if not keys["anthropic"]:
            print("ERROR: need an Anthropic key to propose candidates for Gemini to watch.")
            sys.exit(1)
        picks = judge_with_claude(transcript, rubric, claude_model, start_sec, end_sec, keys["anthropic"])

    if engine in ("gemini", "both"):
        if not keys["gemini"]:
            print("ERROR: no Gemini key. Set GEMINI_API_KEY or add it to data/ai_credentials.json.")
            sys.exit(1)
        vod = _resolve_vod(transcript)
        if not vod:
            print(f"WARN: source VOD not found (looked at vod_path + {cfg.fetcher.local_vod_dir}). "
                  f"Skipping Gemini visual pass.")
        else:
            for p in picks[:gemini_top]:
                print(f"  [gemini] watching {p.get('start')}–{p.get('end')}…", flush=True)
                p["gemini"] = gemini_watch(p, vod, rubric, gemini_model, keys["gemini"])

    _print_report(picks, transcript)

    out = paths.METADATA_DIR / f"{tpath.stem}_judge.json"
    out.write_text(json.dumps({"vod": transcript.get("vod_name"), "engine": engine,
                               "claude_model": claude_model, "picks": picks}, indent=2),
                   encoding="utf-8")
    print(f"\nSaved picks -> {out}")
    print("Next: compare these to the clips you actually made, then correct data/clip_taste.md and re-run.")


def _print_review(picks: list[dict]) -> None:
    print("\n" + "=" * 78)
    print("GEMINI VIDEO REVIEW (eyes on the actual clip)")
    print("=" * 78)
    for i, p in enumerate(picks, 1):
        g = p.get("gemini") or {}
        print(f"\n[{i}] {p.get('start')}-{p.get('end')}  ({p.get('clip_type','?')})")
        print(f"    claude bit: {p.get('the_bit','')}")
        if g:
            print(f"    gemini:     good_clip={g.get('good_clip')}  lands={g.get('lands')}")
            wh = str(g.get('what_happens', '') or '')
            if wh:
                print(f"                sees: {wh[:220]}")
            if g.get('note'):
                print(f"                note: {str(g.get('note'))[:220]}")
    print("\n" + "=" * 78)


def run_review(judge_path: str, gemini_model: str, gemini_top: int) -> None:
    """Load a saved *_judge.json and have Gemini WATCH each pick. No Anthropic key needed."""
    keys = _load_keys()
    if not keys["gemini"]:
        print("ERROR: no Gemini key. Put it in data/ai_credentials.json as "
              '{"gemini_api_key": "..."} or set GEMINI_API_KEY.')
        sys.exit(1)
    jp = Path(judge_path)
    if not jp.exists():
        print(f"ERROR: judge file not found: {jp}")
        sys.exit(1)
    data = json.loads(jp.read_text(encoding="utf-8"))
    picks = data.get("picks", [])
    if not picks:
        print("No picks in judge file.")
        sys.exit(1)
    rubric = _load_rubric()

    vod_name = data.get("vod")
    vod = None
    if vod_name:
        cand = Path(cfg.fetcher.local_vod_dir) / vod_name
        if cand.exists():
            vod = cand
        else:
            tcand = paths.TRANSCRIPTS_DIR / f"{Path(vod_name).stem}.json"
            if tcand.exists():
                try:
                    t = json.loads(tcand.read_text(encoding="utf-8"))
                    vp = t.get("vod_path")
                    if vp and Path(vp).exists():
                        vod = Path(vp)
                except (OSError, json.JSONDecodeError):
                    pass
    if not vod:
        print(f"ERROR: source VOD '{vod_name}' not found in {cfg.fetcher.local_vod_dir}. "
              f"Gemini needs the actual video file to watch.")
        sys.exit(1)

    print(f"Gemini ({gemini_model}) watching {min(gemini_top, len(picks))} pick(s) from {vod.name}…")
    for p in picks[:gemini_top]:
        print(f"  [gemini] {p.get('start')}-{p.get('end')}: cutting window + uploading…", flush=True)
        p["gemini"] = gemini_watch(p, vod, rubric, gemini_model, keys["gemini"])

    jp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _print_review(picks)
    print(f"\nUpdated with Gemini verdicts -> {jp}")


# ---------------------------------------------------------------------------
# APP SELECTION ENGINE — taste-judge replacement for clip_engine.find_highlights
# Gemini judges the transcript against data/clip_taste.md and OVER-SELECTS (stage 1).
# Returns highlights in the exact dict shape the cutter expects, so it drops into
# main.run_pipeline behind a settings flag. No Anthropic key needed.
# ---------------------------------------------------------------------------

# Gemini's response_schema is an OpenAPI subset — no "additionalProperties".
_SELECT_SCHEMA = {
    "type": "object",
    "properties": {"clips": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "start": {"type": "string"}, "end": {"type": "string"},
            "the_bit": {"type": "string"}, "why": {"type": "string"},
            "kind": {"type": "string"}, "clip_type": {"type": "string"},
            "confidence": {"type": "number"}, "compilation": {"type": "boolean"},
            "needs_context": {"type": "boolean"},
            "hazards": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["start", "end", "the_bit", "clip_type", "confidence", "compilation"],
    }}},
    "required": ["clips"],
}


def select_highlights(transcript: dict, vod_path) -> list[dict]:
    """App selection engine. Gemini over-selects clip/meme candidates from the
    transcript against data/clip_taste.md, returns cutter-format highlights."""
    vod_path = Path(vod_path)
    if os.environ.get("INSTACLIP_EDITION", "full").lower() == "clipper":
        from modules.tester_gateway import select_highlights as select_for_tester
        return select_for_tester(transcript, vod_path)
    gkeys = _load_gemini_keys()
    if not gkeys:
        log.error("clip_judge.select_highlights: no Gemini key (data/ai_credentials.json). Returning [].")
        return []
    from google import genai
    from google.genai import types

    clients = [genai.Client(api_key=k) for k in gkeys]
    ki = 0  # index of the key currently in use; rotates forward on a 429
    rubric = _load_rubric()
    segments = transcript.get("segments", [])
    chunks = _chunk(segments, CHUNK_SECONDS, CHUNK_OVERLAP, 0, None)
    sys_txt = (
        "You are Lazi's clip judge. Read this stream transcript and OVER-SELECT generously (Stage 1 — never "
        "miss a clip or meme-able moment) per the taste rubric below. For each candidate give H:MM:SS start/end "
        "that INCLUDE the full setup, the completing line, and the immediate reaction after the payoff. Never "
        "end mid-word, mid-sentence, or directly before the joke lands. A slightly long candidate is safer than "
        "a clipped punchline because later editing can tighten it. Give a one-sentence the_bit, why it lands, "
        "kind (A_setup_payoff | "
        "B_one_liner | meme), clip_type, confidence 0-1, compilation (true if a short one-liner meant to be "
        "merged), and hazards. Be liberal — trimming happens later. BUT: do NOT surface pure logistics / "
        "dead-air (camera/wifi/mic problems, 'is it lagging', waiting for people, cam toggling) — those are "
        "never clips. And don't shred one continuous bit into many 2-second fragments: when consecutive lines "
        "are the SAME joke/beat, return ONE candidate spanning the whole thing. Set needs_context=true when "
        "the selected line depends on an earlier setup, source video/music, chat message, game outcome, or a "
        "later payoff. For music/reaction clips, include enough of the source content BEFORE the reaction to "
        "show what caused it and continue AFTER it until the opinion/reaction resolves. Compilation=true is "
        "an output format, not a low-quality label. Before choosing the end, inspect the following transcript "
        "lines and include any completing tag, laugh, result, correction, or immediate response.\n\n"
        "=== TASTE RUBRIC ===\n" + rubric
    )
    log.info(f"clip_judge: judging {len(chunks)} segments with {len(gkeys)} Gemini key(s).")

    picks: list[dict] = []
    for i, chunk in enumerate(chunks, 1):
        body = _chunk_text(chunk)
        if not body.strip():
            continue
        emit_progress(stage="judging", message=f"Judging segment {i}/{len(chunks)} (key {ki + 1}/{len(gkeys)})")
        placed = False
        overload_tries = 0   # 503/500 transient-overload retries on the current key
        while ki < len(clients) and not placed:
            # First try the primary model; after an overload, fall back to -latest.
            model = DEFAULT_GEMINI_MODEL if overload_tries == 0 else "gemini-flash-latest"
            try:
                r = clients[ki].models.generate_content(
                    model=model,
                    contents=[sys_txt + "\n\n=== TRANSCRIPT ===\n" + body],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=_SELECT_SCHEMA, max_output_tokens=32000),
                )
                try:
                    chunk_clips = json.loads(r.text).get("clips", [])
                except json.JSONDecodeError:
                    chunk_clips = _salvage_clips(r.text or "")
                    log.warning(f"chunk {i}: response truncated — salvaged {len(chunk_clips)} clips.")
                picks += chunk_clips
                placed = True
            except Exception as e:
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    log.warning(f"Gemini key {ki + 1}/{len(gkeys)} quota hit — rotating to next key.")
                    ki += 1            # retry THIS chunk on the next account's quota
                    overload_tries = 0
                    continue
                if "503" in msg or "500" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower():
                    overload_tries += 1
                    if overload_tries <= 5:
                        time.sleep(min(2 ** overload_tries, 24))  # backoff, then retry (w/ fallback model)
                        continue
                    log.warning(f"select chunk {i}: model overloaded after {overload_tries} tries — skipping.")
                    break
                log.warning(f"select chunk {i} failed: {msg[:100]}")
                break  # other error: skip this chunk, keep the current key
        if ki >= len(clients):
            log.warning(f"All {len(gkeys)} Gemini keys exhausted — returning {len(picks)} candidates so far.")
            break

    picks = _dedupe(picks)
    highlights: list[dict] = []
    transcript_end = max((float(segment.get("end") or 0) for segment in segments), default=0.0)
    for p in picks:
        selected_start, selected_end = _to_sec(p.get("start")), _to_sec(p.get("end"))
        if selected_end <= selected_start:
            continue
        # Recent reviews repeatedly identify good moments whose final word or
        # payoff was clipped. Preserve a small edit-safe margin around the LLM's
        # proposed window; the editor can tighten it later without losing source.
        pre_pad, post_pad = _candidate_padding(p)
        s, e = _pad_candidate_window(
            selected_start,
            selected_end,
            transcript_end,
            pre_seconds=pre_pad,
            post_seconds=post_pad,
        )
        padded_end = e
        e, completion_reason = _complete_candidate_end(e, segments, transcript_end)
        conf = float(p.get("confidence") or 0)
        highlights.append({
            "start": round(s, 3), "end": round(e, 3), "duration": round(e - s, 3),
            "peak_time": round(selected_start, 3), "peak_score": round(conf, 4),
            "final_score": round(conf, 4), "quality_score": round(conf, 4),
            "peak_text": p.get("the_bit", ""), "why": p.get("why", ""),
            "clip_type": p.get("clip_type", ""), "kind": p.get("kind", ""),
            "compilation": bool(p.get("compilation")),
            "needs_context": bool(p.get("needs_context")),
            "triggers": [t for t in (p.get("kind"), p.get("clip_type")) if t] or ["judge"],
            "hazard_flags": list(p.get("hazards") or []),
            "peak_signals": {},
            "judge_window": {
                "start": round(selected_start, 3),
                "end": round(selected_end, 3),
            },
            "boundary_handles": {
                "pre_seconds": pre_pad,
                "post_seconds": post_pad,
                "completion_extension_seconds": round(max(0.0, e - padded_end), 3),
                "completion_reason": completion_reason,
            },
        })
    highlights.sort(key=lambda h: h["final_score"], reverse=True)
    for i, h in enumerate(highlights):
        h["clip_id"] = f"{vod_path.stem}_{i + 1:03d}"
        h["vod_name"] = vod_path.name

    try:
        from utils.file_utils import save_json
        save_json({"vod": vod_path.name, "engine": "judge", "highlights": highlights},
                  paths.METADATA_DIR / f"{vod_path.stem}_highlights.json")
    except Exception:
        pass
    log.info(f"clip_judge.select_highlights: over-selected {len(highlights)} candidates.")
    return highlights


if __name__ == "__main__":
    try:  # Windows consoles default to cp1252; transcripts have →, —, emoji, etc.
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Taste-calibrated clip judge (test harness).")
    ap.add_argument("vod", nargs="?", help="VOD name / stem, or path to a transcript .json")
    ap.add_argument("--review", help="Path to a saved *_judge.json; Gemini watches each pick (no Anthropic key needed)")
    ap.add_argument("--engine", choices=["claude", "gemini", "both"], default="claude")
    ap.add_argument("--model", dest="claude_model", default=DEFAULT_CLAUDE_MODEL,
                    help="Claude model id (default claude-opus-4-8; claude-sonnet-4-6 is ~5x cheaper)")
    ap.add_argument("--gemini-model", default=DEFAULT_GEMINI_MODEL)
    ap.add_argument("--start-min", type=float, default=0.0, help="start N minutes into the VOD")
    ap.add_argument("--minutes", type=float, default=None,
                    help="only judge this many minutes (cheap first test, e.g. --minutes 30)")
    ap.add_argument("--gemini-top", type=int, default=8,
                    help="how many top picks Gemini watches (cost control)")
    a = ap.parse_args()
    if a.review:
        run_review(a.review, a.gemini_model, a.gemini_top)
    elif a.vod:
        run(a.vod, a.engine, a.claude_model, a.gemini_model, a.start_min, a.minutes, a.gemini_top)
    else:
        ap.error("provide a VOD/transcript, or --review <judge.json>")
