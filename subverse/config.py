from __future__ import annotations

import os
import json
from subverse_mix import DEFAULT_PROFILES_PATH as _DEFAULT_PROFILES_PATH
from dataclasses import dataclass, field
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


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean.")


def _json_object(name: str) -> dict[str, str]:
    value = os.getenv(name)
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must contain a JSON object.") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} must contain a JSON object.")
    return {str(key): str(item) for key, item in parsed.items()}


@dataclass
class Settings:
    max_upload_bytes: int = _positive_int("MAX_UPLOAD_BYTES", 100 * 1024 * 1024)
    max_analysis_seconds: int = _positive_int("MAX_ANALYSIS_SECONDS", 6 * 60)
    max_sample_rate: int = _positive_int("MAX_SAMPLE_RATE", 192_000)
    max_audio_channels: int = _positive_int("MAX_AUDIO_CHANNELS", 8)
    upload_chunk_bytes: int = _positive_int("UPLOAD_CHUNK_BYTES", 1024 * 1024)
    min_analysis_seconds: float = _positive_float("MIN_ANALYSIS_SECONDS", 0.5)
    analysis_workers: int = _positive_int("ANALYSIS_WORKERS", 2)
    analysis_job_ttl_seconds: int = _positive_int(
        "ANALYSIS_JOB_TTL_SECONDS",
        60 * 60,
    )
    analysis_job_max_records: int = _positive_int(
        "ANALYSIS_JOB_MAX_RECORDS",
        1000,
    )
    temp_dir: Path | None = None
    # The profile catalogue ships with the shared engine (subverse_mix); an
    # override still wins so a deployment can carry its own catalogue.
    genre_profiles_path: Path = Path(
        os.getenv("GENRE_PROFILES_PATH", str(_DEFAULT_PROFILES_PATH))
    )
    auth_required: bool = _boolean("AUTH_REQUIRED", False)
    quota_enabled: bool = _boolean("QUOTA_ENABLED", False)
    firebase_project_id: str = os.getenv("FIREBASE_PROJECT_ID", "")
    firebase_web_config: dict[str, str] = field(init=False, default_factory=dict)
    upload_bucket: str = os.getenv("UPLOAD_BUCKET", "")
    quota_timezone: str = os.getenv("QUOTA_TIMEZONE", "UTC")
    quota_reservation_minutes: int = _positive_int(
        "QUOTA_RESERVATION_MINUTES",
        20,
    )
    ip_hash_secret: str = os.getenv("IP_HASH_SECRET", "")
    admin_emails: frozenset[str] = field(init=False, default_factory=frozenset)

    def __post_init__(self) -> None:
        self.firebase_web_config = _json_object("FIREBASE_WEB_CONFIG")
        self.admin_emails = frozenset(
            email.strip().casefold()
            for email in os.getenv("ADMIN_EMAILS", "").split(",")
            if email.strip()
        )
        if self.auth_required and not self.firebase_project_id:
            raise ValueError("FIREBASE_PROJECT_ID is required when authentication is enabled.")
        if self.quota_enabled and not self.auth_required:
            raise ValueError("QUOTA_ENABLED requires AUTH_REQUIRED.")
        if self.quota_enabled and not self.ip_hash_secret:
            raise ValueError("IP_HASH_SECRET is required when quotas are enabled.")


settings = Settings()
