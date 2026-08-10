"""
Stream context provider for clipping intelligence.
Tracks segment types, streamer culture, and provides enriched context.
"""

import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from config import paths

log = logging.getLogger("stream_context")


@dataclass
class StreamSegment:
    """Represents a labeled stream segment."""
    start_sec: int
    end_sec: int
    segment_type: str  # "react", "gaming", "chat", "music", "irl", "creative"
    tags: list[str]
    notes: str = ""


STREAMER_CULTURE_KB = {
    # Reactions & emotions
    "reacts": {
        "keywords": ["reaction", "react", "responding", "watching", "checking out"],
        "memes": ["poggers", "no shot", "bro what", "ong that's crazy", "fr fr"],
        "vibe_boost": 0.15,
        "good_clip_signals": ["shocked expression", "genuine reaction", "funny take"],
    },
    "gaming": {
        "keywords": ["playing", "gaming", "ranked", "pub", "stream sniper", "clutch", "wipe"],
        "memes": ["gg", "tryhard", "sweaty", "one tap", " 200 IQ", "diffed"],
        "vibe_boost": 0.12,
        "good_clip_signals": ["clutch play", "funny death", "rage moment", "poggers moment"],
    },
    "just_chatting": {
        "keywords": ["talking", "discussion", "chat", "story", "telling", "explaining"],
        "memes": ["no cap", "deadass", "lowkey", "ngl", "fr no lie", "facts"],
        "vibe_boost": 0.10,
        "good_clip_signals": ["funny story", "spicy take", "viral moment", "crew jokes"],
    },
    "music": {
        "keywords": ["music", "song", "beat", "production", "singing", "performing"],
        "memes": ["fire", "slaps", "vibe", "groove", "bop", "heat"],
        "vibe_boost": 0.08,
        "good_clip_signals": ["flow moment", "beat drop", "unexpected turn"],
    },
    "irl": {
        "keywords": ["outside", "outside stream", "irl", "travel", "event", "convention"],
        "memes": ["touch grass", "bro went outside", "public W", "awkward"],
        "vibe_boost": 0.14,
        "good_clip_signals": ["public reaction", "genuine interaction", "unexpected"],
    },
    "creative": {
        "keywords": ["art", "design", "building", "coding", "creative", "making"],
        "memes": ["that's sick", "clean", "flow state", "big brain"],
        "vibe_boost": 0.09,
        "good_clip_signals": ["satisfying result", "creative flex", "problem solve"],
    },
}

# Namibian/Southern African culture & memes
NAMIBIAN_CULTURE = {
    "slang": {
        "bunda": "butt/back",
        "check": "look at",
        "jol": "party/fun time",
        "goon": "guy/person",
        "jawn": "girl/person",
        "shem": "shame/sympathy",
        "howzit": "hello",
        "yeah man": "agreement",
        "sharp sharp": "cool/alright",
        "ag": "expression of resignation",
    },
    "memes": [
        "boet (bro)",
        "lekker (cool/nice)",
        "braai (BBQ moment)",
        "yebo (yes)",
        "haibo (wow/shock)",
        "eish (frustration)",
        "stompie (cigarette butt)",
        "bakkie (pickup truck)",
        "ja nee (yes indeed)",
    ],
    "humor_styles": [
        "self-deprecating humor",
        "absurdist/random humor",
        "banter/roasting",
        "political/social commentary",
        "wholesome community jokes",
    ],
    "cultural_moments": [
        "load shedding references",
        "ubuntu philosophy moments",
        "township vibes",
        "apartheid legacy commentary",
        "family/community emphasis",
    ],
}

# Map what makes good clips per segment type
CLIP_QUALITY_PATTERNS = {
    "react": {
        "min_duration_sec": 8,
        "max_duration_sec": 45,
        "key_indicators": [
            "facial expression peak",
            "verbal exclamation",
            "body language reaction",
            "take/commentary",
        ],
        "avoid": [
            "watching in silence",
            "boring content source",
            "weak payoff",
        ],
    },
    "gaming": {
        "min_duration_sec": 5,
        "max_duration_sec": 60,
        "key_indicators": [
            "clutch/skilled moment",
            "funny death/failure",
            "high intensity audio",
            "reaction to play",
        ],
        "avoid": [
            "dead time gameplay",
            "boring walking",
            "silent grinding",
        ],
    },
    "chat": {
        "min_duration_sec": 15,
        "max_duration_sec": 120,
        "key_indicators": [
            "punchline/joke landing",
            "group laughter",
            "spicy take",
            "story climax",
        ],
        "avoid": [
            "rambling without payoff",
            "inside jokes only",
            "silent moments",
        ],
    },
    "irl": {
        "min_duration_sec": 8,
        "max_duration_sec": 90,
        "key_indicators": [
            "genuine public interaction",
            "unexpected moment",
            "crowd reaction",
            "authentic emotion",
        ],
        "avoid": [
            "awkward silence",
            "staged feels",
            "boring walking",
        ],
    },
}


def detect_segment_type(
    transcript: str, audio_energy_spike: float, context_keywords: list[str] | None = None
) -> tuple[str, float]:
    """
    Detect stream segment type from transcript and audio cues.
    Returns (segment_type, confidence).
    """
    if not transcript:
        return "unknown", 0.0

    text_lower = transcript.lower()
    context_keywords = context_keywords or []

    # Score each segment type
    scores = {}
    for seg_type, config in STREAMER_CULTURE_KB.items():
        score = 0.0
        # Check keywords
        for kw in config["keywords"]:
            if kw.lower() in text_lower:
                score += 0.3
        # Check memes
        for meme in config["memes"]:
            if meme.lower() in text_lower:
                score += 0.2
        # Boost if mentioned in context
        if seg_type in context_keywords:
            score += 0.5
        scores[seg_type] = score

    if not scores or max(scores.values()) < 0.3:
        return "unknown", 0.0

    best_type = max(scores, key=scores.get)
    confidence = min(scores[best_type] / 1.0, 1.0)
    return best_type, confidence


def get_segment_context(
    segment_type: str, transcript: str = ""
) -> dict[str, Any]:
    """
    Get enriched context for a stream segment.
    Includes: culture refs, memes, quality signals, vibe boost.
    """
    if segment_type not in STREAMER_CULTURE_KB:
        return {
            "segment_type": segment_type,
            "culture_context": NAMIBIAN_CULTURE,
            "vibe_boost": 0.0,
            "quality_patterns": {},
        }

    config = STREAMER_CULTURE_KB[segment_type]
    return {
        "segment_type": segment_type,
        "keywords": config["keywords"],
        "relevant_memes": config["memes"],
        "vibe_boost": config["vibe_boost"],
        "good_clip_signals": config["good_clip_signals"],
        "quality_patterns": CLIP_QUALITY_PATTERNS.get(segment_type, {}),
        "namibian_context": NAMIBIAN_CULTURE,
        "culture_context_applied": any(
            meme.lower() in transcript.lower() for meme in NAMIBIAN_CULTURE["slang"].keys()
        ) if transcript else False,
    }


def apply_context_boost(
    base_score: float, segment_type: str, has_namibian_elements: bool = False
) -> float:
    """Apply context-aware boosting to quality score."""
    if segment_type in STREAMER_CULTURE_KB:
        boost = STREAMER_CULTURE_KB[segment_type]["vibe_boost"]
        base_score = min(base_score + boost, 1.0)

    if has_namibian_elements:
        base_score = min(base_score + 0.05, 1.0)

    return base_score


def save_stream_segments(
    segments: list[StreamSegment], output_path: Path | None = None
) -> Path:
    """Save stream segment annotations."""
    if output_path is None:
        output_path = paths.DATA_DIR / "stream_segments.jsonl"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "a", encoding="utf-8") as f:
        for seg in segments:
            line = json.dumps(asdict(seg))
            f.write(line + "\n")

    log.info(f"Saved {len(segments)} stream segments to {output_path.name}")
    return output_path


def load_stream_segments(path: Path | None = None) -> list[StreamSegment]:
    """Load stream segment annotations."""
    if path is None:
        path = paths.DATA_DIR / "stream_segments.jsonl"

    if not path.exists():
        return []

    segments = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                seg = StreamSegment(**data)
                segments.append(seg)
            except (json.JSONDecodeError, TypeError) as e:
                log.warning(f"Failed to parse segment: {e}")

    return segments
