from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .analyzer import AudioDecodeError, analyze_audio
from .config import settings
from .jobs import AnalysisJobStore
from .schemas import AnalysisJobResponse, AnalysisResponse

app = FastAPI()
job_store = AnalysisJobStore(settings.analysis_workers)

ALLOWED_EXTENSIONS = {".wav", ".mp3"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _save_upload(file: UploadFile, extension: str) -> Path:
    bytes_written = 0
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=extension,
            dir=settings.temp_dir,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            while chunk := file.file.read(settings.upload_chunk_bytes):
                bytes_written += len(chunk)
                if bytes_written > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail="Uploaded file exceeds the configured size limit.",
                    )
                temp_file.write(chunk)
        return temp_path
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def _finalize_result(result: dict[str, object], filename: str) -> dict[str, object]:
    if result["duration_seconds"] > settings.max_analysis_seconds:
        raise ValueError("Audio duration exceeds the configured analysis limit.")
    result["filename"] = filename
    result["warnings"] = result["basic_warnings"]
    result["status"] = "ok"
    return result


@app.post("/analyze", response_model=AnalysisResponse)
async def analyze(file: UploadFile = File(...)) -> AnalysisResponse:
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only WAV and MP3 files are supported.")

    temp_path: Path | None = None
    try:
        temp_path = _save_upload(file, extension)

        result = _finalize_result(analyze_audio(temp_path), file.filename or "audio")
        return AnalysisResponse.model_validate(result)
    except AudioDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail="The uploaded file could not be decoded as WAV or MP3 audio.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


@app.post("/analyze/jobs", response_model=AnalysisJobResponse, status_code=202)
async def create_analysis_job(file: UploadFile = File(...)) -> AnalysisJobResponse:
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only WAV and MP3 files are supported.")
    filename = file.filename or "audio"
    try:
        temp_path = _save_upload(file, extension)
        job = job_store.submit(
            temp_path,
            analyze_audio,
            lambda result: _finalize_result(result, filename),
        )
        return AnalysisJobResponse(job_id=job.id, status=job.status, progress=job.progress)
    finally:
        await file.close()


@app.get("/analyze/jobs/{job_id}", response_model=AnalysisJobResponse)
async def get_analysis_job(job_id: str) -> AnalysisJobResponse:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis job was not found.")
    return AnalysisJobResponse(
        job_id=job.id,
        status=job.status,
        progress=job.progress,
        result=job.result,
        error=job.error,
    )
