"""Speaker diarization wrapper (pyannote).

Single responsibility: take an audio path and return ``DiarizationSegment``
list telling *who* spoke *when*.  No text is produced here.
"""

from __future__ import annotations

import logging
import os
import warnings
from collections.abc import Callable
from pathlib import Path

import torch

from .env import load_local_env
from .schema import DiarizationSegment

logger = logging.getLogger(__name__)

load_local_env()


class DiarizationEngine:
    """Thin wrapper around ``pyannote.audio.Pipeline``."""

    def __init__(
        self,
        model_name: str = "pyannote/speaker-diarization-community-1",
        *,
        hf_token: str | None = None,
        device: torch.device | None = None,
    ) -> None:
        self.model_name = model_name
        self.hf_token = hf_token or os.environ.get("HF_TOKEN")
        if device is None:
            if torch.cuda.is_available():
                device = torch.device("cuda:0")
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = torch.device("mps")
            else:
                device = torch.device("cpu")
        self.device = device
        self._pipeline = None

    def _ensure_pipeline(self, on_progress: Callable[[int, str], None] | None = None):
        if self._pipeline is not None:
            if on_progress is not None:
                on_progress(35, "Diarization model ready")
            return
        from pyannote.audio import Pipeline

        # Deliberately import here so the package is optional until diarization
        # is actually used.  Validate HF token early to provide a clear error
        # message instead of hanging silently during model download.
        if not self.hf_token:
            raise RuntimeError(
                "HuggingFace token is required for pyannote. "
                "Set HF_TOKEN env var or pass hf_token= to DiarizationEngine."
            )

        # Avoid logging the full token; only show a short masked prefix for
        # diagnostics.
        masked = f"{self.hf_token[:6]}..." if self.hf_token else "(none)"
        logger.info(
            "Preparing to load diarization pipeline %s on %s (token=%s)",
            self.model_name,
            self.device,
            masked,
        )
        if on_progress is not None:
            on_progress(2, "Checking Hugging Face access")

        # Verify token is valid with the HuggingFace hub before attempting the
        # heavy model download.  This surfaces authentication problems quickly.
        try:
            # Import locally to avoid adding an extra top-level dependency if
            # this path is not exercised.
            from huggingface_hub import whoami

            try:
                whoami(token=self.hf_token)
            except Exception as exc:  # pragma: no cover - network/credential errors
                logger.exception("HuggingFace token validation failed")
                raise RuntimeError(
                    "Invalid or unreachable HuggingFace token provided for diarization. "
                    "Ensure HF_TOKEN is set and network access to huggingface.co is available."
                ) from exc
        except Exception:
            # If huggingface_hub isn't available or whoami failed for some
            # unexpected reason, continue — the from_pretrained call will
            # still surface a helpful error.  We avoid failing here if the
            # extra import isn't present.
            logger.debug("Skipping explicit HF token validation (whoami unavailable)")

        logger.info("Loading diarization pipeline %s …", self.model_name)
        if on_progress is not None:
            on_progress(8, "Downloading/loading diarization model")
        try:
            self._pipeline = Pipeline.from_pretrained(self.model_name, token=self.hf_token)
            self._pipeline.to(self.device)
        except Exception as exc:  # pragma: no cover - runtime failures
            logger.exception("Failed to load diarization pipeline %s", self.model_name)
            raise RuntimeError(
                "Failed to load pyannote diarization pipeline. See logs for details. "
                "Common causes: missing/invalid HF_TOKEN, network issues, or incompatible torch/cuda runtime."
            ) from exc
        else:
            if on_progress is not None:
                on_progress(35, "Diarization model ready")

        logger.info("Diarization pipeline loaded on %s.", self.device)

    def diarize(
        self,
        audio_path: Path,
        *,
        num_speakers: int | None = None,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
        on_progress: Callable[[int, str], None] | None = None,
    ) -> list[DiarizationSegment]:
        """Run speaker diarization on *audio_path*.

        Returns a list of ``DiarizationSegment`` sorted by start time.
        Speaker IDs are normalised to ``speaker_00``, ``speaker_01``, …
        in the order they first appear.
        """
        self._ensure_pipeline(on_progress=on_progress)
        assert self._pipeline is not None

        kwargs: dict = {}
        if num_speakers is not None:
            kwargs["num_speakers"] = num_speakers
        if min_speakers is not None:
            kwargs["min_speakers"] = min_speakers
        if max_speakers is not None:
            kwargs["max_speakers"] = max_speakers

        logger.info("Running diarization on %s …", audio_path)
        if on_progress is not None:
            on_progress(40, "Running speaker diarization")

        def pyannote_hook(step_name: str, _artifact=None, **hook_kwargs) -> None:
            if on_progress is None:
                return

            completed = hook_kwargs.get("completed")
            total = hook_kwargs.get("total")

            if step_name == "segmentation":
                if isinstance(completed, int) and isinstance(total, int) and total > 0:
                    ratio = min(1.0, max(0.0, completed / total))
                    pct = 40 + int(28 * ratio)
                    on_progress(
                        pct,
                        f"Segmenting speech ({completed}/{total}, {int(ratio * 100)}%)",
                    )
                else:
                    on_progress(68, "Counting active speakers")
                return

            if step_name == "speaker_counting":
                on_progress(72, "Counting active speakers")
                return

            if step_name == "embeddings":
                if isinstance(completed, int) and isinstance(total, int) and total > 0:
                    ratio = min(1.0, max(0.0, completed / total))
                    pct = 72 + int(16 * ratio)
                    on_progress(
                        pct,
                        f"Extracting speaker embeddings ({completed}/{total}, {int(ratio * 100)}%)",
                    )
                else:
                    on_progress(88, "Clustering speakers")
                return

            if step_name == "discrete_diarization":
                on_progress(94, "Finalizing speaker diarization")
                return

            on_progress(45, f"Running speaker diarization: {step_name}")

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"std\(\): degrees of freedom is <= 0.*",
                category=UserWarning,
                module=r"pyannote\.audio\.models\.blocks\.pooling",
            )
            output = self._pipeline(str(audio_path), hook=pyannote_hook, **kwargs)

        # pyannote.audio 4 returns a DiarizeOutput object whose speaker turns
        # live under ``speaker_diarization``. Older releases returned an
        # Annotation directly. Support both shapes.
        raw_segments: list[tuple[str, float, float]] = []
        if hasattr(output, "exclusive_speaker_diarization"):
            for turn, speaker in output.exclusive_speaker_diarization:
                raw_segments.append((str(speaker), turn.start, turn.end))
        elif hasattr(output, "speaker_diarization"):
            for turn, speaker in output.speaker_diarization:
                raw_segments.append((str(speaker), turn.start, turn.end))
        elif hasattr(output, "itertracks"):
            for turn, _, speaker in output.itertracks(yield_label=True):
                raw_segments.append((str(speaker), turn.start, turn.end))
        else:
            raise RuntimeError(f"Unsupported diarization output type: {type(output).__name__}")

        raw_segments.sort(key=lambda seg: (seg[1], seg[2], seg[0]))

        # Normalise speaker IDs to deterministic order-of-appearance labels
        speaker_map: dict[str, str] = {}
        for speaker, _, _ in raw_segments:
            if speaker not in speaker_map:
                speaker_map[speaker] = f"speaker_{len(speaker_map):02d}"

        segments = [
            DiarizationSegment(
                speaker_id=speaker_map[spk],
                start=round(start, 3),
                end=round(end, 3),
            )
            for spk, start, end in raw_segments
        ]

        logger.info(
            "Diarization complete: %d segments, %d speakers.",
            len(segments),
            len(speaker_map),
        )
        if on_progress is not None:
            on_progress(100, "Diarization complete")
        return segments
