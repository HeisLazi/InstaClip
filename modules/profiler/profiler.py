import logging
from collections import Counter
from pathlib import Path

import numpy as np

from config import cfg, paths
from utils.audio_utils import (
    extract_audio, analyze_audio,
    get_audio_frames, get_high_energy_segments,
    is_timestamp_in_high_energy,
)
from utils.file_utils import save_json, find_video_files
from utils.text_utils import (
    clean_tokens, normalize_slang,
    separate_background_highlight,
    score_repetition_patterns,
    score_hype_phrases,
    extract_word_features,
)
from utils.whisper_utils import load_whisper_model

log = logging.getLogger("profiler")


def _review_adjusted_weight(base_weight, review):
    """Return a positive profile weight, or None when feedback rejects the clip."""
    if not review:
        return base_weight

    from modules.clip_reviews import classify_review_signal

    verdict = str(review.get("verdict") or "undecided").lower()
    rating = review.get("rating")
    rating = float(rating) if isinstance(rating, (int, float)) else None
    signal = classify_review_signal(review)

    if signal in {"negative", "boundary", "context", "null"}:
        return None
    if signal == "positive":
        # A reviewed keeper is stronger evidence than an unreviewed generated
        # clip, while posted clips remain capped at the existing 6x weight.
        review_weight = min(6.0, max(3.0, (rating or 3.0) + 1.0))
        return max(base_weight, review_weight)
    if verdict == "maybe":
        return max(1.0, base_weight - 1.0)
    # Ratings are not binary taste labels: low-rated keeper/compilation pieces
    # are common in the real review history. Only verdict/tags reject evidence.
    return base_weight


def transcribe_with_segments(model, audio_path):
    try:
        raw_segments, info = model.transcribe(
            str(audio_path),
            beam_size=cfg.whisper.beam_size,
            word_timestamps=False,
        )
        segments = []
        full_text_parts = []

        for seg in raw_segments:
            text = normalize_slang(seg.text.strip())
            segments.append({
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": text,
            })
            full_text_parts.append(text)

        full_text = " ".join(full_text_parts)
        return full_text, segments

    except Exception as e:
        log.error(f"Transcription failed for {audio_path.name}: {e}")
        return "", []


def extract_burst_tokens(segments, high_energy_segs):
    burst_tokens = []
    high_energy_token_indices = set()
    all_tokens = []
    token_idx = 0

    for seg in segments:
        seg_tokens = clean_tokens(seg["text"])
        seg_start = seg["start"]
        seg_end = seg["end"]

        seg_is_high_energy = any(
            not (seg_end < he_start or seg_start > he_end)
            for he_start, he_end in high_energy_segs
        )

        for token in seg_tokens:
            all_tokens.append(token)
            if seg_is_high_energy:
                burst_tokens.append(token)
                high_energy_token_indices.add(token_idx)
            token_idx += 1

    return burst_tokens, high_energy_token_indices


def process_clip(clip_path, model, index, total, is_bad_clip=False):
    label = "BAD" if is_bad_clip else "GOOD"
    log.info(f"[{index}/{total}] [{label}] Processing: {clip_path.name}")

    audio_path = paths.AUDIO_DIR / (clip_path.stem + ".wav")

    if not extract_audio(clip_path, audio_path):
        log.warning(f"Skipping {clip_path.name} — audio extraction failed.")
        return None

    full_text, segments = transcribe_with_segments(model, audio_path)
    audio_data = analyze_audio(audio_path)

    try:
        rms_norm, timestamps, _ = get_audio_frames(audio_path)
        high_energy_segs = get_high_energy_segments(rms_norm, timestamps)
    except Exception as e:
        log.error(f"Frame analysis failed for {clip_path.name}: {e}")
        high_energy_segs = []

    burst_tokens, high_energy_token_indices = extract_burst_tokens(
        segments, high_energy_segs
    )

    all_tokens = clean_tokens(full_text) if full_text else []

    background_words, highlight_words = separate_background_highlight(all_tokens)
    repetition_patterns = score_repetition_patterns(all_tokens)
    hype_phrases = score_hype_phrases(all_tokens, high_energy_token_indices)

    return {
        "clip_name": clip_path.name,
        "is_bad_clip": is_bad_clip,
        "duration": audio_data["duration"],
        "burst_tokens": burst_tokens,
        "all_tokens": all_tokens,
        "background_words": background_words,
        "highlight_words": highlight_words,
        "repetition_patterns": repetition_patterns,
        "hype_phrases": hype_phrases,
        "avg_loudness": audio_data["avg_loudness"],
        "peak_loudness": audio_data["peak_loudness"],
        "spike_threshold": audio_data["spike_threshold"],
        "silence_threshold": audio_data["silence_threshold"],
        "explosions": audio_data["explosions"],
        "explosion_count": audio_data["explosion_count"],
        "_transcript_preview": full_text[:300] if full_text else "",
    }


def aggregate_profile(good_results, bad_results):
    all_burst_tokens = []
    all_tokens = []
    all_background = Counter()
    all_highlight = Counter()
    all_repetitions = []
    all_hype_phrases = []
    all_explosions = []

    for r in good_results:
        w = int(r.get("weight", 1.0))
        for _ in range(w):
            all_burst_tokens.extend(r.get("burst_tokens", []))
            all_tokens.extend(r.get("all_tokens", []))
            all_background.update(r.get("background_words", []))
            all_highlight.update(r.get("highlight_words", []))
            all_repetitions.extend(r.get("repetition_patterns", []))
            all_hype_phrases.extend(r.get("hype_phrases", []))
            all_explosions.extend(r.get("explosions", []))

    bad_tokens = []
    bad_highlight = Counter()
    for r in bad_results:
        bad_tokens.extend(r.get("burst_tokens", []))
        bad_highlight.update(r.get("highlight_words", []))

    burst_counter = Counter(all_burst_tokens)
    highlight_words = [
        w for w, _ in burst_counter.most_common(cfg.profiler.top_words)
        if w not in all_background or all_highlight[w] > all_background[w]
    ]

    bad_burst_counter = Counter(bad_tokens)
    penalized_words = [
        w for w, c in bad_burst_counter.most_common(20)
        if c >= 3
    ]

    highlight_words = [w for w in highlight_words if w not in penalized_words]

    rep_by_word = {}
    for rep in all_repetitions:
        word = rep["word"]
        if word not in rep_by_word or rep["score"] > rep_by_word[word]["score"]:
            rep_by_word[word] = rep
    top_repetitions = sorted(
        rep_by_word.values(), key=lambda x: x["score"], reverse=True
    )[:cfg.profiler.top_patterns]

    phrase_scores = {}
    phrase_counts = Counter()
    for p in all_hype_phrases:
        phrase = p["phrase"]
        phrase_scores[phrase] = phrase_scores.get(phrase, 0) + p["score"]
        phrase_counts[phrase] += 1

    top_hype_phrases = sorted(
        [
            {
                "phrase": phrase,
                "score": round(phrase_scores[phrase] / phrase_counts[phrase], 3),
                "occurrences": phrase_counts[phrase],
            }
            for phrase in phrase_scores
        ],
        key=lambda x: x["score"],
        reverse=True,
    )[:cfg.profiler.top_phrases]

    weighted_good = [
        result
        for result in good_results
        for _ in range(max(1, int(result.get("weight", 1.0))))
    ]
    valid = [r for r in weighted_good if r.get("avg_loudness", 0) > 0]
    avg_loudness = round(float(np.mean([r["avg_loudness"] for r in valid])), 4) if valid else 0.0
    avg_spike_thresh = round(float(np.mean([r["spike_threshold"] for r in valid])), 4) if valid else 0.0
    avg_silence_thresh = round(float(np.mean([r["silence_threshold"] for r in valid])), 4) if valid else 0.0
    avg_explosion_intensity = round(
        float(np.mean([e["intensity"] for r in weighted_good for e in r.get("explosions", [])])), 4
    ) if all_explosions else 0.0
    total_explosions = sum(r.get("explosion_count", 0) for r in weighted_good)

    durations = [r["duration"] for r in weighted_good if r.get("duration", 0) > 0]
    avg_duration = round(float(np.mean(durations)), 2) if durations else 0.0

    return {
        "highlight_words": highlight_words[:cfg.profiler.top_words],
        "background_words": [w for w, _ in all_background.most_common(cfg.profiler.top_words)],
        "penalized_words": penalized_words,
        "repetition_patterns": top_repetitions,
        "hype_phrases": top_hype_phrases,
        "low_energy_patterns": cfg.profiler.low_energy_patterns,
        "audio_profile": {
            "avg_loudness": avg_loudness,
            "spike_threshold": avg_spike_thresh,
            "silence_threshold": avg_silence_thresh,
            "avg_explosion_intensity": avg_explosion_intensity,
            "explosion_frequency": total_explosions,
        },
        "context_window": {
            "pre_seconds": cfg.profiler.context_window.pre_seconds,
            "post_seconds": cfg.profiler.context_window.post_seconds,
        },
        "avg_clip_duration": avg_duration,
        "clips_analyzed": len(good_results),
        "weighted_examples": len(weighted_good),
        "bad_clips_used": len(bad_results),
    }


def process_bad_clips(model):
    bad_clip_files = find_video_files(paths.NOTCLIPS_DIR)
    if not bad_clip_files:
        log.info("No bad clips found in output/notclips/ — skipping bad clip analysis.")
        return []

    try:
        from modules.clip_reviews import classify_review_signal, list_reviews
        reviews = {review["stem"]: review for review in list_reviews(limit=10000)}
    except Exception as exc:
        log.warning(f"Could not load reviews while filtering negative evidence: {exc}")
        reviews = {}
        classify_review_signal = None

    log.info(f"Found {len(bad_clip_files)} bad clip(s) to analyze.")
    results = []
    skipped_feedback_failures = 0
    for i, clip in enumerate(bad_clip_files, start=1):
        review = reviews.get(clip.stem)
        if review and classify_review_signal is not None:
            signal = classify_review_signal(review)
            if signal != "negative":
                skipped_feedback_failures += 1
                log.info(
                    "Skipping %s as negative profile evidence (review signal=%s)",
                    clip.name,
                    signal,
                )
                continue
        result = process_clip(clip, model, i, len(bad_clip_files), is_bad_clip=True)
        if result:
            results.append(result)
    if skipped_feedback_failures:
        log.info(
            "Excluded %d trim/context/positive review(s) from negative profile evidence.",
            skipped_feedback_failures,
        )
    return results


def build_profile():
    log.info("=" * 60)
    log.info("MODULE 0: PROFILER V2")
    log.info("=" * 60)

    clip_files = find_video_files(paths.OLD_CLIPS_DIR)
    if not clip_files:
        log.error(f"No clips found in {paths.OLD_CLIPS_DIR}. Aborting.")
        return {}

    creator_clips = [c for c in clip_files if not c.stem.startswith("GEN_")]
    generated_clips = [c for c in clip_files if c.stem.startswith("GEN_")]
    # publisher.py is excluded from the public edition; profiler works from local
    # clip folders and reviews only.
    posted = set()
    try:
        from modules.clip_reviews import list_reviews
        reviews = {review["stem"]: review for review in list_reviews(limit=10000)}
    except Exception as exc:
        log.warning(f"Could not load clip reviews for profile weighting: {exc}")
        reviews = {}

    log.info(f"Found {len(clip_files)} clip(s) total:")
    log.info(f"  Creator clips (3x weight):   {len(creator_clips)}")
    log.info(f"  System-generated (1x weight): {len(generated_clips)}")
    if posted:
        log.info(f"  Posted clips (6x weight):    {sum(1 for c in clip_files if c.stem in posted)}")
    model = load_whisper_model()

    good_results = []
    review_excluded = 0
    for i, clip in enumerate(creator_clips, start=1):
        base_weight = 6.0 if clip.stem in posted else 3.0
        weight = _review_adjusted_weight(base_weight, reviews.get(clip.stem))
        if weight is None:
            review_excluded += 1
            log.info(f"Skipping review-rejected clip: {clip.name}")
            continue
        result = process_clip(clip, model, i, len(creator_clips))
        if result:
            result["weight"] = weight
            result["source"] = "posted" if clip.stem in posted else "creator"
            good_results.append(result)

    for i, clip in enumerate(generated_clips, start=1):
        base_weight = 6.0 if clip.stem in posted else 1.0
        weight = _review_adjusted_weight(base_weight, reviews.get(clip.stem))
        if weight is None:
            review_excluded += 1
            log.info(f"Skipping review-rejected clip: {clip.name}")
            continue
        result = process_clip(clip, model, i, len(generated_clips))
        if result:
            result["weight"] = weight
            result["source"] = "posted" if clip.stem in posted else "generated"
            good_results.append(result)

    if not good_results:
        log.error("All clips failed. Check logs/pipeline.log.")
        return {}

    bad_results = process_bad_clips(model)

    log.info("Building V2 profile...")
    profile = aggregate_profile(good_results, bad_results)

    save_json(profile, paths.PROFILES_DIR / "lek_profile.json", versioned=True)

    log.info("=" * 60)
    log.info("PROFILER V2 COMPLETE")
    creator_count = sum(1 for r in good_results if r.get("source") == "creator")
    generated_count = sum(1 for r in good_results if r.get("source") == "generated")
    posted_count = sum(1 for r in good_results if r.get("source") == "posted")
    log.info(f"  Creator clips (gold):     {creator_count} (weighted 3x)")
    log.info(f"  System clips:             {generated_count} (weighted 1x)")
    log.info(f"  Posted clips:             {posted_count} (weighted 6x)")
    log.info(f"  Review-rejected skipped:  {review_excluded}")
    log.info(f"  Total clips analyzed:     {profile['clips_analyzed']}")
    log.info(f"  Bad clips used:       {profile['bad_clips_used']}")
    log.info(f"  Avg clip duration:    {profile['avg_clip_duration']}s")
    log.info(f"  Highlight words:      {profile['highlight_words'][:8]}")
    log.info(f"  Top hype phrase:      {profile['hype_phrases'][0] if profile['hype_phrases'] else 'none'}")
    log.info(f"  Explosion frequency:  {profile['audio_profile']['explosion_frequency']}")
    log.info(f"  Spike threshold:      {profile['audio_profile']['spike_threshold']}")
    log.info(f"  Profile saved to:     {paths.PROFILES_DIR / 'lek_profile.json'}")
    log.info("=" * 60)

    return profile


if __name__ == "__main__":
    build_profile()
