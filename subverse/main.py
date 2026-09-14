from __future__ import annotations

import tempfile
import logging
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .analyzer import AudioDecodeError, analyze_audio
from .access import (
    AuthenticatedUser,
    QuotaReservation,
    authenticated_user,
    client_ip,
    daily_quota,
)
from .cloud_uploads import (
    create_upload_session,
    delete_upload,
    download_owned_upload,
)
from .config import settings
from .genre_profiles import GenreProfileError, GenreProfileStore
from .jobs import AnalysisJobStore, JobCapacityError
from .mix_analyzer import analyze_mix as analyze_mix_files
from .schemas import (
    AnalysisJobResponse,
    AnalysisResponse,
    GenreProfileListResponse,
    MixAnalysisResponse,
)
from pydantic import BaseModel, Field

job_store = AnalysisJobStore(
    settings.analysis_workers,
    ttl_seconds=settings.analysis_job_ttl_seconds,
    max_records=settings.analysis_job_max_records,
)
genre_profile_store = GenreProfileStore(settings.genre_profiles_path)
WEB_DIR = Path(__file__).parent / "web"
ROOT_DIR = Path(__file__).parent.parent
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    job_store.shutdown()


from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Subverse Measurement API",
    version="3.4.0",
    lifespan=lifespan,
)

import os
cors_origins = [
    "https://subverselab.com",
    "https://www.subverselab.com"
]
if os.getenv("ENVIRONMENT") == "development" or os.getenv("NODE_ENV") == "development":
    cors_origins.append("http://localhost:5173")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_EXTENSIONS = {".wav", ".mp3"}

app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")
app.mount("/branding", StaticFiles(directory=ROOT_DIR / "assets"), name="branding")
app.mount("/docs", StaticFiles(directory=ROOT_DIR / "docs"), name="docs")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


async def _release_quota_safely(
    reservation: QuotaReservation | None,
) -> None:
    try:
        await run_in_threadpool(daily_quota.release, reservation)
    except Exception:
        logger.exception("A quota reservation could not be released.")


@app.get("/", include_in_schema=False)
async def analyzer_ui() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/terms", include_in_schema=False)
async def terms_page() -> FileResponse:
    return FileResponse(WEB_DIR / "terms.html")


@app.get("/privacy", include_in_schema=False)
async def privacy_page() -> FileResponse:
    return FileResponse(WEB_DIR / "privacy.html")


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}


from datetime import datetime, timezone

@app.get("/api/manifest")
async def get_manifest(request: Request) -> dict[str, object]:
    base_url = str(request.base_url).rstrip("/")
    if request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip() == "https":
        base_url = base_url.replace("http://", "https://", 1)
    return {
        "source_type": "remote",
        "name": "Subverse Mix Check",
        "slug": "subverse-mix-check",
        "content_type": "ai_tool",
        "version": "3.4.0",
        "guide_version": "1.2.0",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "deployment": {
            "provider": "cloud_run",
            "tool_url": base_url,
            "iframe_compatible": True,
        },
        "access": {"level": "member"},
        "actions": [{"type": "launch", "label": "Analyze a Mix"}],
    }


@app.get("/api/config", include_in_schema=False)
async def public_config() -> dict[str, object]:
    return {
        "auth_required": settings.auth_required,
        "firebase": settings.firebase_web_config,
        "cloud_uploads": bool(settings.upload_bucket),
        "max_upload_bytes": settings.max_upload_bytes,
        "max_analysis_seconds": settings.max_analysis_seconds,
        "daily_free_analyses": 1,
    }


class UploadSessionRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(gt=0)


class CloudAnalysisRequest(BaseModel):
    mix_object: str
    reference_object: str | None = None
    genre: str | None = None
    use_closest_profile: bool = False
    analysis_stage: Literal["mix", "master"] = "mix"
    reference_stage: Literal["mix", "master"] | None = None


@app.post("/api/uploads/session", include_in_schema=False)
async def upload_session(
    payload: UploadSessionRequest,
    request: Request,
    user: AuthenticatedUser = Depends(authenticated_user),
) -> dict[str, str]:
    upload = await run_in_threadpool(
        create_upload_session,
        user,
        payload.filename,
        payload.content_type,
        payload.size_bytes,
        request.headers.get("origin"),
    )
    return {"object_name": upload.object_name, "upload_url": upload.upload_url}


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
    return result


def _upload_extension(file: UploadFile) -> str:
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Only WAV and MP3 files are supported.",
        )
    return extension


@app.post("/analyze", response_model=AnalysisResponse)
async def analyze(
    request: Request,
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(authenticated_user),
) -> AnalysisResponse:
    extension = _upload_extension(file)

    temp_path: Path | None = None
    reservation = await run_in_threadpool(
        daily_quota.reserve,
        user,
        client_ip(request),
    )
    completed = False
    try:
        temp_path = await run_in_threadpool(_save_upload, file, extension)
        result = _finalize_result(
            await run_in_threadpool(
                analyze_audio,
                temp_path,
                settings.max_analysis_seconds,
            ),
            file.filename or "audio",
        )
        response = AnalysisResponse.model_validate(result)
        await run_in_threadpool(daily_quota.complete, reservation)
        completed = True
        return response
    except AudioDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail="The uploaded file could not be decoded as WAV or MP3 audio.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if not completed:
            await _release_quota_safely(reservation)
        await file.close()
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


@app.post("/analyze/jobs", response_model=AnalysisJobResponse, status_code=202)
async def create_analysis_job(
    request: Request,
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(authenticated_user),
) -> AnalysisJobResponse:
    if settings.quota_enabled:
        raise HTTPException(status_code=404, detail="This endpoint is unavailable.")
    extension = _upload_extension(file)
    filename = file.filename or "audio"
    temp_path: Path | None = None
    try:
        temp_path = await run_in_threadpool(_save_upload, file, extension)
        job = job_store.submit(
            temp_path,
            partial(
                analyze_audio,
                max_duration_seconds=settings.max_analysis_seconds,
            ),
            lambda result: _finalize_result(result, filename),
        )
        return AnalysisJobResponse(job_id=job.id, status=job.status, progress=job.progress)
    except JobCapacityError as exc:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=503,
            detail="Analysis job capacity has been reached.",
        ) from exc
    finally:
        await file.close()


@app.get("/analyze/jobs/{job_id}", response_model=AnalysisJobResponse)
async def get_analysis_job(
    job_id: str,
    _: AuthenticatedUser = Depends(authenticated_user),
) -> AnalysisJobResponse:
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


@app.get("/mix/genres", response_model=GenreProfileListResponse)
async def list_mix_genres() -> GenreProfileListResponse:
    try:
        return GenreProfileListResponse(genres=genre_profile_store.list())
    except GenreProfileError as exc:
        raise HTTPException(
            status_code=500,
            detail="Genre profile catalog is unavailable.",
        ) from exc


@app.post("/analyze/track", response_model=MixAnalysisResponse)
@app.post("/analyze/mix", response_model=MixAnalysisResponse)
async def analyze_mix(
    request: Request,
    file: UploadFile = File(...),
    reference: UploadFile | None = File(default=None),
    genre: str | None = Form(default=None),
    use_closest_profile: bool = Form(default=False),
    analysis_stage: Literal["mix", "master"] = Form(default="mix"),
    reference_stage: Literal["mix", "master"] | None = Form(default=None),
    user: AuthenticatedUser = Depends(authenticated_user),
) -> MixAnalysisResponse:
    if reference is not None and reference_stage is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "reference_stage must be declared as mix or master when a "
                "reference file is submitted."
            ),
        )
    if reference is None and reference_stage is not None:
        raise HTTPException(
            status_code=422,
            detail="reference_stage cannot be set without a reference file.",
        )
    mix_extension = _upload_extension(file)
    reference_extension = (
        None if reference is None else _upload_extension(reference)
    )
    normalized_genre = genre.strip().lower() if genre and genre.strip() else None
    try:
        genre_profiles = genre_profile_store.all()
    except GenreProfileError as exc:
        raise HTTPException(
            status_code=500,
            detail="Genre profile catalog is unavailable.",
        ) from exc
    genre_profile = (
        None
        if normalized_genre is None
        else next(
            (
                profile
                for profile in genre_profiles
                if profile["id"] == normalized_genre
            ),
            None,
        )
    )
    if normalized_genre is not None:
        if genre_profile is None:
            raise HTTPException(
                status_code=422,
                detail="The selected genre does not have a measured profile.",
            )

    mix_path: Path | None = None
    reference_path: Path | None = None
    reservation = await run_in_threadpool(
        daily_quota.reserve,
        user,
        client_ip(request),
    )
    completed = False
    try:
        mix_path = await run_in_threadpool(_save_upload, file, mix_extension)
        if reference is not None and reference_extension is not None:
            reference_path = await run_in_threadpool(
                _save_upload,
                reference,
                reference_extension,
            )
        result = await run_in_threadpool(
            analyze_mix_files,
            mix_path=mix_path,
            mix_filename=file.filename or "mix",
            reference_path=reference_path,
            reference_filename=(
                None
                if reference is None
                else reference.filename or "reference"
            ),
            selected_genre=normalized_genre,
            genre_profile=genre_profile,
            genre_profiles=genre_profiles,
            use_closest_profile=use_closest_profile,
            analysis_stage=analysis_stage,
            reference_stage=reference_stage,
            max_duration_seconds=settings.max_analysis_seconds,
        )
        if result["mix"]["analysis"]["duration_seconds"] > settings.max_analysis_seconds:
            raise ValueError("Audio duration exceeds the configured analysis limit.")
        comparison = result.get("comparison")
        if (
            comparison is not None
            and comparison.get("reference_analysis") is not None
            and comparison["reference_analysis"]["duration_seconds"]
            > settings.max_analysis_seconds
        ):
            raise ValueError("Reference duration exceeds the configured analysis limit.")
        response = MixAnalysisResponse.model_validate(result)
        await run_in_threadpool(daily_quota.complete, reservation)
        completed = True
        return response
    except AudioDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail="A submitted file could not be decoded as WAV or MP3 audio.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if not completed:
            await _release_quota_safely(reservation)
        await file.close()
        if reference is not None:
            await reference.close()
        if mix_path is not None:
            mix_path.unlink(missing_ok=True)
        if reference_path is not None:
            reference_path.unlink(missing_ok=True)


@app.post("/api/analyze/cloud", response_model=MixAnalysisResponse)
async def analyze_cloud_upload(
    payload: CloudAnalysisRequest,
    request: Request,
    user: AuthenticatedUser = Depends(authenticated_user),
) -> MixAnalysisResponse:
    if payload.reference_object is not None and payload.reference_stage is None:
        raise HTTPException(
            status_code=422,
            detail="reference_stage is required with a Reference Track.",
        )
    if payload.reference_object is None and payload.reference_stage is not None:
        raise HTTPException(
            status_code=422,
            detail="reference_stage cannot be set without a Reference Track.",
        )
    normalized_genre = (
        payload.genre.strip().lower()
        if payload.genre and payload.genre.strip()
        else None
    )
    try:
        genre_profiles = genre_profile_store.all()
    except GenreProfileError as exc:
        raise HTTPException(
            status_code=500,
            detail="Genre profile catalog is unavailable.",
        ) from exc
    genre_profile = (
        None
        if normalized_genre is None
        else next(
            (
                profile
                for profile in genre_profiles
                if profile["id"] == normalized_genre
            ),
            None,
        )
    )
    if normalized_genre is not None and genre_profile is None:
        raise HTTPException(
            status_code=422,
            detail="The selected genre does not have a measured profile.",
        )

    reservation = await run_in_threadpool(
        daily_quota.reserve,
        user,
        client_ip(request),
    )
    completed = False
    mix_upload = None
    reference_upload = None
    try:
        mix_upload = await run_in_threadpool(
            download_owned_upload,
            user,
            payload.mix_object,
        )
        if payload.reference_object:
            reference_upload = await run_in_threadpool(
                download_owned_upload,
                user,
                payload.reference_object,
            )
        result = await run_in_threadpool(
            analyze_mix_files,
            mix_path=mix_upload.path,
            mix_filename=mix_upload.filename,
            reference_path=(
                None if reference_upload is None else reference_upload.path
            ),
            reference_filename=(
                None if reference_upload is None else reference_upload.filename
            ),
            selected_genre=normalized_genre,
            genre_profile=genre_profile,
            genre_profiles=genre_profiles,
            use_closest_profile=payload.use_closest_profile,
            analysis_stage=payload.analysis_stage,
            reference_stage=payload.reference_stage,
            max_duration_seconds=settings.max_analysis_seconds,
        )
        response = MixAnalysisResponse.model_validate(result)
        await run_in_threadpool(daily_quota.complete, reservation)
        completed = True
        return response
    except AudioDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail="A submitted file could not be decoded as WAV or MP3 audio.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if not completed:
            await _release_quota_safely(reservation)
        if mix_upload is not None:
            mix_upload.path.unlink(missing_ok=True)
        if reference_upload is not None:
            reference_upload.path.unlink(missing_ok=True)
        await run_in_threadpool(delete_upload, payload.mix_object)
        if payload.reference_object:
            await run_in_threadpool(delete_upload, payload.reference_object)
