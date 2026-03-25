"""Merge ASR text with diarization segments on the time axis.

The core problem: ASR produces *text* and diarization produces *speaker
turns*.  Neither alone gives us speaker-attributed utterances.  This
module reconciles the two by slicing the ASR text according to diarization
boundaries.

Strategy
--------
1.  If the ForcedAligner has already been applied and we have word-level
    timestamps for the full transcript, we assign each word to the
    diarization segment whose overlap is maximal, then concatenate words
    that belong to the same consecutive speaker turn.

2.  If we only have the full-text output from ASR (no word timestamps),
    we fall back to a simpler heuristic: each diarization segment is
    treated as one utterance and gets a proportional slice of the ASR
    text based on its share of total speaking time.  This is imprecise
    but good enough for the MVP - the text will be readable, and the
    speaker labels will be correct at the turn level.

Both paths produce a ``list[Utterance]``.
"""

from __future__ import annotations

from .schema import (
    DiarizationSegment,
    Utterance,
    WordTimestamp,
)


_SHORT_TURN_SECONDS = 0.35
_BRIDGED_TURN_SECONDS = 1.0
_SHORT_WORD_RUN_SECONDS = 0.8
_SHORT_WORD_RUN_WORDS = 2


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Return the overlap duration between two intervals."""
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


# ---------------------------------------------------------------------------
# Strategy 1: word-level merge (preferred)
# ---------------------------------------------------------------------------


def merge_with_words(
    words: list[WordTimestamp],
    diarization: list[DiarizationSegment],
) -> list[Utterance]:
    """Assign each word to a speaker and concatenate into utterances."""
    diarization = _normalize_diarization_segments(diarization)
    if not words or not diarization:
        return []

    # Assign each word to the best-matching diarization segment
    assigned: list[tuple[str, WordTimestamp]] = []
    for w in words:
        best_seg = _pick_best_segment_for_word(w, diarization)
        assigned.append((best_seg.speaker_id, w))

    assigned = _smooth_word_speaker_assignments(assigned)

    # Merge consecutive words that share the same speaker
    utterances: list[Utterance] = []
    current_speaker: str | None = None
    current_words: list[WordTimestamp] = []

    for speaker, word in assigned:
        if speaker != current_speaker:
            if current_words and current_speaker is not None:
                utterances.append(_words_to_utterance(current_speaker, current_words))
            current_speaker = speaker
            current_words = [word]
        else:
            current_words.append(word)

    if current_words and current_speaker is not None:
        utterances.append(_words_to_utterance(current_speaker, current_words))

    return utterances


def _words_to_utterance(speaker: str, words: list[WordTimestamp]) -> Utterance:
    return Utterance(
        speaker_id=speaker,
        start=words[0].start,
        end=words[-1].end,
        text="".join(w.text for w in words),
        words=words,
    )


def _pick_best_segment_for_word(
    word: WordTimestamp,
    diarization: list[DiarizationSegment],
) -> DiarizationSegment:
    midpoint = (word.start + word.end) / 2.0
    containing = [seg for seg in diarization if seg.start <= midpoint <= seg.end]
    candidates = containing or diarization

    return max(
        candidates,
        key=lambda seg: (
            _overlap(word.start, word.end, seg.start, seg.end),
            -abs(midpoint - ((seg.start + seg.end) / 2.0)),
            _segment_duration(seg),
        ),
    )


def _smooth_word_speaker_assignments(
    assigned: list[tuple[str, WordTimestamp]],
) -> list[tuple[str, WordTimestamp]]:
    if len(assigned) < 3:
        return assigned

    runs = _group_assigned_runs(assigned)
    if len(runs) < 2:
        return assigned

    smoothed = [list(run) for run in runs]

    for idx, run in enumerate(runs):
        speaker, words = run
        run_duration = max(0.0, words[-1].end - words[0].start)
        is_short = len(words) <= _SHORT_WORD_RUN_WORDS or run_duration <= _SHORT_WORD_RUN_SECONDS
        if not is_short:
            continue

        prev_run = runs[idx - 1] if idx > 0 else None
        next_run = runs[idx + 1] if idx + 1 < len(runs) else None

        target_speaker: str | None = None
        if prev_run and next_run and prev_run[0] == next_run[0] and prev_run[0] != speaker:
            target_speaker = prev_run[0]
        elif idx == 0 and next_run and next_run[0] != speaker:
            target_speaker = next_run[0]
        elif idx == len(runs) - 1 and prev_run and prev_run[0] != speaker:
            target_speaker = prev_run[0]

        if target_speaker is not None:
            smoothed[idx][0] = target_speaker

    flattened: list[tuple[str, WordTimestamp]] = []
    for speaker, words in smoothed:
        flattened.extend((speaker, word) for word in words)
    return flattened


def _group_assigned_runs(
    assigned: list[tuple[str, WordTimestamp]],
) -> list[tuple[str, list[WordTimestamp]]]:
    runs: list[tuple[str, list[WordTimestamp]]] = []
    for speaker, word in assigned:
        if runs and runs[-1][0] == speaker:
            runs[-1][1].append(word)
        else:
            runs.append((speaker, [word]))
    return runs


# ---------------------------------------------------------------------------
# Strategy 2: proportional text split (fallback)
# ---------------------------------------------------------------------------


def merge_proportional(
    full_text: str,
    diarization: list[DiarizationSegment],
) -> list[Utterance]:
    """Split *full_text* across diarization segments proportionally.

    This is a rough heuristic used when word-level timestamps are
    unavailable.  The text is distributed to each speaker turn in
    proportion to the duration of that turn.
    """
    if not full_text.strip() or not diarization:
        return []

    # Merge consecutive segments from the same speaker
    merged_segments = _normalize_diarization_segments(diarization)

    total_duration = sum(s.end - s.start for s in merged_segments)
    if total_duration <= 0:
        return [
            Utterance(
                speaker_id=merged_segments[0].speaker_id,
                start=merged_segments[0].start,
                end=merged_segments[-1].end,
                text=full_text.strip(),
            )
        ]

    chars = list(full_text.strip())
    total_chars = len(chars)
    offset = 0
    utterances: list[Utterance] = []

    for i, seg in enumerate(merged_segments):
        duration = seg.end - seg.start
        proportion = duration / total_duration
        # Last segment gets all remaining chars to avoid rounding losses
        if i == len(merged_segments) - 1:
            n_chars = total_chars - offset
        else:
            n_chars = max(1, round(total_chars * proportion))
            n_chars = min(n_chars, total_chars - offset)

        segment_text = "".join(chars[offset : offset + n_chars]).strip()
        offset += n_chars

        if segment_text:
            utterances.append(
                Utterance(
                    speaker_id=seg.speaker_id,
                    start=round(seg.start, 3),
                    end=round(seg.end, 3),
                    text=segment_text,
                )
            )

    return utterances


def _merge_consecutive_speakers(
    segments: list[DiarizationSegment],
) -> list[DiarizationSegment]:
    """Merge adjacent diarization segments that share the same speaker."""
    if not segments:
        return []
    merged: list[DiarizationSegment] = [segments[0]]
    for seg in segments[1:]:
        if seg.speaker_id == merged[-1].speaker_id:
            # Extend the previous segment
            merged[-1] = DiarizationSegment(
                speaker_id=seg.speaker_id,
                start=merged[-1].start,
                end=seg.end,
            )
        else:
            merged.append(seg)
    return merged


def _normalize_diarization_segments(
    segments: list[DiarizationSegment],
) -> list[DiarizationSegment]:
    cleaned = [
        seg
        for seg in sorted(segments, key=lambda seg: (seg.start, seg.end, seg.speaker_id))
        if seg.end > seg.start
    ]
    if not cleaned:
        return []

    normalized = _merge_consecutive_speakers(cleaned)
    while True:
        rewritten = list(normalized)
        changed = False

        for idx, seg in enumerate(normalized):
            duration = _segment_duration(seg)

            if idx == 0:
                if len(normalized) > 1 and duration <= _SHORT_TURN_SECONDS:
                    next_seg = normalized[1]
                    if seg.speaker_id != next_seg.speaker_id:
                        rewritten[idx] = _with_speaker(seg, next_seg.speaker_id)
                        changed = True
                continue

            if idx == len(normalized) - 1:
                if duration <= _SHORT_TURN_SECONDS:
                    prev_seg = normalized[idx - 1]
                    if seg.speaker_id != prev_seg.speaker_id:
                        rewritten[idx] = _with_speaker(seg, prev_seg.speaker_id)
                        changed = True
                continue

            prev_seg = normalized[idx - 1]
            next_seg = normalized[idx + 1]

            if (
                duration <= _BRIDGED_TURN_SECONDS
                and prev_seg.speaker_id == next_seg.speaker_id
                and seg.speaker_id != prev_seg.speaker_id
            ):
                rewritten[idx] = _with_speaker(seg, prev_seg.speaker_id)
                changed = True
                continue

            if duration <= _SHORT_TURN_SECONDS:
                target = (
                    prev_seg
                    if _segment_duration(prev_seg) >= _segment_duration(next_seg)
                    else next_seg
                )
                if seg.speaker_id != target.speaker_id:
                    rewritten[idx] = _with_speaker(seg, target.speaker_id)
                    changed = True

        merged = _merge_consecutive_speakers(rewritten)
        if not changed or merged == normalized:
            return merged
        normalized = merged


def _segment_duration(segment: DiarizationSegment) -> float:
    return max(0.0, segment.end - segment.start)


def _with_speaker(segment: DiarizationSegment, speaker_id: str) -> DiarizationSegment:
    return DiarizationSegment(speaker_id=speaker_id, start=segment.start, end=segment.end)
