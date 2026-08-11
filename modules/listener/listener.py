import json
import json
import logging
import subprocess
from pathlib import Path

from config import cfg, paths
from utils.audio_utils import extract_audio
from utils.file_utils import save_json
from utils.progress_events import emit as emit_progress, check_cancelled
from utils.text_utils import normalize_slang
from utils.whisper_utils import load_whisper_model

log = logging.getLogger("listener")


def get_transcript_path(vod_path):
    return paths.TRANSCRIPTS_DIR / (vod_path.stem + ".json")


def transcript_exists(vod_path):
    return get_transcript_path(vod_path).exists()


def ask_user_retranscribe(vod_path):
    transcript_path = get_transcript_path(vod_path)
    transcript_data = json.loads(transcript_path.read_text(encoding="utf-8"))
    segment_count = len(transcript_data.get("segments", []))
    duration = transcript_data.get("duration_seconds", 0)
    duration_str = f"{int(duration // 3600)}h {int((duration % 3600) // 60)}m"

    print("\n" + "=" * 60)
    print("CACHED TRANSCRIPT FOUND")
    print("=" * 60)
    print(f"  VOD:      {vod_path.name}")
    print(f"  Duration: {duration_str}")
    print(f"  Segments: {segment_count}")
    print(f"  Cached:   {transcript_path.name}")
    print("=" * 60)

    while True:
        choice = input("Use cached transcript? [y = use cache / n = re-transcribe]: ").strip().lower()
        if choice == "y":
            log.info("Using cached transcript.")
            return False
        elif choice == "n":
            log.info("Re-transcribing from scratch.")
            return True
        else:
            print("  Enter 'y' or 'n'.")


def load_cached_transcript(vod_path):
    path = get_transcript_path(vod_path)
    log.info(f"Loading cached transcript: {path.name}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_audio_path(vod_path):
    return paths.AUDIO_DIR / (vod_path.stem + ".wav")

def _checkpoint_root(vod_path: Path) -> Path:
    return paths.TRANSCRIPT_CHECKPOINTS_DIR / vod_path.stem


def _atomic_json(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(path)


def _audio_duration(audio_path: Path) -> float:
    try:
        import soundfile as sf

        return float(sf.info(str(audio_path)).duration or 0.0)
    except Exception:
        return 0.0


def _extract_checkpoint_chunk(audio_path: Path, target: Path, start: float, duration: float) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
        "-i", str(audio_path), "-vn", "-acodec", "pcm_s16le",
        "-ar", str(cfg.audio.sample_rate), "-ac", str(cfg.audio.channels), str(target),
    ]
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0 or not target.exists():
        detail = result.stderr.decode("utf-8", errors="replace")[-1200:]
        raise RuntimeError(f"ffmpeg checkpoint extraction failed: {detail}")


def _hotword_prompt() -> str:
    """The creator's language-pack terms as a Whisper initial prompt, biasing
    transcription toward their slang/multilingual vocabulary (Language Pack WS3.1).
    Whisper treats the prompt as preceding context, so unusual words ("tsek",
    "ma se poes", "shanyok") transcribe correctly instead of being anglicized."""
    try:
        from modules.language_pack import whisper_hotwords
        words = whisper_hotwords(max_terms=120)
        if not words:
            return ""
        return "Vocabulary: " + ", ".join(words) + "."
    except Exception as e:  # noqa: BLE001 — hotwords must never break transcription
        log.debug(f"no language-pack hotwords: {e}")
        return ""


def _transcribe_window(model, audio_path: Path, vod_path: Path, *, offset: float, total_duration: float) -> dict:
    prompt = _hotword_prompt()
    # Pin the transcription language when configured. Auto-detect samples the
    # first ~30s of a window — stream intros/music can misfire it badly (a real
    # run detected 'es' on an English stream, garbling the whole window). Slang
    # still transcribes via the hotword prompt; "" / missing = auto-detect.
    language = str(getattr(cfg.whisper, "language", "") or "").strip() or None
    raw_segments, info = model.transcribe(
        str(audio_path),
        beam_size=cfg.whisper.beam_size,
        word_timestamps=cfg.listener.word_timestamps,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        chunk_length=30,
        initial_prompt=prompt or None,
        language=language,
    )

    segments = []
    full_text_parts = []
    next_progress_at = max(60.0, (int(offset // 60) + 1) * 60.0)
    for seg in raw_segments:
        # Cancel responsively: check every segment (cheap), not just once per
        # audio-minute when progress is emitted. A buyer hitting Cancel on a
        # 3-hour VOD now stops within one segment instead of waiting minutes.
        check_cancelled()
        absolute_end = offset + float(seg.end)
        if absolute_end >= next_progress_at:
            pct = min(100.0, absolute_end / total_duration * 100) if total_duration else 0.0
            log.info(
                "Transcribing: %dm / %dm (%.0f%%)",
                int(absolute_end // 60), int(total_duration // 60), pct,
            )
            emit_progress(
                stage="transcribing",
                percent=round(pct, 1),
                processed_seconds=int(absolute_end),
                total_seconds=int(total_duration),
                checkpoint_seconds=int(offset),
                message=(
                    f"Transcribing {vod_path.name} - "
                    f"{int(absolute_end // 60)}m / {int(total_duration // 60)}m"
                ),
            )
            next_progress_at = (int(absolute_end // 60) + 1) * 60.0

        normalized_text = normalize_slang(seg.text.strip())
        full_text_parts.append(normalized_text)
        segment_dict = {
            "start": round(offset + float(seg.start), 3),
            "end": round(absolute_end, 3),
            "text": normalized_text,
        }
        if cfg.listener.word_timestamps and seg.words:
            segment_dict["words"] = [
                {
                    "word": normalize_slang(word.word.strip()),
                    "start": round(offset + float(word.start), 3),
                    "end": round(offset + float(word.end), 3),
                    "prob": round(word.probability, 3),
                }
                for word in seg.words
                if word.end - word.start >= cfg.listener.min_segment_duration / 10
            ]
        if seg.end - seg.start >= cfg.listener.min_segment_duration:
            segments.append(segment_dict)

    return {
        "language": str(getattr(info, "language", "") or ""),
        "language_prob": round(float(getattr(info, "language_probability", 0.0) or 0.0), 3),
        "segments": segments,
        "full_text": " ".join(full_text_parts),
    }


def transcribe_vod_audio(model, audio_path, vod_path):
    log.info(f"Transcribing: {audio_path.name}")
    log.info("This will take a while for long VODs — do not close the terminal.")

    try:
        audio_duration = _audio_duration(audio_path)
        chunk_seconds = max(60, int(cfg.listener.checkpoint_seconds))
        use_checkpoints = audio_duration > chunk_seconds * 1.25
        chunks: list[dict] = []

        if not use_checkpoints:
            single = _transcribe_window(
                model, audio_path, vod_path, offset=0.0,
                total_duration=audio_duration,
            )
            chunks.append(single)
            if not audio_duration and single["segments"]:
                audio_duration = max(float(item["end"]) for item in single["segments"])
        else:
            root = _checkpoint_root(vod_path)
            root.mkdir(parents=True, exist_ok=True)
            fingerprint = {
                "audio_size": audio_path.stat().st_size,
                "audio_mtime_ns": audio_path.stat().st_mtime_ns,
                "chunk_seconds": chunk_seconds,
            }
            manifest_path = root / "manifest.json"
            existing_manifest = {}
            if manifest_path.exists():
                try:
                    existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    existing_manifest = {}
            if existing_manifest != fingerprint:
                for old in root.glob("chunk-*.json"):
                    old.unlink(missing_ok=True)
                _atomic_json(fingerprint, manifest_path)

            count = max(1, int((audio_duration + chunk_seconds - 1) // chunk_seconds))
            for index in range(count):
                start = float(index * chunk_seconds)
                duration = min(float(chunk_seconds), audio_duration - start)
                checkpoint = root / f"chunk-{index:04d}.json"
                if checkpoint.exists():
                    chunk = json.loads(checkpoint.read_text(encoding="utf-8"))
                    log.info("Resuming transcript from checkpoint %d/%d", index + 1, count)
                else:
                    temp_audio = root / f"chunk-{index:04d}.wav"
                    _extract_checkpoint_chunk(audio_path, temp_audio, start, duration)
                    try:
                        chunk = _transcribe_window(
                            model, temp_audio, vod_path, offset=start,
                            total_duration=audio_duration,
                        )
                        chunk["checkpoint_start"] = start
                        chunk["checkpoint_duration"] = duration
                        _atomic_json(chunk, checkpoint)
                    finally:
                        temp_audio.unlink(missing_ok=True)
                chunks.append(chunk)
                emit_progress(
                    stage="transcribing",
                    percent=round(min(100.0, (start + duration) / audio_duration * 100), 1),
                    processed_seconds=int(start + duration),
                    total_seconds=int(audio_duration),
                    checkpoint_seconds=int(start + duration),
                    message=f"Saved transcription checkpoint {index + 1}/{count}",
                )

        segments = [segment for chunk in chunks for segment in chunk.get("segments", [])]
        full_text_parts = [chunk.get("full_text", "") for chunk in chunks if chunk.get("full_text")]
        language_chunk = next((chunk for chunk in chunks if chunk.get("language")), {})
        language = language_chunk.get("language", "")
        language_prob = float(language_chunk.get("language_prob", 0.0) or 0.0)

        log.info(
            f"Transcription complete — "
            f"{len(segments)} segments, "
            f"{int(audio_duration // 60)}m {int(audio_duration % 60)}s "
            f"[{language} {language_prob:.2f}]"
        )

        return {
            "vod_name": vod_path.name,
            "vod_path": str(vod_path),
            "language": language,
            "language_prob": round(language_prob, 3),
            "duration_seconds": round(audio_duration, 2),
            "segment_count": len(segments),
            "segments": segments,
            "full_text": " ".join(full_text_parts),
            "checkpointed": use_checkpoints,
        }

    except Exception as e:
        log.error(f"Transcription failed: {e}")
        return {}


def transcribe_vod(vod_path, model=None, interactive=True):
    log.info("=" * 60)
    log.info("MODULE 2: LISTENER")
    log.info(f"VOD: {vod_path.name}")
    log.info("=" * 60)

    if transcript_exists(vod_path):
        if not interactive:
            log.info("Cached transcript found — using it automatically.")
            transcript = load_cached_transcript(vod_path)
            log.info("=" * 60)
            log.info("LISTENER COMPLETE (from cache)")
            log.info(f"  Segments: {transcript.get('segment_count', 0)}")
            log.info("=" * 60)
            return transcript
        retranscribe = ask_user_retranscribe(vod_path)
        if not retranscribe:
            transcript = load_cached_transcript(vod_path)
            log.info("=" * 60)
            log.info("LISTENER COMPLETE (from cache)")
            log.info(f"  Segments: {transcript.get('segment_count', 0)}")
            log.info("=" * 60)
            return transcript

    audio_path = get_audio_path(vod_path)
    if not audio_path.exists():
        log.info("Extracting audio from VOD...")
        emit_progress(stage="extracting_audio",
                      message=f"Extracting audio from {vod_path.name}")
        success = extract_audio(vod_path, audio_path)
        if not success:
            log.error("Audio extraction failed. Cannot transcribe.")
            return {}
    else:
        log.info(f"Audio already extracted: {audio_path.name}")

    if model is None:
        emit_progress(stage="loading_whisper", message="Loading Whisper…")
        model = load_whisper_model()

    emit_progress(stage="transcribing", percent=0.0,
                  message=f"Transcribing {vod_path.name}")
    transcript = transcribe_vod_audio(model, audio_path, vod_path)

    if not transcript:
        log.error("Transcription returned empty result.")
        return {}

    # Optional: tag each segment with speaker label.
    if cfg.clip_engine.speaker_id_enabled and transcript.get("segments"):
        try:
            from modules.speaker_id.speaker_id import (
                resemblyzer_available, identify_segments, load_speaker,
            )
            target = cfg.clip_engine.speaker_id_target
            if not resemblyzer_available():
                log.info("resemblyzer not available — skipping speaker-id")
            elif load_speaker(target) is None:
                log.info(f"No voiceprint for '{target}' — enroll first via GUI")
            else:
                identify_segments(
                    audio_path, transcript["segments"],
                    target_speaker=target,
                    threshold=cfg.clip_engine.speaker_id_threshold,
                )
        except Exception as e:
            log.warning(f"Speaker-id failed: {e}")

    transcript_path = get_transcript_path(vod_path)
    save_json(transcript, transcript_path)

    log.info("=" * 60)
    log.info("LISTENER COMPLETE")
    log.info(f"  VOD:           {vod_path.name}")
    log.info(f"  Duration:      {int(transcript['duration_seconds'] // 60)}m")
    log.info(f"  Segments:      {transcript['segment_count']}")
    log.info(f"  Language:      {transcript['language']} ({transcript['language_prob']})")
    log.info(f"  Saved to:      {transcript_path.name}")
    log.info("=" * 60)

    return transcript


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python listener.py <path_to_vod>")
        sys.exit(1)
    vod = Path(sys.argv[1])
    result = transcribe_vod(vod)
    if result:
        print(f"\nTranscript segments: {result['segment_count']}")
        print(f"Duration: {result['duration_seconds']}s")
