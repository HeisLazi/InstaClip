"""
Tiny wrapper around sounddevice for recording the default mic to a WAV file.
Used by the GUI's voiceprint enrollment.
"""

import logging
from pathlib import Path

import numpy as np

log = logging.getLogger("mic_recorder")

SAMPLE_RATE = 16000  # matches resemblyzer's expected input


def list_input_devices() -> list[dict]:
    import sounddevice as sd
    return [d for d in sd.query_devices() if d["max_input_channels"] > 0]


def record_to_wav(out_path: Path, duration_seconds: float = 30.0,
                  device: int | str | None = None) -> Path:
    """Block-record from the default mic and write a 16kHz mono WAV."""
    import sounddevice as sd
    import soundfile as sf

    out_path.parent.mkdir(parents=True, exist_ok=True)
    log.info(f"Recording {duration_seconds:.0f}s @ {SAMPLE_RATE}Hz mono...")

    audio = sd.rec(
        int(duration_seconds * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        device=device,
    )
    sd.wait()

    audio = np.squeeze(audio)
    sf.write(str(out_path), audio, SAMPLE_RATE, subtype="PCM_16")
    log.info(f"Saved: {out_path} ({audio.size / SAMPLE_RATE:.1f}s)")
    return out_path
