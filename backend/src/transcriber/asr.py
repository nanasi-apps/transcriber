"""Whisper MLX ASR wrapper.

Single responsibility: take an audio path and return recognised text.
All model-specific knobs are isolated here so swapping the ASR backend
later only touches this file.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import mlx.core as mx
import torch

from .audio import ensure_wav
from .progress import start_progress_ticker
from .schema import AsrSegment

logger = logging.getLogger(__name__)


DEFAULT_WHISPER_MODEL = "mlx-community/whisper-large-v3-mlx"


def _resolve_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda:0")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _to_whisper_language(language: str) -> str:
    normalized = language.strip().lower()
    language_map = {
        "japanese": "ja",
        "ja": "ja",
        "english": "en",
        "en": "en",
    }
    return language_map.get(normalized, normalized)


class AsrEngine:
    """Thin wrapper around `mlx_whisper.transcribe`."""

    def __init__(
        self,
        model_name: str = DEFAULT_WHISPER_MODEL,
        *,
        device: torch.device | None = None,
        dtype: torch.dtype | None = None,
        chunk_seconds: int = 60,
        max_inference_batch_size: int = 1,
        max_new_tokens: int = 4096,
    ) -> None:
        self.model_name = model_name
        self.device = device or _resolve_device()
        self.dtype = dtype or torch.float32
        self.chunk_seconds = max(15, int(chunk_seconds))
        self.max_new_tokens = max_new_tokens
        self._mlx_whisper = None

    def _ensure_runtime(self) -> None:
        if self._mlx_whisper is not None:
            return

        logger.info("Loading ASR runtime for %s", self.model_name)
        try:
            import mlx_whisper

            self._mlx_whisper = mlx_whisper
        except Exception as exc:
            raise ImportError(
                "Whisper MLX backend requires mlx-whisper. Install it with: pip install mlx-whisper"
            ) from exc

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str = "Japanese",
        on_progress: Callable[[int, str], None] | None = None,
    ) -> list[AsrSegment]:
        """Transcribe *audio_path* and return Whisper segments."""
        wav_path, needs_cleanup = ensure_wav(audio_path)
        whisper_language = _to_whisper_language(language)

        try:
            if on_progress is not None:
                on_progress(2, "Loading ASR model")

            self._ensure_runtime()
            assert self._mlx_whisper is not None

            if on_progress is not None:
                on_progress(12, "ASR model ready")
                on_progress(18, "Running speech recognition")
                stop_ticker = start_progress_ticker(
                    on_progress,
                    start_pct=18,
                    end_pct=94,
                    base_message="Running speech recognition",
                    ramp_seconds=35.0,
                )
            else:
                stop_ticker = None

            result = self._mlx_whisper.transcribe(
                str(wav_path),
                path_or_hf_repo=self.model_name,
                language=whisper_language,
                word_timestamps=True,
                verbose=False,
                condition_on_previous_text=True,
                fp16=True,
            )
            if stop_ticker is not None:
                stop_ticker(94, "Finalizing speech recognition")

            raw_segments = result.get("segments", []) if isinstance(result, dict) else []
            segments: list[AsrSegment] = []
            total = max(1, len(raw_segments))
            for index, segment in enumerate(raw_segments, start=1):
                text = str(segment.get("text", "")).strip()
                start = float(segment.get("start", 0.0))
                end = float(segment.get("end", start))
                if text and end > start:
                    segments.append(
                        AsrSegment(
                            start=round(start, 3),
                            end=round(end, 3),
                            text=text,
                        )
                    )

                if on_progress is not None:
                    pct = min(99, 94 + int(5 * index / total))
                    on_progress(pct, f"Finalizing speech recognition... ({index}/{total})")

            mx.clear_cache()

            if segments:
                if on_progress is not None:
                    on_progress(100, "ASR complete")
                return segments

            text = ""
            if isinstance(result, dict):
                text = str(result.get("text", "")).strip()
            if text:
                max_end = max((segment.end for segment in segments), default=0.0)
                fallback_end = max(0.001, max_end)
                if on_progress is not None:
                    on_progress(100, "ASR complete")
                return [AsrSegment(start=0.0, end=round(fallback_end, 3), text=text)]
            if on_progress is not None:
                on_progress(100, "ASR complete")
            return []
        except Exception:
            if "stop_ticker" in locals() and stop_ticker is not None:
                stop_ticker()
            raise
        finally:
            if needs_cleanup:
                wav_path.unlink(missing_ok=True)
