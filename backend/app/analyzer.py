from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np
import pyloudnorm as pyln
import soundfile as sf

from .config import settings

FREQUENCY_BANDS: dict[str, tuple[float, float]] = {
    "sub": (20.0, 60.0),
    "bass": (60.0, 250.0),
    "low_mid": (250.0, 500.0),
    "mid": (500.0, 2000.0),
    "high_mid": (2000.0, 6000.0),
    "high": (6000.0, 16000.0),
}


class AudioDecodeError(Exception):
    """Raised when a supported upload cannot be decoded as audio."""


def _load_audio(file_path: str | Path) -> tuple[np.ndarray, int]:
    path = str(file_path)
    try:
        audio, sample_rate = sf.read(path, always_2d=True, dtype="float32")
    except (RuntimeError, ValueError, OSError):
        try:
            audio, sample_rate = librosa.load(path, sr=None, mono=False)
            if audio.ndim == 1:
                audio = audio[np.newaxis, :]
            audio = audio.T.astype(np.float32)
        except Exception as exc:
            raise AudioDecodeError("The uploaded file could not be decoded as audio.") from exc

    if audio.ndim == 1:
        audio = audio[:, np.newaxis]

    return np.asarray(audio, dtype=np.float32), int(sample_rate)


def _dbfs(value: float, floor: float = 1e-12) -> float:
    return float(20.0 * np.log10(max(value, floor)))


def _approximate_lufs(audio: np.ndarray, sample_rate: int) -> float:
    mono = audio.mean(axis=1)
    if len(mono) < max(sample_rate // 2, 1):
        return _dbfs(float(np.sqrt(np.mean(np.square(mono)))))

    meter = pyln.Meter(sample_rate)
    loudness = meter.integrated_loudness(mono)
    if not np.isfinite(loudness):
        return _dbfs(float(np.sqrt(np.mean(np.square(mono)))))
    return float(loudness)


def _frequency_balance(audio: np.ndarray, sample_rate: int) -> dict[str, float]:
    mono = audio.mean(axis=1)
    if len(mono) < 8:
        return {name: 0.0 for name in FREQUENCY_BANDS}

    window = np.hanning(len(mono))
    spectrum = np.fft.rfft(mono * window)
    frequencies = np.fft.rfftfreq(len(mono), d=1.0 / sample_rate)
    magnitudes = np.abs(spectrum) ** 2

    band_energy: dict[str, float] = {}
    for name, (low, high) in FREQUENCY_BANDS.items():
        mask = (frequencies >= low) & (frequencies < high)
        if not np.any(mask):
            band_energy[name] = 0.0
            continue
        band_slice = magnitudes[mask]
        band_energy[name] = float(np.mean(band_slice))

    total_energy = sum(band_energy.values())
    if total_energy <= 1e-12:
        return {name: 0.0 for name in FREQUENCY_BANDS}

    return {
        name: float(energy / total_energy) for name, energy in band_energy.items()
    }


def _stereo_correlation(audio: np.ndarray) -> float | None:
    if audio.shape[1] < 2:
        return None

    left = audio[:, 0]
    right = audio[:, 1]
    if np.std(left) < 1e-12 or np.std(right) < 1e-12:
        return 0.0

    correlation = np.corrcoef(left, right)[0, 1]
    return float(np.clip(correlation, -1.0, 1.0))


def _warnings(
    peak_dbfs: float,
    crest_factor_db: float,
    approximate_lufs: float,
    stereo_correlation: float | None,
    frequency_balance: dict[str, float],
    analysis_status: str,
) -> list[str]:
    warnings: list[str] = []

    if analysis_status == "silent":
        return ["Audio is silent; mix metrics are not meaningful."]
    if analysis_status == "too_short":
        return ["Audio is too short for a reliable mix analysis."]

    if peak_dbfs > -1.0:
        warnings.append("Peak level is close to 0 dBFS and may clip after conversion.")
    if approximate_lufs < -18.0:
        warnings.append("Integrated loudness is low for a modern mastered track.")
    if approximate_lufs > -8.0:
        warnings.append("Integrated loudness is very hot and may be over-limited.")
    if crest_factor_db < 6.0:
        warnings.append("Crest factor is low, suggesting aggressive dynamics control.")
    if stereo_correlation is not None and stereo_correlation < 0.0:
        warnings.append("Negative stereo correlation may indicate phase issues.")
    if frequency_balance["low_mid"] > 0.28:
        warnings.append("too much low_mid")
    if frequency_balance["sub"] < 0.03:
        warnings.append("weak sub")
    if frequency_balance["high"] > 0.34:
        warnings.append("harsh highs")
    if frequency_balance["sub"] + frequency_balance["bass"] < 0.18:
        warnings.append("thin mix")
    if frequency_balance["high_mid"] + frequency_balance["high"] < 0.16:
        warnings.append("dark mix")

    return warnings


def analyze_audio(file_path: str | Path) -> dict[str, object]:
    audio, sample_rate = _load_audio(file_path)
    channels = int(audio.shape[1])
    mono = audio.mean(axis=1)

    duration_seconds = float(len(audio) / sample_rate) if sample_rate else 0.0
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
    peak_dbfs = _dbfs(peak)
    rms_dbfs = _dbfs(rms)
    crest_factor_db = float(peak_dbfs - rms_dbfs)
    approximate_lufs = _approximate_lufs(audio, sample_rate)
    frequency_balance = _frequency_balance(audio, sample_rate)
    stereo_correlation = _stereo_correlation(audio)
    if audio.size == 0 or peak <= 1e-12:
        analysis_status = "silent"
    elif duration_seconds < settings.min_analysis_seconds:
        analysis_status = "too_short"
    else:
        analysis_status = "ok"

    return {
        "duration_seconds": round(duration_seconds, 3),
        "sample_rate": sample_rate,
        "peak": round(peak, 4),
        "channels": channels,
        "peak_dbfs": round(peak_dbfs, 3),
        "rms": round(rms, 4),
        "rms_dbfs": round(rms_dbfs, 3),
        "crest_factor_db": round(crest_factor_db, 3),
        "approximate_lufs": round(approximate_lufs, 3),
        "frequency_bands": {
            name: round(level, 4) for name, level in frequency_balance.items()
        },
        "frequency_balance": {
            name: round(level, 4) for name, level in frequency_balance.items()
        },
        "stereo_correlation": (
            None if stereo_correlation is None else round(stereo_correlation, 3)
        ),
        "analysis_status": analysis_status,
        "basic_warnings": _warnings(
            peak_dbfs=peak_dbfs,
            crest_factor_db=crest_factor_db,
            approximate_lufs=approximate_lufs,
            stereo_correlation=stereo_correlation,
            frequency_balance=frequency_balance,
            analysis_status=analysis_status,
        ),
    }
