"""CLI entry point for the transcription pipeline.

Usage::

    # Basic - JSON output to stdout
    transcribe audio.wav

    # Save JSON to file
    transcribe audio.wav -o result.json

    # Human-readable text output
    transcribe audio.wav --format text

    # With forced alignment
    transcribe audio.wav --align

    # Specify speaker count hints
    transcribe audio.wav --min-speakers 2 --max-speakers 5
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .aligner import DEFAULT_ALIGNER_MODEL
from .asr import DEFAULT_WHISPER_MODEL


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="transcribe",
        description="Speaker-attributed transcription of audio files.",
    )
    p.add_argument(
        "audio",
        type=Path,
        help="Path to the input audio/video file.",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write output to this file instead of stdout.",
    )
    p.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format (default: json).",
    )

    # -- ASR --
    p.add_argument(
        "--asr-model",
        default=DEFAULT_WHISPER_MODEL,
        help="Whisper MLX model ID for ASR.",
    )
    p.add_argument(
        "--language",
        default="Japanese",
        help="Language hint passed to ASR and aligner.",
    )
    p.add_argument(
        "--max-new-tokens",
        type=int,
        default=4096,
        help="Max tokens for ASR generation.",
    )

    # -- Diarization --
    p.add_argument(
        "--diarization-model",
        default="pyannote/speaker-diarization-community-1",
        help="HuggingFace model ID for speaker diarization.",
    )
    p.add_argument(
        "--hf-token",
        default=None,
        help="HuggingFace token (or set HF_TOKEN env var).",
    )
    p.add_argument(
        "--num-speakers",
        type=int,
        default=None,
        help="Exact number of speakers (if known).",
    )
    p.add_argument(
        "--min-speakers",
        type=int,
        default=None,
        help="Minimum number of speakers.",
    )
    p.add_argument(
        "--max-speakers",
        type=int,
        default=None,
        help="Maximum number of speakers.",
    )

    # -- Alignment --
    align_group = p.add_mutually_exclusive_group()
    align_group.add_argument(
        "--align",
        action="store_true",
        dest="align",
        help="Enable forced alignment for word-level timestamps (default).",
    )
    align_group.add_argument(
        "--no-align",
        action="store_false",
        dest="align",
        help="Disable forced alignment and use fallback speaker/text merge.",
    )
    p.set_defaults(align=True)
    p.add_argument(
        "--aligner-model",
        default=DEFAULT_ALIGNER_MODEL,
        help="HuggingFace model ID for forced aligner.",
    )

    # -- Misc --
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging.",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Logging setup
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    if not args.audio.exists():
        parser.error(f"File not found: {args.audio}")

    # Build pipeline config
    from .pipeline import Pipeline, PipelineConfig, RunParams

    config = PipelineConfig(
        asr_model=args.asr_model,
        asr_max_new_tokens=args.max_new_tokens,
        diarization_model=args.diarization_model,
        hf_token=args.hf_token,
        aligner_model=args.aligner_model,
    )

    run_params = RunParams(
        asr_language=args.language,
        use_aligner=args.align,
        aligner_language=args.language,
        num_speakers=args.num_speakers,
        min_speakers=args.min_speakers,
        max_speakers=args.max_speakers,
    )

    pipe = Pipeline(config)
    result = pipe.run(args.audio, params=run_params)

    # Format output
    output = result.to_json() if args.format == "json" else result.to_text()

    # Write output
    if args.output:
        args.output.write_text(output, encoding="utf-8")
        logging.getLogger(__name__).info("Output written to %s", args.output)
    else:
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")


if __name__ == "__main__":
    main()
