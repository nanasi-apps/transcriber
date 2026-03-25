"""Output data models for the transcription pipeline.

These types define the canonical intermediate and final representations.
All pipeline stages produce or consume these types, making it safe to
swap out ASR / diarization / alignment implementations without touching
the layers above.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

# ---------------------------------------------------------------------------
# Intermediate representations (per-stage outputs)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AsrSegment:
    """A contiguous block of recognised text with rough time boundaries.

    Produced by the ASR stage.  The boundaries come from the model's own
    chunking/segmentation and are *not* yet aligned
    to speaker turns.
    """

    start: float
    end: float
    text: str


@dataclass(frozen=True, slots=True)
class DiarizationSegment:
    """A speaker turn detected by the diarization stage.

    ``speaker_id`` is an opaque label such as ``"speaker_00"``.
    """

    speaker_id: str
    start: float
    end: float


# ---------------------------------------------------------------------------
# Word-level timestamps (optional, from ForcedAligner)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WordTimestamp:
    """Timestamp for a single word / character unit."""

    text: str
    start: float
    end: float


# ---------------------------------------------------------------------------
# Final output
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Utterance:
    """A single speaker-attributed utterance - the fundamental output unit.

    ``words`` is populated only when the forced-aligner is applied to
    this utterance.
    """

    speaker_id: str
    start: float
    end: float
    text: str
    words: list[WordTimestamp] | None = None


@dataclass(slots=True)
class TranscriptionResult:
    """Complete result of the transcription pipeline."""

    utterances: list[Utterance]
    audio_duration: float
    metadata: dict = field(default_factory=dict)

    # -- serialisation helpers -----------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def to_text(self) -> str:
        """Human-readable formatted text."""
        lines: list[str] = []
        for u in self.utterances:
            header = f"[{u.speaker_id}] ({u.start:.1f}s - {u.end:.1f}s)"
            lines.append(header)
            lines.append(u.text)
            lines.append("")
        return "\n".join(lines)
