"""Pipeline orchestrator.

Wires together audio normalisation, ASR, diarization, merge, and
(optionally) forced alignment into a single ``run()`` call that takes
an audio file and returns a ``TranscriptionResult``.

Each stage is independently replaceable - the orchestrator only
depends on the *interfaces*, not on specific model implementations.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import torch

from .aligner import AlignerEngine, DEFAULT_ALIGNER_MODEL
from .asr import AsrEngine, DEFAULT_WHISPER_MODEL
from .audio import ensure_wav, get_audio_duration
from .diarization import DiarizationEngine
from .memory import release_torch_memory
from .merge import merge_proportional, merge_with_words
from .schema import TranscriptionResult, Utterance

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Progress callback protocol
# ---------------------------------------------------------------------------

# stage name, 0-100 progress within that stage, human message
ProgressCallback = Callable[[str, int, str], None]


def _noop_progress(_stage: str, _pct: int, _msg: str) -> None:
    pass


# ---------------------------------------------------------------------------
# Config / Timings
# ---------------------------------------------------------------------------


@dataclass
class PipelineConfig:
    """Model identity - determines which weights are loaded.

    These values are set once at startup and do not change between runs.
    Per-run knobs (language, speaker counts, etc.) belong in ``RunParams``.
    """

    # ASR
    asr_model: str = DEFAULT_WHISPER_MODEL
    asr_max_new_tokens: int = 4096

    # Diarization
    diarization_model: str = "pyannote/speaker-diarization-community-1"
    hf_token: str | None = None

    # Forced alignment
    aligner_model: str = DEFAULT_ALIGNER_MODEL


@dataclass
class RunParams:
    """Per-run parameters that may change between jobs."""

    asr_language: str = "Japanese"
    use_aligner: bool = True
    aligner_language: str = "Japanese"
    num_speakers: int | None = None
    min_speakers: int | None = None
    max_speakers: int | None = None


@dataclass
class PipelineTimings:
    """Wall-clock durations (seconds) per stage for observability."""

    audio_prep: float = 0.0
    asr: float = 0.0
    diarization: float = 0.0
    alignment: float = 0.0
    merge: float = 0.0
    total: float = 0.0

    def to_dict(self) -> dict:
        return {k: round(v, 2) for k, v in self.__dict__.items()}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class Pipeline:
    """End-to-end transcription pipeline.

    Holds heavyweight model instances that persist for the lifetime of
    the server.  Per-run parameters are passed to ``run()`` via
    ``RunParams`` so the same Pipeline can serve many jobs without
    reloading models.

    A threading lock serialises ``run()`` calls - running two large
    model inferences concurrently would OOM most machines anyway.
    """

    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.config = config or PipelineConfig()
        self._asr: AsrEngine | None = None
        self._diarization: DiarizationEngine | None = None
        self._aligner: AlignerEngine | None = None
        self._lock = threading.Lock()

    # -- lazy engine accessors -----------------------------------------------

    @property
    def asr(self) -> AsrEngine:
        if self._asr is None:
            self._asr = AsrEngine(
                model_name=self.config.asr_model,
                max_new_tokens=self.config.asr_max_new_tokens,
            )
        return self._asr

    @property
    def diarization(self) -> DiarizationEngine:
        if self._diarization is None:
            self._diarization = DiarizationEngine(
                model_name=self.config.diarization_model,
                hf_token=self.config.hf_token,
            )
        return self._diarization

    @property
    def aligner(self) -> AlignerEngine:
        if self._aligner is None:
            self._aligner = AlignerEngine(model_name=self.config.aligner_model)
        return self._aligner

    # -- main entry point ----------------------------------------------------

    def run(
        self,
        audio_path: Path | str,
        *,
        params: RunParams | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> TranscriptionResult:
        """Execute the full pipeline on *audio_path*.

        *params* supplies per-run settings (language, speaker hints, etc.).
        If ``None``, defaults are used.

        *on_progress* is called with ``(stage, percent, message)`` at each
        major transition so that callers (server, CLI) can report status.

        Only one ``run()`` executes at a time (guarded by a lock) to
        prevent OOM from concurrent model inference.
        """
        with self._lock:
            return self._run_locked(audio_path, params=params, on_progress=on_progress)

    def _run_locked(
        self,
        audio_path: Path | str,
        *,
        params: RunParams | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> TranscriptionResult:
        rp = params or RunParams()
        progress = on_progress or _noop_progress
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        timings = PipelineTimings()
        t_total = time.monotonic()
        alignment_applied = False

        # 1. Audio normalisation
        progress("audio_prep", 0, "Preparing audio")
        t0 = time.monotonic()
        wav_path, needs_cleanup = ensure_wav(audio_path)
        audio_duration = get_audio_duration(audio_path)
        timings.audio_prep = time.monotonic() - t0
        logger.info("Audio: %.1f s, WAV at %s", audio_duration, wav_path)
        progress("audio_prep", 100, "Audio ready")

        try:
            # 2. ASR (text extraction)
            progress("asr", 0, "Loading ASR model")
            t0 = time.monotonic()
            with torch.inference_mode():
                asr_segments = self.asr.transcribe(
                    wav_path,
                    language=rp.asr_language,
                    on_progress=lambda pct, msg: progress("asr", pct, msg),
                )
            full_text = " ".join(seg.text for seg in asr_segments)
            timings.asr = time.monotonic() - t0
            logger.info("ASR done: %d chars in %.1f s", len(full_text), timings.asr)
            progress("asr", 100, "ASR complete")
            release_torch_memory()

            # 3. Speaker diarization
            progress("diarization", 0, "Loading diarization model")
            t0 = time.monotonic()
            with torch.inference_mode():
                dia_segments = self.diarization.diarize(
                    wav_path,
                    num_speakers=rp.num_speakers,
                    min_speakers=rp.min_speakers,
                    max_speakers=rp.max_speakers,
                    on_progress=lambda pct, msg: progress("diarization", pct, msg),
                )
            timings.diarization = time.monotonic() - t0
            logger.info(
                "Diarization done: %d segments in %.1f s",
                len(dia_segments),
                timings.diarization,
            )
            progress("diarization", 100, "Diarization complete")
            release_torch_memory()

            # 4. Merge ASR + diarization
            progress("merge", 0, "Merging results")
            t0 = time.monotonic()
            utterances: list[Utterance]

            if rp.use_aligner and full_text.strip():
                # 4a. Forced alignment -> word-level merge
                progress("alignment", 0, "Loading alignment model")
                t_align = time.monotonic()
                try:
                    with torch.inference_mode():
                        words = self.aligner.align_segments(
                            wav_path,
                            asr_segments,
                            language=rp.aligner_language,
                            on_progress=lambda pct, msg: progress("alignment", pct, msg),
                        )
                    timings.alignment = time.monotonic() - t_align
                    logger.info(
                        "Alignment done: %d words in %.1f s",
                        len(words),
                        timings.alignment,
                    )
                    progress("alignment", 100, "Alignment complete")
                    utterances = merge_with_words(words, dia_segments)
                    alignment_applied = True
                    release_torch_memory()
                except Exception:
                    logger.exception("Forced alignment failed; falling back to proportional merge")
                    progress("alignment", 100, "Alignment failed, using fallback merge")
                    utterances = merge_proportional(full_text, dia_segments)
            else:
                # 4b. Proportional fallback
                utterances = merge_proportional(full_text, dia_segments)

            timings.merge = time.monotonic() - t0 - timings.alignment
            logger.info("Merge done: %d utterances", len(utterances))
            progress("merge", 100, "Merge complete")

        finally:
            if needs_cleanup:
                wav_path.unlink(missing_ok=True)
            release_torch_memory()

        timings.total = time.monotonic() - t_total
        progress("done", 100, "Pipeline complete")

        return TranscriptionResult(
            utterances=utterances,
            audio_duration=round(audio_duration, 3),
            metadata={
                "asr_model": self.config.asr_model,
                "diarization_model": self.config.diarization_model,
                "aligner_model": self.config.aligner_model if alignment_applied else None,
                "alignment_requested": rp.use_aligner,
                "alignment_applied": alignment_applied,
                "language": rp.asr_language,
                "timings": timings.to_dict(),
            },
        )
