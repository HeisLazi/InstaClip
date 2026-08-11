"""
Hazard detection for clip segments.

Soft-flag only — never multiplies the score. Returns a list of hazard tags
which the engine attaches to the segment dict as `hazard_flags`, so the UI
can show them and the user can filter manually.

Hazard categories cover the negative-constraint vectors from the cultural
research doc (TOS substances, political debate, DYK-style interpersonal
schisms, dead air, DMCA-risk background music).
"""

from modules.streamer_lexicon import HAZARD_PHRASES

# Detector returns this many flags max per segment to keep metadata small.
MAX_FLAGS_PER_SEGMENT = 4


def _phrase_hits(text_lower: str, phrases) -> bool:
    return any(p in text_lower for p in phrases)


def detect_text_hazards(text: str) -> list[str]:
    """
    Return hazard category labels found in transcript text.
    """
    if not text:
        return []
    lower = text.lower()
    flags = []
    for category, phrases in HAZARD_PHRASES.items():
        if _phrase_hits(lower, phrases):
            flags.append(category)
    return flags[:MAX_FLAGS_PER_SEGMENT]


def detect_dead_air(audio_energy: float, audio_spike: float, text: str,
                    energy_threshold: float = 0.05) -> bool:
    """
    Dead air = no transcript, no spike, low overall energy.
    """
    if text and text.strip():
        return False
    return audio_energy < energy_threshold and audio_spike < 0.1


def detect_dmca_risk(audio_energy: float, text: str,
                     energy_threshold: float = 0.35) -> bool:
    """
    Heuristic: meaningful background audio but no speech / reaction in the
    transcript. Strong signal for background commercial music with no fair-use
    reaction context.
    """
    if not text or len(text.strip()) < 6:
        return audio_energy >= energy_threshold
    return False


def detect_intoxication_acoustic(text: str) -> bool:
    """
    Lightweight intoxication hint based on transcript phrasing.
    The doc calls for slurred-speech acoustic detection too; that's
    out of scope here without an additional model, so we ship the
    text-only signal and leave acoustic detection as a TODO.
    """
    if not text:
        return False
    return _phrase_hits(text.lower(), HAZARD_PHRASES["intoxication_hint"])


def detect_segment_hazards(segment: dict) -> list[str]:
    """
    Run all hazard detectors for a segment dict from clip_engine.
    Returns a deduped list of hazard labels (or empty list).

    Call site: clip_engine.score_segment, attach result as segment["hazard_flags"].
    """
    text = segment.get("text", "") or ""
    audio_energy = float(segment.get("audio_energy") or 0.0)
    audio_spike = float(segment.get("audio_spike") or 0.0)

    flags: list[str] = []
    flags.extend(detect_text_hazards(text))

    if detect_dead_air(audio_energy, audio_spike, text):
        flags.append("dead_air")

    if detect_dmca_risk(audio_energy, text):
        flags.append("dmca_risk")

    if detect_intoxication_acoustic(text):
        # Also covered by detect_text_hazards but we keep an explicit label.
        if "intoxication_hint" not in flags:
            flags.append("intoxication_hint")

    # Dedupe while preserving order.
    seen = set()
    out = []
    for f in flags:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out[:MAX_FLAGS_PER_SEGMENT]
