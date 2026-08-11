import logging
from pathlib import Path

import numpy as np

from config import cfg, paths
from utils.audio_utils import get_audio_frames, get_high_energy_segments
from utils.file_utils import save_json
from utils.progress_events import check_cancelled, emit as emit_progress
from utils.text_utils import clean_tokens, normalize_slang

try:
    from modules.face_detector.face_detector import build_face_index, get_face_score_at
    FACE_DETECTION_AVAILABLE = True
except (ImportError, Exception):
    FACE_DETECTION_AVAILABLE = False
    def build_face_index(*args, **kwargs): return {}
    def get_face_score_at(*args, **kwargs): return 0.0

try:
    from modules.quality_classifier.predictor import predict_quality, model_available as quality_model_available
    QUALITY_CLASSIFIER_AVAILABLE = True
except (ImportError, Exception):
    QUALITY_CLASSIFIER_AVAILABLE = False
    def predict_quality(*args, **kwargs): return None
    def quality_model_available(): return False

try:
    from modules.streamer_lexicon import SEMANTIC_BOOST_MAP, normalize_idioms
except (ImportError, Exception):
    SEMANTIC_BOOST_MAP = {}
    def normalize_idioms(text): return text

try:
    from modules.clip_hazards import detect_segment_hazards
except (ImportError, Exception):
    def detect_segment_hazards(segment): return []

log = logging.getLogger("clip_engine")


def get_semantic_boost(text):
    text_lower = text.lower()
    boost = 0.0
    for slang, (meaning, value) in SEMANTIC_BOOST_MAP.items():
        if slang in text_lower:
            boost += value
    return min(boost, 0.20)


def build_audio_index(rms_norm, timestamps):
    index = {}
    for rms, t in zip(rms_norm, timestamps):
        sec = int(t)
        if sec not in index:
            index[sec] = []
        index[sec].append(float(rms))
    return {sec: float(np.mean(vals)) for sec, vals in index.items()}


def get_audio_energy_at(timestamp, audio_index):
    sec = int(timestamp)
    vals = [
        audio_index.get(sec - 1, 0),
        audio_index.get(sec, 0),
        audio_index.get(sec + 1, 0),
    ]
    return float(np.mean([v for v in vals if v > 0]) if any(v > 0 for v in vals) else 0.0)


def detect_audio_spike(timestamp, audio_index, spike_threshold):
    energy = get_audio_energy_at(timestamp, audio_index)
    if energy >= spike_threshold:
        return min(energy / spike_threshold, 1.0)
    return 0.0


def detect_explosion_at(timestamp, audio_index, silence_threshold, spike_threshold, lookback_seconds=5):
    sec = int(timestamp)
    pre_energies = [audio_index.get(sec - i, 0) for i in range(1, lookback_seconds + 1)]
    current_energy = audio_index.get(sec, 0)

    valid_pre = [e for e in pre_energies if e > 0]
    if not valid_pre:
        return 0.0

    avg_pre = float(np.mean(valid_pre))
    was_quiet = avg_pre <= silence_threshold
    is_spike = current_energy >= spike_threshold

    if was_quiet and is_spike:
        jump = current_energy - avg_pre
        return min(jump / spike_threshold, 1.0)
    return 0.0


def score_repetition_in_segment(text):
    tokens = clean_tokens(normalize_slang(text))
    if len(tokens) < 2:
        return 0.0

    thresholds = cfg.profiler.repetition_thresholds
    max_repeat = 1
    i = 0
    while i < len(tokens):
        word = tokens[i]
        count = 1
        while i + count < len(tokens) and tokens[i + count] == word:
            count += 1
        max_repeat = max(max_repeat, count)
        i += count

    if max_repeat >= thresholds["strong"]:
        return 0.9
    elif max_repeat >= thresholds["medium"]:
        return 0.6
    elif max_repeat >= thresholds["weak"]:
        return 0.3
    return 0.0


def score_profile_match(text, profile):
    tokens = set(clean_tokens(normalize_slang(text)))
    text_lower = text.lower()

    if not tokens:
        return 0.0

    score = 0.0
    hits = 0

    highlight_words = set(profile.get("highlight_words", []))
    matching = tokens & highlight_words
    if matching:
        score += min(len(matching) / 3.0, 0.5)
        hits += 1

    hype_phrases = profile.get("hype_phrases", [])
    for phrase_data in hype_phrases[:10]:
        phrase = phrase_data.get("phrase", "") if isinstance(phrase_data, dict) else phrase_data
        if phrase and phrase in text_lower:
            phrase_score = phrase_data.get("score", 0.5) if isinstance(phrase_data, dict) else 0.5
            score += phrase_score * 0.3
            hits += 1
            break

    rep_patterns = profile.get("repetition_patterns", [])
    for rep in rep_patterns[:5]:
        pattern = rep.get("pattern", "") if isinstance(rep, dict) else rep
        if pattern and pattern in text_lower:
            rep_score = rep.get("score", 0.5) if isinstance(rep, dict) else 0.5
            score += rep_score * 0.2
            hits += 1
            break

    background_words = set(profile.get("background_words", []))
    penalized = set(profile.get("penalized_words", []))
    bg_ratio = len(tokens & background_words) / max(len(tokens), 1)
    if bg_ratio > 0.6:
        score *= 0.5
    if tokens & penalized:
        score *= 0.3

    return min(score, 1.0)


def score_keyword_spike(text, audio_energy, spike_threshold):
    if audio_energy < spike_threshold * 0.8:
        return 0.0

    tokens = set(clean_tokens(normalize_slang(text)))
    hype_words = cfg.profiler.hype_words
    matches = tokens & hype_words

    if not matches:
        return 0.0

    energy_bonus = min(audio_energy / spike_threshold, 1.0)
    return min(len(matches) / 3.0, 1.0) * energy_bonus


def contains_low_energy_pattern(text):
    text_lower = text.lower()
    return any(p in text_lower for p in cfg.profiler.low_energy_patterns)


def score_state_change(timestamp, audio_index, lookback=10, lookahead=5):
    sec = int(timestamp)
    pre_energies = [audio_index.get(sec - i, 0) for i in range(1, lookback + 1)]
    post_energies = [audio_index.get(sec + i, 0) for i in range(1, lookahead + 1)]

    pre_valid = [e for e in pre_energies if e > 0]
    post_valid = [e for e in post_energies if e > 0]

    if not pre_valid or not post_valid:
        return 0.0

    pre_avg = float(np.mean(pre_valid))
    post_avg = float(np.mean(post_valid))

    change = abs(post_avg - pre_avg) / max(pre_avg, 0.01)
    return min(change / 2.0, 1.0)


def score_aftermath(timestamp, duration, audio_index, spike_threshold, post_window=15):
    sec = int(timestamp + duration)
    post_energies = [audio_index.get(sec + i, 0) for i in range(1, post_window + 1)]
    valid = [e for e in post_energies if e > 0]

    if not valid:
        return 0.0

    avg_post = float(np.mean(valid))
    return min(avg_post / max(spike_threshold, 0.01), 1.0)


def classify_clip_type(audio_spike, explosion, repetition, state_change, aftermath, face_reaction):
    if explosion >= 0.5 and state_change >= 0.4:
        return "bait_and_switch"
    elif repetition >= 0.6:
        return "escalation_spiral"
    elif audio_spike >= 0.5 and face_reaction >= 0.4:
        return "reaction_content"
    elif state_change >= 0.5 and audio_spike < 0.3:
        return "deadpan_absurdity"
    elif audio_spike >= 0.4 and aftermath >= 0.4:
        return "chaos_logic"
    else:
        return "general"


def score_segment(segment, profile, audio_index, spike_threshold, silence_threshold, face_index=None):
    timestamp = segment["start"]
    duration = segment.get("end", timestamp + 5) - timestamp
    text = segment.get("text", "")
    audio_energy = get_audio_energy_at(timestamp, audio_index)

    audio_spike = detect_audio_spike(timestamp, audio_index, spike_threshold)
    explosion = detect_explosion_at(timestamp, audio_index, silence_threshold, spike_threshold)
    repetition = score_repetition_in_segment(text)
    profile_match = score_profile_match(text, profile)
    keyword_spike = score_keyword_spike(text, audio_energy, spike_threshold)
    face_reaction = get_face_score_at(timestamp, face_index) if face_index else 0.0

    state_change = score_state_change(timestamp, audio_index)
    aftermath = score_aftermath(timestamp, duration, audio_index, spike_threshold)
    semantic_boost = get_semantic_boost(text)

    clip_type = classify_clip_type(
        audio_spike, explosion, repetition, state_change, aftermath, face_reaction
    )

    if state_change < 0.05 and audio_spike < 0.2 and explosion < 0.2:
        return {**segment, "score": 0.0, "clip_type": "rejected_flat",
                "audio_spike": 0.0, "explosion": 0.0, "repetition": 0.0,
                "profile_match": 0.0, "face_reaction": 0.0, "keyword_spike": 0.0,
                "state_change": 0.0, "aftermath": 0.0, "audio_energy": round(audio_energy, 4)}

    w = cfg.clip_engine.weights
    if face_index:
        composite = (
                audio_spike * w.get("audio_spike", 0.25) +
                explosion * w.get("explosion", 0.20) +
                repetition * w.get("repetition", 0.20) +
                profile_match * w.get("profile_match", 0.15) +
                face_reaction * w.get("face_reaction", 0.15) +
                keyword_spike * w.get("keyword_spike", 0.05)
        )
    else:
        face_w = w.get("face_reaction", 0.15)
        redistributed = face_w / 2
        composite = (
                audio_spike * (w.get("audio_spike", 0.25) + redistributed) +
                explosion * (w.get("explosion", 0.20) + redistributed) +
                repetition * w.get("repetition", 0.20) +
                profile_match * w.get("profile_match", 0.15) +
                keyword_spike * w.get("keyword_spike", 0.05)
        )

    if state_change >= 0.5:
        composite += 0.10
    elif state_change >= 0.3:
        composite += 0.05

    if aftermath >= 0.5:
        composite += 0.08
    elif aftermath < 0.1:
        composite -= 0.05

    composite += semantic_boost

    if face_reaction >= 0.5:
        composite *= 1.4
    elif face_reaction >= 0.3:
        composite *= 1.2

    if contains_low_energy_pattern(text) and audio_spike < 0.3 and state_change < 0.2:
        composite *= 0.15

    # Speaker boost: a segment from the target speaker (you) is more likely
    # to be a real reaction worth clipping than a TikTok/audio in the background.
    speaker_tag = segment.get("speaker")
    speaker_boost = float(getattr(cfg.clip_engine, "speaker_boost", 0.0))
    target = getattr(cfg.clip_engine, "speaker_id_target", "lazi")
    if speaker_tag == target and speaker_boost > 0:
        composite *= (1.0 + speaker_boost)
    elif speaker_tag == "other" and speaker_boost > 0:
        composite *= (1.0 - speaker_boost * 0.5)

    composite = min(composite, 1.0)

    result = {
        **segment,
        "score": round(composite, 4),
        "clip_type": clip_type,
        "audio_spike": round(audio_spike, 4),
        "explosion": round(explosion, 4),
        "repetition": round(repetition, 4),
        "profile_match": round(profile_match, 4),
        "face_reaction": round(face_reaction, 4),
        "keyword_spike": round(keyword_spike, 4),
        "state_change": round(state_change, 4),
        "aftermath": round(aftermath, 4),
        "semantic_boost": round(semantic_boost, 4),
        "audio_energy": round(audio_energy, 4),
    }
    hazard_flags = detect_segment_hazards(result)
    if hazard_flags:
        result["hazard_flags"] = hazard_flags
    return result


def merge_highlights(scored_segments, threshold):
    MIN_CLIP = 20.0
    MAX_CLIP = 90.0
    pre_roll = float(cfg.clip_engine.pre_roll)
    post_roll = float(cfg.clip_engine.post_roll)

    hot_segments = [s for s in scored_segments if s["score"] >= threshold]
    if not hot_segments:
        return []

    windows = []
    for seg in hot_segments:
        start = max(0.0, seg["start"] - pre_roll)
        end = seg["end"] + post_roll
        # Capture the per-signal breakdown at the peak segment so the detail
        # view can show provenance later (Phase 3).
        peak_signals = {
            k: seg.get(k)
            for k in (
                "audio_spike", "explosion", "repetition", "profile_match",
                "face_reaction", "keyword_spike", "state_change", "aftermath",
                "semantic_boost", "audio_energy", "clip_type",
            )
            if k in seg
        }
        windows.append({
            "start": start,
            "end": end,
            "peak_score": seg["score"],
            "peak_time": seg["start"],
            "peak_text": seg.get("text", ""),
            "triggers": _get_trigger_reasons(seg),
            "peak_signals": peak_signals,
            "hazard_flags": list(seg.get("hazard_flags") or []),
        })

    windows.sort(key=lambda w: w["start"])

    merged = []
    for window in windows:
        if merged and window["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], window["end"])
            if window["peak_score"] > merged[-1]["peak_score"]:
                merged[-1]["peak_score"] = window["peak_score"]
                merged[-1]["peak_time"] = window["peak_time"]
                merged[-1]["peak_text"] = window["peak_text"]
                merged[-1]["peak_signals"] = window.get("peak_signals", {})
            merged[-1]["triggers"] = list(set(merged[-1]["triggers"] + window["triggers"]))
            # Union hazard flags across merged windows.
            merged[-1]["hazard_flags"] = list(
                {*(merged[-1].get("hazard_flags") or []), *(window.get("hazard_flags") or [])}
            )
        else:
            merged.append(dict(window))

    final = []
    for w in merged:
        duration = w["end"] - w["start"]

        if duration < MIN_CLIP:
            deficit = MIN_CLIP - duration
            w["start"] = max(0.0, w["start"] - deficit / 2)
            w["end"] = w["end"] + deficit / 2

        if w["end"] - w["start"] > MAX_CLIP:
            center = w["peak_time"]
            w["start"] = max(0.0, center - pre_roll)
            w["end"] = w["start"] + MAX_CLIP

        w["start"] = round(w["start"], 3)
        w["end"] = round(w["end"], 3)
        w["duration"] = round(w["end"] - w["start"], 3)

        final.append(w)

    return final


def _highlight_text(highlight, segments):
    """Concatenate transcript segments that fall inside a highlight window."""
    start, end = highlight["start"], highlight["end"]
    parts = []
    for seg in segments:
        if seg.get("end", 0) >= start and seg.get("start", 0) <= end:
            t = seg.get("text", "").strip()
            if t:
                parts.append(t)
    text = " ".join(parts).strip()
    return text or highlight.get("peak_text", "")


def _apply_quality_classifier(highlights, segments, vod_path):
    """
    Re-rank and optionally filter highlights using the trained quality
    classifier. No-op if disabled or model not trained.

    If vision is enabled and llava is available, each highlight is captioned
    by sampling frames from the VOD — same enrichment used at training time.
    """
    if not cfg.clip_engine.quality_classifier_enabled:
        for h in highlights:
            h["quality_score"] = None
            h["final_score"] = h["peak_score"]
        return highlights

    if not QUALITY_CLASSIFIER_AVAILABLE or not quality_model_available():
        log.info("Quality classifier not available — skipping re-rank")
        for h in highlights:
            h["quality_score"] = None
            h["final_score"] = h["peak_score"]
        return highlights

    use_vision = getattr(cfg.clip_engine, "vision_enabled", False)
    vision_model = getattr(cfg.clip_engine, "vision_model", "llava:7b")
    describe = None
    if use_vision:
        try:
            from modules.vision_describer.vision_describer import describe_highlight, vision_alive
            ok, msg = vision_alive(vision_model)
            if ok:
                describe = describe_highlight
                log.info(f"Vision captioning enabled — model: {vision_model}")
            else:
                log.info(f"Vision unavailable ({msg}) — skipping visual captions")
        except Exception as e:
            log.warning(f"Vision module import failed: {e}")

    log.info(f"Re-ranking {len(highlights)} highlights with quality classifier...")
    weight = float(cfg.clip_engine.quality_classifier_weight)
    min_keep = float(cfg.clip_engine.quality_min_keep)
    weight = max(0.0, min(weight, 1.0))

    kept = []
    dropped = 0
    for h in highlights:
        text = _highlight_text(h, segments)

        visual_caption = None
        if describe is not None:
            try:
                vres = describe(vod_path, h["start"], h["end"],
                                model=vision_model, n_frames=3)
                visual_caption = vres.get("combined") or None
                if visual_caption:
                    h["visual_caption"] = visual_caption[:400]
            except Exception as e:
                log.debug(f"vision call failed for highlight {h.get('clip_id','?')}: {e}")

        q = predict_quality(text, visual_caption=visual_caption)
        if q is None:
            h["quality_score"] = None
            h["final_score"] = h["peak_score"]
            kept.append(h)
            continue

        h["quality_score"] = round(q, 4)
        h["final_score"] = round((1.0 - weight) * h["peak_score"] + weight * q, 4)

        if q < min_keep:
            dropped += 1
            continue
        kept.append(h)

    log.info(f"Quality classifier: kept {len(kept)}, dropped {dropped} (min_keep={min_keep})")
    return kept


def _get_trigger_reasons(seg):
    reasons = []
    if seg.get("audio_spike", 0) >= 0.5: reasons.append("audio_spike")
    if seg.get("explosion", 0) >= 0.5: reasons.append("explosion")
    if seg.get("repetition", 0) >= 0.3: reasons.append("repetition")
    if seg.get("profile_match", 0) >= 0.3: reasons.append("profile_match")
    if seg.get("face_reaction", 0) >= 0.3: reasons.append("face_reaction")
    if seg.get("state_change", 0) >= 0.4: reasons.append("state_change")
    if seg.get("aftermath", 0) >= 0.4: reasons.append("aftermath")
    if seg.get("semantic_boost", 0) >= 0.1: reasons.append("semantic")
    if seg.get("keyword_spike", 0) >= 0.3: reasons.append("keyword_spike")
    clip_type = seg.get("clip_type", "")
    if clip_type and clip_type not in ("general", "rejected_flat"):
        reasons.append(clip_type)
    return reasons or ["low_signal"]


def find_highlights(transcript, profile, vod_path):
    log.info("=" * 60)
    log.info("MODULE 3: CLIP ENGINE")
    log.info(f"VOD: {vod_path.name}")
    log.info(f"Segments to scan: {len(transcript.get('segments', []))}")
    log.info("=" * 60)

    segments = transcript.get("segments", [])
    if not segments:
        log.error("No segments in transcript. Cannot score.")
        return []

    if not profile:
        log.error("Empty profile. Run profiler first.")
        return []

    audio_path = paths.AUDIO_DIR / (vod_path.stem + ".wav")
    if not audio_path.exists():
        log.error(f"Audio not found: {audio_path}. Run listener first.")
        return []

    log.info("Loading audio energy index...")
    try:
        rms_norm, timestamps, _ = get_audio_frames(audio_path)
        audio_index = build_audio_index(rms_norm, timestamps)
        spike_threshold = float(np.percentile(rms_norm, cfg.profiler.high_energy_percentile))
        silence_threshold = float(np.percentile(rms_norm, 20))
        log.info(f"Audio loaded — spike threshold: {spike_threshold:.3f}")
    except Exception as e:
        log.error(f"Audio analysis failed: {e}")
        return []

    face_cache_path = paths.TRANSCRIPTS_DIR / (vod_path.stem + "_face.json")
    run_face = cfg.clip_engine.face_detection_enabled or face_cache_path.exists()
    if run_face and FACE_DETECTION_AVAILABLE:
        log.info("Building face reaction index...")
        try:
            face_index = build_face_index(vod_path)
            if face_index:
                log.info(f"Face detection active — {len(face_index)} seconds indexed")
            else:
                log.info("Face index empty — scoring without face signals")
        except Exception as e:
            log.warning(f"Face detection failed ({e}) — continuing without it")
            face_index = {}
    else:
        if not FACE_DETECTION_AVAILABLE:
            log.info("Face detector unavailable — skipping face signals")
        else:
            log.info("Face detection disabled in settings — skipping")
        face_index = {}

    log.info("Scoring segments...")
    emit_progress(stage="scoring", percent=0.0,
                  message=f"Scoring {len(segments)} segments")
    scored = []
    n_segments = max(1, len(segments))
    for i, seg in enumerate(segments):
        scored_seg = score_segment(
            seg, profile, audio_index, spike_threshold, silence_threshold,
            face_index=face_index or None,
        )
        scored.append(scored_seg)
        if i and i % 100 == 0:
            emit_progress(stage="scoring",
                          percent=round(i / n_segments * 100, 1),
                          processed=i, total=n_segments)
        elif i and i % 25 == 0:
            check_cancelled()

    scores = [s["score"] for s in scored]
    above_threshold = sum(1 for s in scores if s >= cfg.clip_engine.highlight_threshold)
    log.info(
        f"Scoring complete — "
        f"avg: {np.mean(scores):.3f}, "
        f"max: {np.max(scores):.3f}, "
        f"above threshold ({cfg.clip_engine.highlight_threshold}): {above_threshold}"
    )

    log.info("Merging highlights...")
    emit_progress(stage="merging_highlights",
                  message="Merging overlapping highlight windows…")
    highlights = merge_highlights(scored, cfg.clip_engine.highlight_threshold)

    if not highlights:
        log.warning(
            f"No highlights found above threshold {cfg.clip_engine.highlight_threshold}. "
            f"Try lowering highlight_threshold in settings.json."
        )
        return []

    highlights = _apply_quality_classifier(highlights, segments, vod_path)

    highlights.sort(key=lambda h: h.get("final_score", h["peak_score"]), reverse=True)

    for i, h in enumerate(highlights):
        h["clip_id"] = f"{vod_path.stem}_{i+1:03d}"
        h["vod_name"] = vod_path.name

    metadata_path = paths.METADATA_DIR / f"{vod_path.stem}_highlights.json"
    save_json({"vod": vod_path.name, "highlights": highlights}, metadata_path)

    log.info("=" * 60)
    log.info("CLIP ENGINE COMPLETE")
    log.info(f"  Highlights found: {len(highlights)}")
    log.info(f"  Best score:       {highlights[0]['peak_score']:.3f}")
    log.info(f"  Best moment:      {highlights[0]['peak_text'][:60]}")
    log.info(f"  Metadata saved:   {metadata_path.name}")
    log.info("=" * 60)

    return highlights


if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) < 3:
        print("Usage: python clip_engine.py <transcript.json> <vod_path>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        t = json.load(f)
    from utils.file_utils import load_json
    p = load_json(paths.PROFILE_PATH)
    results = find_highlights(t, p, Path(sys.argv[2]))
    print(f"\nFound {len(results)} highlights")