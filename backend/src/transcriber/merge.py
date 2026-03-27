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

import re

try:
    import nagisa
except ImportError:  # pragma: no cover - optional at runtime
    nagisa = None

from .schema import (
    DiarizationSegment,
    Utterance,
    WordTimestamp,
)

_SHORT_TURN_SECONDS = 0.35
_BRIDGED_TURN_SECONDS = 1.0
_SHORT_WORD_RUN_SECONDS = 0.8
_SHORT_WORD_RUN_WORDS = 2
_LONG_WORD_RUN_SECONDS = 3.0
_LONG_WORD_RUN_WORDS = 8
_TERMINAL_PUNCTUATION = ("\u3002", "\uff01", "\uff1f", "!", "?", "\n")
_SOFT_PUNCTUATION = ("\u3001", "\uff0c", ",", "\uff1b", ";", "\uff1a", ":")
_MIN_SPLIT_CHARS = 30
_TARGET_SPLIT_CHARS = 70
_HARD_SPLIT_CHARS = 110
_MIN_SPLIT_DURATION_SECONDS = 3.0
_TARGET_SPLIT_DURATION_SECONDS = 8.0
_HARD_SPLIT_DURATION_SECONDS = 14.0
_SOFT_SPLIT_GAP_SECONDS = 0.45
_LONG_SPLIT_GAP_SECONDS = 0.9


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
                utterances.extend(_split_words_to_utterances(current_speaker, current_words))
            current_speaker = speaker
            current_words = [word]
        else:
            current_words.append(word)

    if current_words and current_speaker is not None:
        utterances.extend(_split_words_to_utterances(current_speaker, current_words))

    return utterances


def _words_to_utterance(speaker: str, words: list[WordTimestamp]) -> Utterance:
    return Utterance(
        speaker_id=speaker,
        start=words[0].start,
        end=words[-1].end,
        text="".join(w.text for w in words),
        words=words,
    )


def _split_words_to_utterances(speaker: str, words: list[WordTimestamp]) -> list[Utterance]:
    if not words:
        return []

    chunks: list[list[WordTimestamp]] = []
    current: list[WordTimestamp] = [words[0]]
    current_chars = _text_length(words[0].text)

    for word in words[1:]:
        prev_word = current[-1]
        current_duration = max(0.0, prev_word.end - current[0].start)
        gap = max(0.0, word.start - prev_word.end)

        if _should_split_word_chunk(
            text=current[-1].text,
            chars=current_chars,
            duration=current_duration,
            gap=gap,
        ):
            chunks.append(current)
            current = [word]
            current_chars = _text_length(word.text)
            continue

        current.append(word)
        current_chars += _text_length(word.text)

    if current:
        chunks.append(current)

    return [_words_to_utterance(speaker, chunk) for chunk in _merge_tiny_word_chunks(chunks)]


def _should_split_word_chunk(*, text: str, chars: int, duration: float, gap: float) -> bool:
    if chars >= _HARD_SPLIT_CHARS or duration >= _HARD_SPLIT_DURATION_SECONDS:
        return True

    if _ends_with_punctuation(text, _TERMINAL_PUNCTUATION):
        return chars >= _MIN_SPLIT_CHARS or duration >= _MIN_SPLIT_DURATION_SECONDS

    if gap >= _LONG_SPLIT_GAP_SECONDS:
        return chars >= (_MIN_SPLIT_CHARS // 2) or duration >= (_MIN_SPLIT_DURATION_SECONDS / 2)

    if _ends_with_punctuation(text, _SOFT_PUNCTUATION):
        return chars >= _TARGET_SPLIT_CHARS or duration >= _TARGET_SPLIT_DURATION_SECONDS

    if gap >= _SOFT_SPLIT_GAP_SECONDS:
        return chars >= _TARGET_SPLIT_CHARS or duration >= _TARGET_SPLIT_DURATION_SECONDS

    return False


def _merge_tiny_word_chunks(chunks: list[list[WordTimestamp]]) -> list[list[WordTimestamp]]:
    if len(chunks) < 2:
        return chunks

    merged: list[list[WordTimestamp]] = []
    for chunk in chunks:
        if not merged:
            merged.append(list(chunk))
            continue

        text = "".join(word.text for word in chunk).strip()
        duration = max(0.0, chunk[-1].end - chunk[0].start)
        if len(text) < 12 and duration < 1.2:
            merged[-1].extend(chunk)
            continue

        merged.append(list(chunk))

    return merged


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
        elif (
            prev_run
            and next_run
            and prev_run[0] != speaker
            and next_run[0] != speaker
            and _run_duration(prev_run[1]) >= _LONG_WORD_RUN_SECONDS
            and _run_duration(next_run[1]) >= _LONG_WORD_RUN_SECONDS
            and len(prev_run[1]) >= _LONG_WORD_RUN_WORDS
            and len(next_run[1]) >= _LONG_WORD_RUN_WORDS
        ):
            target_speaker = (
                prev_run[0]
                if _run_duration(prev_run[1]) >= _run_duration(next_run[1])
                else next_run[0]
            )
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


def _run_duration(words: list[WordTimestamp]) -> float:
    if not words:
        return 0.0
    return max(0.0, words[-1].end - words[0].start)


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
            utterances.extend(_split_proportional_utterance(seg, segment_text))

    return utterances


def _split_proportional_utterance(
    segment: DiarizationSegment,
    text: str,
) -> list[Utterance]:
    chunks = _split_text_chunks(text)
    if len(chunks) == 1:
        return [
            Utterance(
                speaker_id=segment.speaker_id,
                start=round(segment.start, 3),
                end=round(segment.end, 3),
                text=chunks[0],
            )
        ]

    total_units = sum(max(1, _text_length(chunk)) for chunk in chunks)
    remaining_duration = max(0.0, segment.end - segment.start)
    current_start = segment.start
    utterances: list[Utterance] = []
    remaining_units = total_units

    for index, chunk in enumerate(chunks):
        units = max(1, _text_length(chunk))
        if index == len(chunks) - 1 or remaining_units <= 0:
            chunk_end = segment.end
        else:
            chunk_duration = remaining_duration * (units / remaining_units)
            chunk_end = min(segment.end, current_start + max(0.5, chunk_duration))

        utterances.append(
            Utterance(
                speaker_id=segment.speaker_id,
                start=round(current_start, 3),
                end=round(chunk_end, 3),
                text=chunk,
            )
        )
        remaining_duration = max(0.0, segment.end - chunk_end)
        current_start = chunk_end
        remaining_units -= units

    if utterances:
        utterances[-1].end = round(segment.end, 3)

    return utterances


def _split_text_chunks(text: str) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []

    units = _split_text_units(stripped)
    if len(units) == 1 and _text_length(units[0]) <= _HARD_SPLIT_CHARS:
        return units

    chunks: list[str] = []
    current = ""

    for unit in units:
        candidate = f"{current}{unit}".strip()
        if not current:
            current = unit.strip()
            continue

        if _text_length(current) >= _TARGET_SPLIT_CHARS:
            chunks.append(current.strip())
            current = unit.strip()
            continue

        if _text_length(candidate) > _HARD_SPLIT_CHARS:
            chunks.append(current.strip())
            current = unit.strip()
            continue

        current = candidate

    if current:
        chunks.append(current.strip())

    final_chunks: list[str] = []
    for chunk in chunks:
        if _text_length(chunk) > _HARD_SPLIT_CHARS:
            final_chunks.extend(_hard_split_text_chunk(chunk))
        else:
            final_chunks.append(chunk)

    return [chunk for chunk in final_chunks if chunk]


def _split_text_units(text: str) -> list[str]:
    units: list[str] = []
    current = ""

    for char in text:
        current += char
        if char in _TERMINAL_PUNCTUATION or char == "\n":
            units.append(current.strip())
            current = ""

    if current.strip():
        units.append(current.strip())

    return units or [text]


def _hard_split_text_chunk(text: str) -> list[str]:
    tokens = _tokenize_text(text)
    if len(tokens) > 1:
        chunks: list[str] = []
        current = ""

        for token in tokens:
            cleaned_token = token if current else token.lstrip()
            candidate = f"{current}{cleaned_token}"
            if current and _text_length(candidate) > _HARD_SPLIT_CHARS:
                chunks.append(current.strip())
                current = token.lstrip()
                continue

            current = candidate
            if _text_length(current) >= _TARGET_SPLIT_CHARS and _ends_with_punctuation(
                token,
                _TERMINAL_PUNCTUATION + _SOFT_PUNCTUATION,
            ):
                chunks.append(current.strip())
                current = ""

        if current.strip():
            chunks.append(current.strip())

        return _merge_tiny_text_chunks(chunks)

    chunks: list[str] = []
    remaining = text.strip()
    while _text_length(remaining) > _HARD_SPLIT_CHARS:
        split_at = _find_split_index(remaining)
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()

    if remaining:
        chunks.append(remaining)

    return _merge_tiny_text_chunks(chunks)


def _find_split_index(text: str) -> int:
    upper = min(len(text), _HARD_SPLIT_CHARS)
    lower = min(len(text), _MIN_SPLIT_CHARS)

    for idx in range(upper, lower, -1):
        if text[idx - 1] in _TERMINAL_PUNCTUATION + _SOFT_PUNCTUATION:
            return idx

    for idx in range(upper, lower, -1):
        if text[idx - 1].isspace():
            return idx

    return upper


def _tokenize_text(text: str) -> list[str]:
    if not text:
        return []

    if nagisa is not None:
        try:
            tagged = nagisa.tagging(text)
            if tagged.words:
                tokens: list[str] = []
                cursor = 0
                for word in tagged.words:
                    idx = text.find(word, cursor)
                    if idx < 0:
                        break
                    tokens.append(text[cursor : idx + len(word)])
                    cursor = idx + len(word)
                else:
                    if cursor < len(text):
                        if tokens:
                            tokens[-1] += text[cursor:]
                        else:
                            tokens.append(text[cursor:])
                    return [token for token in tokens if token]
        except Exception:
            pass

    return [token for token in re.findall(r"\s*\S", text) if token]


def _merge_tiny_text_chunks(chunks: list[str]) -> list[str]:
    if len(chunks) < 2:
        return chunks

    merged: list[str] = []
    for chunk in chunks:
        if merged and _text_length(chunk) < 12:
            merged[-1] = f"{merged[-1]}{chunk}".strip()
            continue
        merged.append(chunk)
    return merged


def _ends_with_punctuation(text: str, punctuation: tuple[str, ...]) -> bool:
    stripped = text.rstrip()
    return stripped.endswith(punctuation)


def _text_length(text: str) -> int:
    return len(text.strip())


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
