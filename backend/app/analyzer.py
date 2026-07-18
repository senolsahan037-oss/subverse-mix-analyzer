from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from scipy.signal import resample_poly

from .config import settings

FREQUENCY_BANDS: dict[str, tuple[float, float]] = {
    "sub": (20.0, 60.0),
    "bass": (60.0, 250.0),
    "low_mid": (250.0, 500.0),
    "mid": (500.0, 2000.0),
    "high_mid": (2000.0, 6000.0),
    "high": (6000.0, 16000.0),
}

KEY_NAMES = ("C", "C♯/D♭", "D", "D♯/E♭", "E", "F", "F♯/G♭", "G", "G♯/A♭", "A", "A♯/B♭", "B")
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.6, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


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


def _rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0


def _approximate_lufs(audio: np.ndarray, sample_rate: int) -> float:
    if len(audio) < max(sample_rate // 2, 1):
        return _dbfs(_rms(audio))

    meter = pyln.Meter(sample_rate)
    # pyloudnorm implements BS.1770 channel weighting for up to five channels.
    measured_audio = audio[:, :5]
    loudness = meter.integrated_loudness(measured_audio)
    if not np.isfinite(loudness):
        return _dbfs(_rms(audio))
    return float(loudness)


def _true_peak(audio: np.ndarray) -> float:
    if not audio.size:
        return 0.0
    oversampled = resample_poly(audio, up=4, down=1, axis=0)
    sample_peak = float(np.max(np.abs(audio)))
    oversampled_peak = float(np.max(np.abs(oversampled))) if oversampled.size else 0.0
    return max(sample_peak, oversampled_peak)


def _dynamic_range(audio: np.ndarray, sample_rate: int) -> float:
    """Return a percentile spread of one-second channel-aware RMS windows."""
    if len(audio) < sample_rate or sample_rate <= 0:
        return 0.0

    window = sample_rate
    levels = [
        _dbfs(_rms(audio[start : start + window]))
        for start in range(0, len(audio) - window + 1, window)
    ]
    audible_levels = [level for level in levels if level > -70.0]
    if len(audible_levels) < 2:
        return 0.0
    return float(np.percentile(audible_levels, 95) - np.percentile(audible_levels, 10))


def _tempo_and_key(audio: np.ndarray, sample_rate: int) -> dict[str, float | str | None]:
    """Estimate musical tempo and key; return unavailable values for short/silent audio."""
    if sample_rate <= 0 or len(audio) < sample_rate * 3 or _rms(audio) <= 1e-12:
        return {"bpm": None, "bpm_confidence": 0.0, "key": None, "key_confidence": 0.0}

    mono = audio.mean(axis=1)
    try:
        frame_size = 2048
        hop_size = 512
        frame_count = 1 + max(0, (len(mono) - frame_size) // hop_size)
        frames = np.stack(
            [mono[index * hop_size : index * hop_size + frame_size] for index in range(frame_count)]
        )
        spectrum = np.abs(np.fft.rfft(frames * np.hanning(frame_size), axis=1))
        log_spectrum = np.log1p(spectrum)
        onset_envelope = np.sum(np.maximum(np.diff(log_spectrum, axis=0), 0.0), axis=1)
        autocorrelation = np.correlate(onset_envelope, onset_envelope, mode="full")[len(onset_envelope) - 1 :]
        min_lag = max(1, round((60.0 * sample_rate) / (200.0 * hop_size)))
        max_lag = min(len(autocorrelation) - 1, round((60.0 * sample_rate) / (60.0 * hop_size)))
        if max_lag <= min_lag or np.std(onset_envelope) < max(np.mean(onset_envelope) * 0.1, 1e-6):
            bpm, bpm_confidence = None, 0.0
        else:
            tempo_region = autocorrelation[min_lag : max_lag + 1]
            best_lag = min_lag + int(np.argmax(tempo_region))
            bpm = 60.0 * sample_rate / (hop_size * best_lag)
            while bpm < 80.0:
                bpm *= 2.0
            while bpm > 180.0:
                bpm /= 2.0
            bpm_confidence = float(np.clip(autocorrelation[best_lag] / max(autocorrelation[0], 1e-12), 0.0, 1.0))

        frequencies = np.fft.rfftfreq(frame_size, d=1.0 / sample_rate)
        valid = (frequencies >= 20.0) & (frequencies <= 5000.0)
        midi = np.rint(69.0 + (12.0 * np.log2(frequencies[valid] / 440.0))).astype(int)
        pitch_classes = np.mod(midi, 12)
        pitch_class_profile = np.bincount(
            pitch_classes,
            weights=np.mean(spectrum[:, valid], axis=0),
            minlength=12,
        ).astype(float)
        normalized_profile = pitch_class_profile / max(np.linalg.norm(pitch_class_profile), 1e-12)
        candidates: list[tuple[float, str]] = []
        for tonic, name in enumerate(KEY_NAMES):
            for mode, template in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
                normalized_template = np.roll(template, tonic) / np.linalg.norm(template)
                candidates.append((float(np.dot(normalized_profile, normalized_template)), f"{name} {mode}"))
        candidates.sort(reverse=True)
        best_score, key = candidates[0]
        next_score = candidates[1][0]
        key_confidence = float(np.clip((best_score - next_score) / max(1.0 - next_score, 1e-12), 0.0, 1.0))
        return {
            "bpm": round(bpm, 2) if bpm is not None and np.isfinite(bpm) else None,
            "bpm_confidence": round(bpm_confidence, 3),
            "key": key,
            "key_confidence": round(key_confidence, 3),
        }
    except Exception:
        return {"bpm": None, "bpm_confidence": 0.0, "key": None, "key_confidence": 0.0}


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


def _stereo_analysis(audio: np.ndarray) -> dict[str, float | str | None]:
    if audio.shape[1] < 2:
        return {
            "mid_rms": round(_rms(audio), 4),
            "side_rms": None,
            "side_ratio": None,
            "mono_fold_down_loss_db": 0.0,
            "mono_compatibility_score": 100.0,
            "mono_compatibility_status": "not_applicable",
        }

    left, right = audio[:, 0], audio[:, 1]
    mid = (left + right) / 2.0
    side = (left - right) / 2.0
    mid_rms = _rms(mid)
    side_rms = _rms(side)
    source_rms = _rms(np.column_stack((left, right)))
    fold_down_loss_db = max(0.0, _dbfs(source_rms) - _dbfs(mid_rms))
    side_ratio = side_rms / max(mid_rms + side_rms, 1e-12)
    score = float(np.clip(100.0 - (fold_down_loss_db * 25.0), 0.0, 100.0))
    status = "safe" if fold_down_loss_db < 1.0 else "watch" if fold_down_loss_db < 3.0 else "risk"
    return {
        "mid_rms": round(mid_rms, 4),
        "side_rms": round(side_rms, 4),
        "side_ratio": round(float(side_ratio), 4),
        "mono_fold_down_loss_db": round(fold_down_loss_db, 3),
        "mono_compatibility_score": round(score, 1),
        "mono_compatibility_status": status,
    }


def _warnings(
    peak_dbfs: float,
    crest_factor_db: float,
    approximate_lufs: float,
    true_peak_db: float,
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
    if true_peak_db > -1.0:
        warnings.append("True peak is close to 0 dBTP and may clip after encoding.")
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
    duration_seconds = float(len(audio) / sample_rate) if sample_rate else 0.0
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    rms = _rms(audio)
    peak_dbfs = _dbfs(peak)
    rms_dbfs = _dbfs(rms)
    crest_factor_db = float(peak_dbfs - rms_dbfs)
    approximate_lufs = _approximate_lufs(audio, sample_rate)
    true_peak = _true_peak(audio)
    true_peak_db = _dbfs(true_peak)
    dynamic_range_db = _dynamic_range(audio, sample_rate)
    frequency_balance = _frequency_balance(audio, sample_rate)
    stereo_correlation = _stereo_correlation(audio)
    stereo_analysis = _stereo_analysis(audio)
    musical_analysis = _tempo_and_key(audio, sample_rate)
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
        "true_peak": round(true_peak, 4),
        "true_peak_db": round(true_peak_db, 3),
        "dynamic_range_db": round(dynamic_range_db, 3),
        "frequency_bands": {
            name: round(level, 4) for name, level in frequency_balance.items()
        },
        "frequency_balance": {
            name: round(level, 4) for name, level in frequency_balance.items()
        },
        "stereo_correlation": (
            None if stereo_correlation is None else round(stereo_correlation, 3)
        ),
        "stereo_analysis": stereo_analysis,
        **musical_analysis,
        "analysis_status": analysis_status,
        "basic_warnings": _warnings(
            peak_dbfs=peak_dbfs,
            crest_factor_db=crest_factor_db,
            approximate_lufs=approximate_lufs,
            true_peak_db=true_peak_db,
            stereo_correlation=stereo_correlation,
            frequency_balance=frequency_balance,
            analysis_status=analysis_status,
        ),
    }
