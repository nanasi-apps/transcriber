"""Audio normalisation utilities.

Responsible for converting arbitrary audio/video files into the canonical
format consumed by every downstream stage: **16 kHz, mono, float32 WAV**.

This module deliberately avoids loading any ML models so it stays fast
and can be tested independently.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

SAMPLE_RATE: int = 16_000
"""Target sample rate used throughout the pipeline."""

_WAV_EXTENSIONS = frozenset({".wav"})


def convert_to_wav(input_path: Path, output_path: Path) -> None:
    """Convert *any* ffmpeg-supported file to 16 kHz mono WAV.

    Raises ``RuntimeError`` when ffmpeg returns a non-zero exit code.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-sample_fmt",
        "s16",
        "-f",
        "wav",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed:\n{result.stderr}")


def load_audio(path: Path) -> np.ndarray:
    """Load a WAV file as a 1-D float32 numpy array at ``SAMPLE_RATE``."""
    data, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if sr != SAMPLE_RATE:
        raise ValueError(f"Expected {SAMPLE_RATE} Hz, got {sr} Hz")
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data


def get_audio_duration(path: Path) -> float:
    """Return audio duration in seconds using ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed:\n{result.stderr}")
    return float(result.stdout.strip())


def ensure_wav(input_path: Path) -> tuple[Path, bool]:
    """Return a 16 kHz mono WAV path, converting if necessary.

    Returns ``(wav_path, needs_cleanup)`` - the caller is responsible for
    deleting the file when ``needs_cleanup`` is ``True``.
    """
    if input_path.suffix.lower() in _WAV_EXTENSIONS:
        # Verify sample rate / channels before assuming it's usable.
        info = sf.info(str(input_path))
        if info.samplerate == SAMPLE_RATE and info.channels == 1:
            return input_path, False

    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".wav")
    import os

    os.close(tmp_fd)
    tmp_path = Path(tmp_name)
    logger.info("Converting %s → %s", input_path, tmp_path)
    convert_to_wav(input_path, tmp_path)
    return tmp_path, True
