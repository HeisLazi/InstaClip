"""
Unified clip context provider that integrates all intelligence sources:
- Stream segment classification (react, gaming, etc.)
- Review-based quality scoring
- Streamer culture context (memes, slang, jokes)
- Facial recognition
- Audio/visual analysis
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from config import paths
from modules.stream_context import (
    detect_segment_type,
    get_segment_context,
    apply_context_boost,
    NAMIBIAN_CULTURE,
)

log = logging.getLogger("clip_context")


@dataclass
class ClipContext:
    """Complete context for making clipping decisions."""

    timestamp: float
    segment_type: str
    segment_confidence: float
    transcript: str
    quality_score: float | None
    face_score: float
    audio_energy: float
    # Enrichment
    relevant_memes: list[str]
    relevant_keywords: list[str]
    namibian_elements: list[str]
    vibe_boost: float
    good_clip_signals: list[str]
    # Metadata
    metadata: dict[str, Any]

    def __post_init__(self):
        # Apply context boosts
        has_namibian = any(
            elem.lower() in self.transcript.lower() for elem in self.namibian_elements
        )
        if self.quality_score is not None:
            self.quality_score = apply_context_boost(
                self.quality_score, self.segment_type, has_namibian
            )


def build_clip_context(
    timestamp: float,
    transcript: str,
    audio_energy: float,
    quality_score: float | None = None,
    face_score: float = 0.0,
    context_keywords: list[str] | None = None,
) -> ClipContext:
    """
    Build comprehensive clip context from available signals.
    """
    # Detect segment type
    segment_type, seg_confidence = detect_segment_type(
        transcript, audio_energy, context_keywords
    )

    # Get segment context
    seg_context = get_segment_context(segment_type, transcript)

    # Find Namibian cultural elements in transcript
    namibian_elements = []
    if transcript:
        text_lower = transcript.lower()
        for slang_word, meaning in NAMIBIAN_CULTURE["slang"].items():
            if slang_word.lower() in text_lower:
                namibian_elements.append(f"{slang_word} ({meaning})")
        for meme in NAMIBIAN_CULTURE["memes"]:
            if meme.lower() in text_lower:
                namibian_elements.append(meme)

    # Compile context
    context = ClipContext(
        timestamp=timestamp,
        segment_type=segment_type,
        segment_confidence=seg_confidence,
        transcript=transcript,
        quality_score=quality_score or 0.0,
        face_score=face_score,
        audio_energy=audio_energy,
        relevant_memes=seg_context.get("relevant_memes", []),
        relevant_keywords=seg_context.get("keywords", []),
        namibian_elements=namibian_elements,
        vibe_boost=seg_context.get("vibe_boost", 0.0),
        good_clip_signals=seg_context.get("good_clip_signals", []),
        metadata={
            "segment_context": seg_context,
            "namibian_context": NAMIBIAN_CULTURE,
        },
    )

    return context


def should_clip(context: ClipContext, thresholds: dict[str, float] | None = None) -> dict[str, Any]:
    """
    Determine if a moment should become a clip based on context.

    Returns dict with decision, reasoning, and score.
    """
    if thresholds is None:
        thresholds = {
            "quality": 0.60,
            "audio": 0.40,
            "face": 0.30,
            "combined": 0.50,
        }

    # Compile signals
    signals = {
        "quality_score": context.quality_score or 0.0,
        "audio_energy": context.audio_energy,
        "face_detection": context.face_score,
        "segment_confidence": context.segment_confidence,
        "vibe_boost": context.vibe_boost,
    }

    # Calculate combined score
    combined_score = (
        signals["quality_score"] * 0.35
        + signals["audio_energy"] * 0.25
        + signals["face_detection"] * 0.20
        + signals["segment_confidence"] * 0.10
        + signals["vibe_boost"] * 0.10
    )

    # Determine clippability
    reasons_to_clip = []
    reasons_to_skip = []

    if signals["quality_score"] >= thresholds["quality"]:
        reasons_to_clip.append(f"Quality: {signals['quality_score']:.2f}")

    if signals["audio_energy"] >= thresholds["audio"]:
        reasons_to_clip.append(f"Audio spike: {signals['audio_energy']:.2f}")

    if signals["face_detection"] >= thresholds["face"]:
        reasons_to_clip.append(f"Face: {signals['face_detection']:.2f}")

    # Cultural signals
    if context.namibian_elements:
        reasons_to_clip.append(f"Cultural: {', '.join(context.namibian_elements[:2])}")

    # Check for good clip signals
    matching_signals = [
        sig
        for sig in context.good_clip_signals
        if sig.lower() in context.transcript.lower()
    ]
    if matching_signals:
        reasons_to_clip.extend(matching_signals[:2])

    # Negative signals
    if signals["quality_score"] < 0.3:
        reasons_to_skip.append("Low quality score")

    if not context.transcript and signals["audio_energy"] < 0.3:
        reasons_to_skip.append("Silent moment")

    # Final decision
    should_clip_bool = (
        combined_score >= thresholds["combined"]
        or len(reasons_to_clip) >= 2
        or (context.segment_type != "unknown" and combined_score >= 0.45)
    )

    return {
        "should_clip": should_clip_bool,
        "combined_score": float(combined_score),
        "signals": signals,
        "reasons_to_clip": reasons_to_clip,
        "reasons_to_skip": reasons_to_skip,
        "segment_type": context.segment_type,
        "confidence": float(context.segment_confidence),
    }


def get_clip_improvement_suggestions(context: ClipContext) -> list[str]:
    """
    Give suggestions for what would make this into a better clip.
    """
    suggestions = []

    # Quality suggestions
    if context.quality_score and context.quality_score < 0.5:
        for sig in context.good_clip_signals:
            suggestions.append(f"Look for: {sig}")

    # Segment-specific suggestions
    patterns = {
        "react": [
            "Capture the peak facial reaction moment",
            "Include the audio reaction (gasp, laugh, exclamation)",
        ],
        "gaming": [
            "Wait for the play completion/outcome",
            "Include teammate/chat reactions",
        ],
        "chat": [
            "Let the punchline land completely",
            "Include the group's reaction",
        ],
        "irl": [
            "Capture genuine moment, not staged",
            "Include crowd/NPC reaction",
        ],
    }

    if context.segment_type in patterns:
        suggestions.extend(patterns[context.segment_type])

    # Cultural suggestions
    if not context.namibian_elements and context.segment_type != "unknown":
        suggestions.append("Bonus: Use local slang/memes for relatability")

    return suggestions
