from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from .access import AuthenticatedUser
from .config import settings


SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")


@dataclass(frozen=True)
class CloudUpload:
    object_name: str
    upload_url: str


@dataclass(frozen=True)
class DownloadedUpload:
    path: Path
    filename: str


def _bucket():
    from google.cloud import storage

    if not settings.upload_bucket:
        raise HTTPException(status_code=503, detail="Cloud uploads are not configured.")
    return storage.Client(project=settings.firebase_project_id).bucket(
        settings.upload_bucket
    )


def clean_filename(filename: str) -> str:
    cleaned = SAFE_FILENAME.sub("_", Path(filename).name).strip(" .")
    return (cleaned or "audio")[:180]


def create_upload_session(
    user: AuthenticatedUser,
    filename: str,
    content_type: str,
    size_bytes: int,
    origin: str | None,
) -> CloudUpload:
    safe_filename = clean_filename(filename)
    extension = Path(safe_filename).suffix.lower()
    if extension not in {".wav", ".mp3"}:
        raise HTTPException(status_code=400, detail="Only WAV and MP3 files are supported.")
    if size_bytes <= 0 or size_bytes > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="The file exceeds the upload limit.")
    object_name = f"temporary/{user.uid}/{uuid4().hex}{extension}"
    blob = _bucket().blob(object_name)
    blob.metadata = {
        "owner_uid": user.uid,
        "original_filename": safe_filename,
        "declared_size": str(size_bytes),
    }
    upload_url = blob.create_resumable_upload_session(
        content_type=content_type,
        size=size_bytes,
        origin=origin,
    )
    return CloudUpload(object_name=object_name, upload_url=upload_url)


def download_owned_upload(
    user: AuthenticatedUser,
    object_name: str,
) -> DownloadedUpload:
    expected_prefix = f"temporary/{user.uid}/"
    if not object_name.startswith(expected_prefix) or ".." in object_name:
        raise HTTPException(status_code=403, detail="The uploaded object is not available.")
    blob = _bucket().blob(object_name)
    try:
        blob.reload()
    except Exception as exc:
        from google.api_core.exceptions import NotFound

        if not isinstance(exc, NotFound):
            raise HTTPException(
                status_code=503,
                detail="Temporary storage is currently unavailable.",
            ) from exc
        raise HTTPException(status_code=404, detail="The uploaded object was not found.") from exc
    metadata = blob.metadata or {}
    if metadata.get("owner_uid") != user.uid:
        raise HTTPException(status_code=403, detail="The uploaded object is not available.")
    if blob.size is None or blob.size > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="The uploaded object exceeds the size limit.")
    filename = clean_filename(metadata.get("original_filename", "audio"))
    extension = Path(object_name).suffix.lower()
    temp_file = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=extension,
        dir=settings.temp_dir,
    )
    temp_file.close()
    path = Path(temp_file.name)
    try:
        blob.download_to_filename(str(path))
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return DownloadedUpload(path=path, filename=filename)


def delete_upload(object_name: str) -> None:
    if not object_name.startswith("temporary/") or ".." in object_name:
        return
    try:
        _bucket().blob(object_name).delete()
    except Exception:
        # The bucket lifecycle rule is the final cleanup backstop.
        return
