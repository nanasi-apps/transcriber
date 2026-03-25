"""Forced alignment wrapper.

Single responsibility: given audio + text, produce word / character level
timestamps.  This is applied *after* merge when higher-precision boundaries
are wanted for specific utterances.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import mlx.core as mx
import numpy as np
import torch

from .audio import SAMPLE_RATE, load_audio
from .memory import release_torch_memory
from .progress import start_progress_ticker
from .schema import AsrSegment, WordTimestamp

logger = logging.getLogger(__name__)


DEFAULT_ALIGNER_MODEL = "mlx-community/Qwen3-ForcedAligner-0.6B-4bit"
_MAX_ALIGNMENT_WINDOW_SECONDS = 120.0
_ALIGNMENT_WINDOW_PADDING_SECONDS = 1.5
_MAX_ALIGNMENT_WINDOW_CHARS = 1200


def _resolve_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda:0")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _resolve_dtype(device: torch.device) -> torch.dtype:
    if device.type == "cuda":
        return torch.bfloat16
    return torch.float32


class AlignerEngine:
    """Thin wrapper around the MLX Qwen forced aligner."""

    def __init__(
        self,
        model_name: str = DEFAULT_ALIGNER_MODEL,
        *,
        device: torch.device | None = None,
        dtype: torch.dtype | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device or _resolve_device()
        self.dtype = dtype or _resolve_dtype(self.device)
        self._model = None

    @staticmethod
    def _make_progress_message(current: int, total: int) -> str:
        if total <= 1:
            return "Running forced alignment..."
        return f"Running forced alignment... ({current}/{total})"

    def _ensure_model(self, on_progress: Callable[[int, str], None] | None = None):
        if self._model is not None:
            if on_progress is not None:
                on_progress(25, "Alignment model ready")
            return
        try:
            from mlx_audio.stt import load as load_stt_model
        except Exception as exc:
            raise ImportError(
                "MLX forced aligner requires mlx-audio. Install it with: pip install mlx-audio"
            ) from exc

        logger.info(
            "Loading ForcedAligner %s on %s (%s) …",
            self.model_name,
            self.device,
            self.dtype,
        )
        stop_ticker = None
        if on_progress is not None:
            on_progress(5, "Loading alignment model")
            stop_ticker = start_progress_ticker(
                on_progress,
                start_pct=5,
                end_pct=25,
                base_message="Loading alignment model",
                ramp_seconds=18.0,
            )

        self._model = load_stt_model(self.model_name)
        if stop_ticker is not None:
            stop_ticker(25, "Alignment model ready")
        logger.info("ForcedAligner loaded.")

    def align(
        self,
        audio: str | Path | tuple[np.ndarray, int],
        text: str,
        *,
        language: str = "Japanese",
    ) -> list[WordTimestamp]:
        """Align *text* to *audio* and return word-level timestamps.

        *audio* can be a file path or a ``(waveform, sample_rate)`` tuple.
        """
        self._ensure_model()
        assert self._model is not None

        if isinstance(audio, Path):
            audio_input: str | np.ndarray = str(audio)
        elif isinstance(audio, tuple):
            waveform, sample_rate = audio
            if sample_rate != SAMPLE_RATE:
                raise ValueError(f"Forced alignment expects {SAMPLE_RATE}Hz audio")
            audio_input = waveform
        else:
            audio_input = audio

        results = self._model.generate(
            audio=audio_input,
            text=text,
            language=language,
        )

        words: list[WordTimestamp] = []
        items = results.items if hasattr(results, "items") else []
        for w in items:
            words.append(
                WordTimestamp(
                    text=w.text,
                    start=round(w.start_time, 3),
                    end=round(w.end_time, 3),
                )
            )
        mx.clear_cache()
        return words

    def align_segments(
        self,
        audio_path: str | Path,
        segments: list[AsrSegment],
        *,
        language: str = "Japanese",
        on_progress: Callable[[int, str], None] | None = None,
    ) -> list[WordTimestamp]:
        """Align ASR segments in bounded windows to balance accuracy and memory."""
        self._ensure_model(on_progress=on_progress)
        assert self._model is not None

        audio_path = Path(audio_path)
        waveform = load_audio(audio_path)
        usable_segments = [seg for seg in segments if seg.text.strip() and seg.end > seg.start]
        if not usable_segments:
            return []

        windows = self._build_alignment_windows(usable_segments)
        words: list[WordTimestamp] = []
        total = len(windows)

        try:
            for index, window in enumerate(windows, start=1):
                if on_progress is not None:
                    progress_pct = 25 + int(((index - 1) / total) * 65)
                    on_progress(progress_pct, self._make_progress_message(index, total))

                audio_start = max(0.0, window[0].start - _ALIGNMENT_WINDOW_PADDING_SECONDS)
                audio_end = window[-1].end + _ALIGNMENT_WINDOW_PADDING_SECONDS
                start_frame = max(0, int(audio_start * SAMPLE_RATE))
                end_frame = min(len(waveform), max(start_frame + 1, int(audio_end * SAMPLE_RATE)))
                window_audio = waveform[start_frame:end_frame]
                if window_audio.size == 0:
                    continue

                window_text = " ".join(
                    segment.text.strip() for segment in window if segment.text.strip()
                )
                if not window_text:
                    continue

                results = self._model.generate(
                    audio=window_audio,
                    text=window_text,
                    language=language,
                )

                items = results.items if hasattr(results, "items") else []
                for item in items:
                    words.append(
                        WordTimestamp(
                            text=item.text,
                            start=round(audio_start + item.start_time, 3),
                            end=round(audio_start + item.end_time, 3),
                        )
                    )
                del window_audio
                del results
                mx.clear_cache()
                release_torch_memory(clear_cache=False)

                if on_progress is not None:
                    progress_pct = 25 + int((index / total) * 65)
                    if index == total:
                        on_progress(94, "Finalizing forced alignment")
                    else:
                        on_progress(progress_pct, self._make_progress_message(index, total))

            if on_progress is not None:
                on_progress(100, "Alignment complete")
            return words
        finally:
            del waveform
            release_torch_memory(clear_cache=False)

    def _build_alignment_windows(self, segments: list[AsrSegment]) -> list[list[AsrSegment]]:
        windows: list[list[AsrSegment]] = []
        current: list[AsrSegment] = []
        current_chars = 0

        for segment in segments:
            segment_chars = len(segment.text.strip())
            candidate = current + [segment]
            candidate_duration = candidate[-1].end - candidate[0].start
            candidate_chars = current_chars + segment_chars

            if current and (
                candidate_duration > _MAX_ALIGNMENT_WINDOW_SECONDS
                or candidate_chars > _MAX_ALIGNMENT_WINDOW_CHARS
            ):
                windows.append(current)
                current = [segment]
                current_chars = segment_chars
                continue

            current = candidate
            current_chars = candidate_chars

        if current:
            windows.append(current)

        return windows
