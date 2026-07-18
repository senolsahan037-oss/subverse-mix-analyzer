from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _positive_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return parsed


def _positive_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive number.") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive number.")
    return parsed


@dataclass
class Settings:
    max_upload_bytes: int = _positive_int("MAX_UPLOAD_BYTES", 100 * 1024 * 1024)
    max_analysis_seconds: int = _positive_int("MAX_ANALYSIS_SECONDS", 30 * 60)
    upload_chunk_bytes: int = _positive_int("UPLOAD_CHUNK_BYTES", 1024 * 1024)
    min_analysis_seconds: float = _positive_float("MIN_ANALYSIS_SECONDS", 0.5)
    analysis_workers: int = _positive_int("ANALYSIS_WORKERS", 2)
    temp_dir: Path | None = None


settings = Settings()
