# =============================================================================
# utils/audio_utils.py — Shared Audio Helpers
# =============================================================================
# Used by: profiler.py, listener.py, clip_engine.py
# =============================================================================

import logging
import subprocess
from pathlib import Path

import librosa
import numpy as np

from config import cfg

log = logging.getLogger("utils.audio")


def extract_audio(video_path: Path, audio_path: Path) -> bool:
    """
    Extract audio from a video file using ffmpeg.
    Output: mono WAV at configured sample rate — optimized for Whisper.

    Returns True on success, False on any failure.
    """
    command = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", str(cfg.audio.sample_rate),
        "-ac", str(cfg.audio.channels),
        str(audio_path),
    ]
    try:
        size_gb = video_path.stat().st_size / (1024 ** 3)
        timeout_seconds = max(300, min(int(size_gb * 240), 3600))
        subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
            timeout=timeout_seconds,
        )
        log.debug(f"Audio extracted → {audio_path.name}")
        return True
    except subprocess.CalledProcessError as e:
        log.error(f"ffmpeg failed on {video_path.name}: {e.stderr.decode()}")
    except subprocess.TimeoutExpired:
        log.error(f"ffmpeg timed out on {video_path.name}")
    except FileNotFoundError:
        log.critical("ffmpeg not found — is it installed and in PATH?")
    return False


def get_audio_frames(audio_path: Path) -> tuple[np.ndarray, np.ndarray, int]:
    """
    Load audio and compute RMS energy per frame.

    Returns:
        rms_norm:   RMS energy per frame, normalized 0-1
        timestamps: Timestamp in seconds for each frame
        sr:         Sample rate
    """
    import soundfile as sf
    hop_length = 512
    target_sr  = cfg.audio.sample_rate

    # Use soundfile with memory-mapped reading to avoid loading full file into RAM
    # Then downsample to 1 RMS value per second instead of per frame
    # This reduces memory usage by ~50x on long VODs
    try:
        info = sf.info(str(audio_path))
        file_sr = info.samplerate
        total_samples = info.frames

        # Read in 60-second chunks to avoid OOM on long VODs
        chunk_size = file_sr * 60
        rms_per_second = []

        with sf.SoundFile(str(audio_path)) as f:
            while True:
                chunk = f.read(chunk_size, dtype="float32", always_2d=True)
                if len(chunk) == 0:
                    break
                # Convert to mono
                mono = chunk.mean(axis=1)
                # Compute RMS per second within this chunk
                seconds_in_chunk = max(1, len(mono) // file_sr)
                for s in range(seconds_in_chunk):
                    start = s * file_sr
                    end   = min(start + file_sr, len(mono))
                    segment = mono[start:end]
                    if len(segment) > 0:
                        rms_val = float(np.sqrt(np.mean(segment ** 2)))
                        rms_per_second.append(rms_val)

        rms_array = np.array(rms_per_second, dtype=np.float32)
        rms_max   = rms_array.max()
        rms_norm  = rms_array / rms_max if rms_max > 0 else rms_array
        timestamps = np.arange(len(rms_norm), dtype=np.float32)
        sr         = 1  # 1 value per second
        return rms_norm, timestamps, sr

    except Exception:
        # Fallback to librosa if soundfile fails
        y, sr = librosa.load(str(audio_path), sr=target_sr, mono=True)
        rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
        rms_max = rms.max()
        rms_norm = rms / rms_max if rms_max > 0 else rms
        timestamps = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)
        return rms_norm, timestamps, sr


def get_high_energy_segments(
        rms_norm: np.ndarray,
        timestamps: np.ndarray,
) -> list[tuple[float, float]]:
    """
    Find time segments where audio energy is in the top N percentile.
    These are the moments where highlight words are likely spoken.

    Returns:
        List of (start_time, end_time) tuples for high energy segments.
    """
    threshold = np.percentile(rms_norm, cfg.profiler.high_energy_percentile)
    high_energy = rms_norm >= threshold

    segments = []
    in_segment = False
    seg_start = 0.0

    for i, (is_high, t) in enumerate(zip(high_energy, timestamps)):
        if is_high and not in_segment:
            seg_start = float(t)
            in_segment = True
        elif not is_high and in_segment:
            segments.append((seg_start, float(t)))
            in_segment = False

    if in_segment:
        segments.append((seg_start, float(timestamps[-1])))

    return segments


def detect_explosions(
        rms_norm: np.ndarray,
        timestamps: np.ndarray,
) -> list[dict]:
    """
    Detect silence → explosion moments (the core of comedy/hype timing).

    A valid explosion = period of low energy followed by a sharp spike.

    Returns:
        List of explosion events with timestamp and intensity.
    """
    silence_threshold = float(np.percentile(rms_norm, 20))
    spike_threshold   = float(np.percentile(rms_norm, cfg.profiler.high_energy_percentile))

    explosions = []
    window = 10  # frames to look back for silence (~0.3s)

    for i in range(window, len(rms_norm)):
        current = rms_norm[i]
        pre_window = rms_norm[i - window:i]

        was_silent = float(np.mean(pre_window)) < silence_threshold
        is_spike   = current >= spike_threshold

        if was_silent and is_spike:
            jump = float(current - np.mean(pre_window))
            explosions.append({
                "timestamp": round(float(timestamps[i]), 3),
                "intensity": round(float(current), 4),
                "jump":      round(jump, 4),
            })

    # Deduplicate — merge explosions within 1 second of each other
    merged = []
    for exp in explosions:
        if merged and exp["timestamp"] - merged[-1]["timestamp"] < 1.0:
            # Keep the stronger one
            if exp["intensity"] > merged[-1]["intensity"]:
                merged[-1] = exp
        else:
            merged.append(exp)

    return merged


def analyze_audio(audio_path: Path) -> dict:
    """
    Full V2 audio analysis.

    Returns:
        avg_loudness:     Mean RMS energy 0-1
        peak_loudness:    Max RMS energy 0-1
        spike_threshold:  Energy level that constitutes a spike
        silence_threshold:Energy level that constitutes silence
        explosions:       List of silence→spike events
        duration:         Clip length in seconds
    """
    try:
        rms_norm, timestamps, sr = get_audio_frames(audio_path)

        if len(rms_norm) == 0:
            log.warning(f"Empty audio: {audio_path.name}")
            return _empty_audio_result()

        y_duration = float(timestamps[-1]) if len(timestamps) > 0 else 0.0
        explosions = detect_explosions(rms_norm, timestamps)

        return {
            "avg_loudness":      round(float(np.mean(rms_norm)), 4),
            "peak_loudness":     round(float(np.max(rms_norm)), 4),
            "spike_threshold":   round(float(np.percentile(rms_norm, cfg.profiler.high_energy_percentile)), 4),
            "silence_threshold": round(float(np.percentile(rms_norm, 20)), 4),
            "explosions":        explosions,
            "explosion_count":   len(explosions),
            "duration":          round(y_duration, 2),
        }

    except Exception as e:
        log.error(f"Audio analysis failed for {audio_path.name}: {e}")
        return _empty_audio_result()


def _empty_audio_result() -> dict:
    return {
        "avg_loudness": 0.0, "peak_loudness": 0.0,
        "spike_threshold": 0.0, "silence_threshold": 0.0,
        "explosions": [], "explosion_count": 0, "duration": 0.0,
    }


def is_timestamp_in_high_energy(
        timestamp: float,
        high_energy_segments: list[tuple[float, float]],
) -> bool:
    """
    Check if a given timestamp falls inside a high energy segment.
    Used by profiler to filter words to only those spoken during hype.
    """
    for start, end in high_energy_segments:
        if start <= timestamp <= end:
            return True
    return False
