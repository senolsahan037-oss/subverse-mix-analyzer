from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class FrequencyBands(BaseModel):
    sub: float
    bass: float
    low_mid: float
    mid: float
    high_mid: float
    high: float


class StereoAnalysis(BaseModel):
    mid_rms: float
    side_rms: Optional[float]
    side_ratio: Optional[float]
    mono_fold_down_loss_db: float
    mono_compatibility_score: float
    mono_compatibility_status: Literal["not_applicable", "safe", "watch", "risk"]


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
    true_peak: float
    true_peak_db: float
    dynamic_range_db: float
    frequency_bands: FrequencyBands
    frequency_balance: FrequencyBands
    stereo_correlation: Optional[float]
    stereo_analysis: StereoAnalysis
    bpm: Optional[float]
    bpm_confidence: float
    key: Optional[str]
    key_confidence: float
    analysis_status: Literal["ok", "silent", "too_short"]
    basic_warnings: list[str]
    warnings: Optional[list[str]] = None
    status: Optional[str] = None


class AnalysisJobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    progress: int
    result: Optional[AnalysisResponse] = None
    error: Optional[str] = None
