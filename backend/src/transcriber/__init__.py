"""Transcriber - speaker-attributed transcription pipeline.

Core pipeline: Qwen3-ASR + pyannote diarization + Qwen3-ForcedAligner.
"""

from .schema import (
    AsrSegment,
    DiarizationSegment,
    TranscriptionResult,
    Utterance,
    WordTimestamp,
)

__all__ = [
    "AsrSegment",
    "DiarizationSegment",
    "TranscriptionResult",
    "Utterance",
    "WordTimestamp",
]
