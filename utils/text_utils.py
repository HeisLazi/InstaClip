# =============================================================================
# utils/text_utils.py — Shared Text Processing Helpers (V2)
# =============================================================================
# Used by: profiler.py, clip_engine.py
# =============================================================================

import re
import logging
from collections import Counter

from config import cfg

log = logging.getLogger("utils.text")


def normalize_slang(text: str) -> str:
    """
    Apply slang dictionary before tokenizing.
    Replaces Whisper mishears and aliases with canonical forms.

    e.g. "bruh that was naah crazy" → "bro that was nah crazy"
    """
    words = text.lower().split()
    normalized = [cfg.profiler.slang_lookup.get(w, w) for w in words]
    return " ".join(normalized)


def clean_tokens(raw_text: str) -> list[str]:
    """
    Full V2 text cleaning pipeline:
    1. Normalize slang aliases
    2. Lowercase
    3. Strip punctuation
    4. Remove stopwords and single characters

    Returns a list of clean word tokens.
    """
    text = normalize_slang(raw_text)
    text = re.sub(r"[^a-z\s]", "", text)
    return [t for t in text.split() if t not in cfg.profiler.stopwords and len(t) > 1]


def separate_background_highlight(tokens: list[str]) -> tuple[list[str], list[str]]:
    """
    Split words into background (said constantly) vs highlight (reaction words).

    Logic:
    - Count frequency of each word across all tokens
    - Words above the background threshold = background noise
    - Words below threshold = potential highlight words
    - Hype words from settings always go to highlight regardless

    Returns:
        background_words: words that appear too often to be meaningful
        highlight_words:  words that likely signal a reaction moment
    """
    if not tokens:
        return [], []

    total = len(tokens)
    word_counts = Counter(tokens)

    background = []
    highlight  = []

    for word, count in word_counts.most_common():
        frequency = count / total
        # Always highlight if in the hype words list
        if word in cfg.profiler.hype_words:
            highlight.append(word)
        elif frequency >= cfg.profiler.background_frequency_threshold:
            background.append(word)
        else:
            highlight.append(word)

    return (
        background[:cfg.profiler.top_words],
        highlight[:cfg.profiler.top_words],
    )


def score_repetition_patterns(tokens: list[str]) -> list[dict]:
    """
    Detect and score word repetition patterns.

    Scoring:
        2x repeat  → weak   (score 0.3)
        3x repeat  → medium (score 0.6)
        4x+ repeat → strong (score 0.9)

    Returns:
        List of dicts: {pattern, count, strength, score}
    """
    if not tokens:
        return []

    thresholds = cfg.profiler.repetition_thresholds
    patterns = []

    i = 0
    while i < len(tokens):
        word = tokens[i]
        count = 1
        while i + count < len(tokens) and tokens[i + count] == word:
            count += 1

        if count >= thresholds["weak"]:
            if count >= thresholds["strong"]:
                strength = "strong"
                score    = 0.9
            elif count >= thresholds["medium"]:
                strength = "medium"
                score    = 0.6
            else:
                strength = "weak"
                score    = 0.3

            pattern_str = " ".join([word] * count)
            patterns.append({
                "pattern":  pattern_str,
                "word":     word,
                "count":    count,
                "strength": strength,
                "score":    score,
            })

        i += count

    # Sort by score descending, deduplicate by word (keep highest)
    seen_words = {}
    for p in sorted(patterns, key=lambda x: x["score"], reverse=True):
        if p["word"] not in seen_words:
            seen_words[p["word"]] = p

    return list(seen_words.values())[:cfg.profiler.top_patterns]


def score_hype_phrases(
        tokens: list[str],
        high_energy_token_indices: set[int],
) -> list[dict]:
    """
    Score 2-3 word phrases that occur during high energy moments.

    Phrase score =
        (energy_alignment * 0.4) +
        (repetition       * 0.4) +
        (rarity           * 0.2)

    Returns:
        List of dicts: {phrase, score, occurrences}
    """
    if not tokens:
        return []

    total_tokens = len(tokens)
    bigrams  = [f"{tokens[i]} {tokens[i+1]}"       for i in range(len(tokens) - 1)]
    trigrams = [f"{tokens[i]} {tokens[i+1]} {tokens[i+2]}" for i in range(len(tokens) - 2)]
    all_phrases = bigrams + trigrams

    phrase_counts = Counter(all_phrases)

    # Track how many times each phrase occurs in high energy windows
    phrase_energy_hits = Counter()
    for i in range(len(tokens) - 1):
        phrase = f"{tokens[i]} {tokens[i+1]}"
        if i in high_energy_token_indices or (i+1) in high_energy_token_indices:
            phrase_energy_hits[phrase] += 1
    for i in range(len(tokens) - 2):
        phrase = f"{tokens[i]} {tokens[i+1]} {tokens[i+2]}"
        if any(j in high_energy_token_indices for j in [i, i+1, i+2]):
            phrase_energy_hits[phrase] += 1

    scored = []
    for phrase, count in phrase_counts.items():
        if count < 2:
            continue

        frequency     = count / max(total_tokens, 1)
        energy_hits   = phrase_energy_hits.get(phrase, 0)
        energy_ratio  = energy_hits / count if count > 0 else 0.0
        rarity_score  = max(0.0, 1.0 - (frequency * 20))  # rare = higher score

        score = (
                (energy_ratio * 0.4) +
                (min(count / 5.0, 1.0) * 0.4) +
                (rarity_score * 0.2)
        )

        if score > 0.1:  # Filter out near-zero scores
            scored.append({
                "phrase":      phrase,
                "score":       round(score, 3),
                "occurrences": count,
            })

    return sorted(scored, key=lambda x: x["score"], reverse=True)[:cfg.profiler.top_phrases]


def contains_low_energy_pattern(text: str) -> bool:
    """
    Check if a sentence matches known low-energy patterns.
    These phrases almost never appear in good clips.
    """
    text_lower = text.lower()
    return any(pattern in text_lower for pattern in cfg.profiler.low_energy_patterns)


def extract_word_features(tokens: list[str]) -> dict:
    """
    V1 compatibility — basic word frequency features.
    Still used for aggregation fallback.
    """
    if not tokens:
        return {"common_words": [], "repeated_patterns": [], "common_phrases": []}

    word_counts = Counter(tokens)
    common_words = [w for w, _ in word_counts.most_common(cfg.profiler.top_words)]

    repeat_counter = Counter(
        f"{tokens[i]} {tokens[i+1]}"
        for i in range(len(tokens) - 1)
        if tokens[i] == tokens[i + 1]
    )
    repeated_patterns = [
        p for p, _ in repeat_counter.most_common(cfg.profiler.top_patterns)
    ]

    bigram_counts = Counter(
        f"{tokens[i]} {tokens[i+1]}" for i in range(len(tokens) - 1)
    )
    common_phrases = [
        p for p, c in bigram_counts.most_common(cfg.profiler.top_phrases * 2)
        if c > 1
    ][:cfg.profiler.top_phrases]

    return {
        "common_words":      common_words,
        "repeated_patterns": repeated_patterns,
        "common_phrases":    common_phrases,
    }
