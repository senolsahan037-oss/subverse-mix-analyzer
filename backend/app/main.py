from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .analyzer import AudioDecodeError, analyze_audio
from .config import settings
from .schemas import AnalysisResponse

app = FastAPI()

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


@app.post("/analyze", response_model=AnalysisResponse)
async def analyze(file: UploadFile = File(...)) -> AnalysisResponse:
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only WAV and MP3 files are supported.")

    temp_path: Path | None = None
    try:
        temp_path = _save_upload(file, extension)

        result = analyze_audio(temp_path)
        if result["duration_seconds"] > settings.max_analysis_seconds:
            raise HTTPException(
                status_code=422,
                detail="Audio duration exceeds the configured analysis limit.",
            )
        result["filename"] = file.filename
        result["warnings"] = result["basic_warnings"]
        result["status"] = "ok"
        return AnalysisResponse.model_validate(result)
    except AudioDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail="The uploaded file could not be decoded as WAV or MP3 audio.",
        ) from exc
    finally:
        await file.close()
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
