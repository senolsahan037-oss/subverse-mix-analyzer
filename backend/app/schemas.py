from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class FrequencyBands(BaseModel):
    sub: float
    bass: float
    low_mid: float
    mid: float
    high_mid: float
    high: float


class AnalysisResponse(BaseModel):
    filename: Optional[str] = None
    duration_seconds: float
    sample_rate: int
    channels: int
    peak: Optional[float] = None
    peak_dbfs: float
    rms: Optional[float] = None
    rms_dbfs: float
    crest_factor_db: float
    approximate_lufs: float
    frequency_bands: FrequencyBands
    frequency_balance: FrequencyBands
    stereo_correlation: Optional[float]
    basic_warnings: list[str]
    warnings: Optional[list[str]] = None
    status: Optional[str] = None
