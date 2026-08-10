"""AI-assisted boundary suggestions for compilation clips."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from modules import editor
from modules.clip_judge import _load_gemini_keys

log = logging.getLogger("compilation")

_TRIM_SCHEMA = {
    "type": "object",
    "properties": {
        "start": {"type": "number"},
        "end": {"type": "number"},
        "reason": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["start", "end", "reason", "confidence"],
}


def _full_clip(source: Path, duration: float, reason: str) -> dict[str, Any]:
    return {
        "stem": source.stem,
        "start": 0.0,
        "end": round(duration, 3),
        "reason": reason,
        "confidence": 0.0,
        "method": "full_clip",
    }


def suggest_payoff_trim(source: Path) -> dict[str, Any]:
    """Watch a short clip and suggest boundaries that preserve setup and payoff."""
    info = editor.probe(source)
    duration = float(info.get("duration") or 0.0)
    if duration <= 0:
        raise ValueError("clip duration is 0")
    if duration <= 4.5:
        return _full_clip(source, duration, "Already short; trimming risks cutting the line.")

    keys = _load_gemini_keys()
    if not keys:
        return _full_clip(source, duration, "No Gemini key is configured, so the original boundaries were kept.")

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return _full_clip(source, duration, "google-genai is not installed, so the original boundaries were kept.")

    prompt = f"""
Watch this {duration:.2f}-second streamer clip and tighten it for a fast compilation.
Return one start and end timestamp in seconds. Preserve the minimum setup needed to
understand the bit, include the full punchline/payoff/joke, and end 0.4-1.0 seconds
after the final spoken or visible reaction. Never cut a word, sentence, laugh, or
reaction in half. Remove only genuine dead air or trailing material after the bit.
If the clip cannot be shortened safely, return start 0 and end {duration:.3f}.
""".strip()

    last_error: Exception | None = None
    for key_index, key in enumerate(keys):
        client = genai.Client(api_key=key)
        uploaded = None
        try:
            uploaded = client.files.upload(file=str(source))
            for _ in range(60):
                uploaded = client.files.get(name=uploaded.name)
                state = getattr(uploaded.state, "name", str(uploaded.state))
                if state == "ACTIVE":
                    break
                if state == "FAILED":
                    raise RuntimeError("Gemini could not process the clip")
                time.sleep(1)
            else:
                raise TimeoutError("Gemini video processing timed out")

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[uploaded, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_TRIM_SCHEMA,
                    max_output_tokens=1000,
                ),
            )
            suggestion = json.loads(response.text or "{}")
            start = max(0.0, min(duration - 0.5, float(suggestion.get("start") or 0.0)))
            end = max(start + 0.5, min(duration, float(suggestion.get("end") or duration)))
            if end - start < 2.0:
                return _full_clip(source, duration, "AI suggestion was too short to preserve context.")
            return {
                "stem": source.stem,
                "start": round(start, 3),
                "end": round(end, 3),
                "reason": str(suggestion.get("reason") or "Tightened around the setup and payoff.")[:500],
                "confidence": max(0.0, min(1.0, float(suggestion.get("confidence") or 0.0))),
                "method": "gemini_video",
            }
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            message = str(exc).lower()
            if "429" in message or "resource_exhausted" in message or "quota" in message:
                log.warning("Compilation trim key %s/%s exhausted; rotating.", key_index + 1, len(keys))
                continue
            log.warning("Compilation trim suggestion failed: %s", exc)
            break
        finally:
            if uploaded is not None:
                try:
                    client.files.delete(name=uploaded.name)
                except Exception:  # noqa: BLE001
                    pass

    reason = "AI trim failed; the original boundaries were kept."
    if last_error:
        reason = f"{reason} {str(last_error)[:180]}"
    return _full_clip(source, duration, reason)
