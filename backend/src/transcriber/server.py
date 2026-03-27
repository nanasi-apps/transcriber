"""FastAPI server for the speaker-attributed transcription pipeline.

Endpoints
---------
POST /api/transcribe/upload   Upload audio -> start job -> return job_id
GET  /api/jobs/{job_id}       Poll job status / progress / result
GET  /api/health              Liveness probe
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .pipeline import Pipeline, PipelineConfig, RunParams

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Transcriber API",
    version="0.2.0",
    description=(
        "Speaker-attributed transcription: Whisper MLX ASR + "
        "MLX forced alignment + pyannote diarization"
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

UPLOAD_DIR = Path(tempfile.gettempdir()) / "transcriber_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Singleton pipeline - models are lazy-loaded on first request and reused
# across all jobs.  Only one Pipeline instance is ever created.
_pipeline: Pipeline | None = None
_background_tasks: set[asyncio.Task] = set()

# Completed / errored jobs are purged after this many seconds.
_JOB_TTL_SECONDS: int = 600  # 10 minutes


def _get_pipeline() -> Pipeline:
    """Return the singleton Pipeline, creating it on first call."""
    global _pipeline
    if _pipeline is None:
        _pipeline = Pipeline(PipelineConfig())
    return _pipeline


# ---------------------------------------------------------------------------
# Job bookkeeping
# ---------------------------------------------------------------------------


class JobState:
    __slots__ = (
        "completed_at",
        "error",
        "message",
        "progress",
        "result_path",
        "stage",
        "started_at",
        "status",
    )

    def __init__(self) -> None:
        self.status: str = "queued"
        self.stage: str = "queued"
        self.progress: int = 0
        self.message: str = "Queued"
        self.result_path: Path | None = None
        self.error: str | None = None
        self.started_at: float = time.monotonic()
        self.completed_at: float | None = None  # monotonic timestamp


_jobs: dict[str, JobState] = {}

# Stage -> overall progress % mapping (cumulative upper bounds)
_STAGE_WEIGHT: dict[str, tuple[int, int]] = {
    "audio_prep": (0, 5),
    "asr": (5, 45),
    "diarization": (45, 85),
    "alignment": (85, 92),
    "merge": (92, 98),
    "done": (100, 100),
}


def _make_progress_callback(job: JobState):
    """Return a callback that maps per-stage progress to overall %."""

    def callback(stage: str, pct: int, msg: str) -> None:
        lo, hi = _STAGE_WEIGHT.get(stage, (0, 100))
        overall = lo + int((hi - lo) * pct / 100)
        job.stage = stage
        job.progress = min(overall, 100)
        job.message = msg
        if stage != "done":
            job.status = "processing"

    return callback


def _purge_expired_jobs() -> None:
    """Remove completed/errored jobs older than *_JOB_TTL_SECONDS*."""
    now = time.monotonic()
    expired = [
        jid
        for jid, js in _jobs.items()
        if js.completed_at is not None and (now - js.completed_at) > _JOB_TTL_SECONDS
    ]
    for jid in expired:
        result_path = _jobs[jid].result_path
        if result_path is not None:
            with suppress(OSError):
                result_path.unlink(missing_ok=True)
        del _jobs[jid]
    if expired:
        logger.debug("Purged %d expired job(s).", len(expired))


def _load_job_result(job: JobState) -> dict | None:
    if job.result_path is None:
        return None

    try:
        return json.loads(job.result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Failed to read result file %s", job.result_path)
        return None


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class JobCreatedResponse(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str  # queued | processing | done | error
    stage: str
    progress: int  # 0-100
    message: str
    processing_time: float | None = None
    result: dict | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/transcribe/upload", response_model=JobCreatedResponse)
async def transcribe_upload(
    file: Annotated[UploadFile, File(...)],
    language: str = Query("Japanese", description="Language hint for ASR"),
    align: bool = Query(True, description="Enable forced alignment"),
    num_speakers: int | None = Query(None, description="Exact speaker count"),
    min_speakers: int | None = Query(None, description="Min speakers"),
    max_speakers: int | None = Query(None, description="Max speakers"),
    hf_token: str | None = Query(None, description="HuggingFace token (or use HF_TOKEN env)"),
) -> JobCreatedResponse:
    """Upload an audio file and start a transcription job."""
    suffix = Path(file.filename or "upload").suffix or ".bin"
    supported = {".mp4", ".wav", ".mp3", ".m4a", ".webm", ".ogg", ".flac", ".aac", ".wma"}
    if suffix.lower() not in supported:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    # Save uploaded file
    target = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    with target.open("wb") as buf:
        while chunk := await file.read(1024 * 1024):
            buf.write(chunk)
    await file.close()

    # Per-run params (lightweight - no model loading)
    run_params = RunParams(
        asr_language=language,
        use_aligner=align,
        aligner_language=language,
        num_speakers=num_speakers,
        min_speakers=min_speakers,
        max_speakers=max_speakers,
    )

    # Shared singleton - models loaded once and reused
    pipe = _get_pipeline()
    if hf_token and pipe.config.hf_token is None:
        pipe.config.hf_token = hf_token

    job_id = uuid.uuid4().hex
    job = JobState()
    _jobs[job_id] = job

    # Opportunistic cleanup of old jobs
    _purge_expired_jobs()

    async def runner() -> None:
        try:
            result = await asyncio.to_thread(
                pipe.run,
                target,
                params=run_params,
                on_progress=_make_progress_callback(job),
            )
            result_path = UPLOAD_DIR / f"{job_id}.result.json"
            result_path.write_text(
                json.dumps(result.to_dict(), ensure_ascii=False), encoding="utf-8"
            )
            job.result_path = result_path
            job.status = "done"
            job.stage = "done"
            job.progress = 100
            job.message = "Complete"
        except Exception as exc:
            logger.exception("Transcription job %s failed", job_id)
            job.status = "error"
            job.progress = 100
            job.message = str(exc)
            job.error = str(exc)
        finally:
            job.completed_at = time.monotonic()
            with suppress(OSError):
                target.unlink(missing_ok=True)

    task = asyncio.create_task(runner())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return JobCreatedResponse(job_id=job_id)


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
async def job_status(job_id: str) -> JobStatusResponse:
    """Poll the status of a transcription job."""
    _purge_expired_jobs()
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusResponse(
        job_id=job_id,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        message=job.error or job.message,
        processing_time=(
            round((job.completed_at or time.monotonic()) - job.started_at, 2)
            if job.started_at is not None
            else None
        ),
        result=_load_job_result(job),
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def start() -> None:
    """Start the uvicorn server."""
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765)


if __name__ == "__main__":
    start()
