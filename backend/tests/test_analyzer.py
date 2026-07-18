from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from backend.app.analyzer import FREQUENCY_BANDS, analyze_audio


def test_analyzer_returns_required_fields(tmp_path: Path) -> None:
    sample_rate = 48000
    duration_seconds = 1.5
    timeline = np.linspace(
        0.0,
        duration_seconds,
        int(sample_rate * duration_seconds),
        endpoint=False,
    )

    left = 0.35 * np.sin(2 * np.pi * 80 * timeline)
    right = 0.3 * np.sin(2 * np.pi * 1200 * timeline + 0.1)
    noise = 0.02 * np.random.default_rng(7).normal(size=timeline.shape[0])
    stereo_audio = np.column_stack([left + noise, right + noise]).astype(np.float32)

    file_path = tmp_path / "synthetic_mix.wav"
    sf.write(file_path, stereo_audio, sample_rate)

    result = analyze_audio(file_path)

    expected_fields = {
        "duration_seconds",
        "sample_rate",
        "channels",
        "peak",
        "peak_dbfs",
        "rms",
        "rms_dbfs",
        "crest_factor_db",
        "approximate_lufs",
        "true_peak",
        "true_peak_db",
        "dynamic_range_db",
        "frequency_bands",
        "frequency_balance",
        "stereo_correlation",
        "stereo_analysis",
        "bpm",
        "bpm_confidence",
        "key",
        "key_confidence",
        "analysis_status",
        "basic_warnings",
    }

    assert expected_fields.issubset(result.keys())
    assert result["sample_rate"] == sample_rate
    assert result["channels"] == 2
    assert result["duration_seconds"] > 1.4
    assert set(result["frequency_bands"]) == set(FREQUENCY_BANDS)
    assert set(result["frequency_balance"]) == set(FREQUENCY_BANDS)
    assert abs(sum(result["frequency_balance"].values()) - 1.0) < 0.01
    assert isinstance(result["stereo_correlation"], float)
    assert isinstance(result["basic_warnings"], list)
    assert result["analysis_status"] == "ok"


def test_musical_analysis_returns_tempo_and_key_with_confidence(tmp_path: Path) -> None:
    sample_rate = 22050
    duration_seconds = 8
    audio = np.zeros(sample_rate * duration_seconds, dtype=np.float32)
    for start in range(0, len(audio), sample_rate // 2):
        audio[start : start + 400] = np.hanning(400)
    file_path = tmp_path / "tempo.wav"
    sf.write(file_path, audio, sample_rate)

    result = analyze_audio(file_path)

    assert result["bpm"] == pytest.approx(120, abs=3)
    assert 0 < result["bpm_confidence"] <= 1
    assert result["key"] is not None
    assert 0 <= result["key_confidence"] <= 1


def test_stereo_measurements_are_channel_aware_and_detect_fold_down_loss(
    tmp_path: Path,
) -> None:
    sample_rate = 48000
    timeline = np.arange(sample_rate, dtype=np.float32) / sample_rate
    left = 0.1 * np.sin(2 * np.pi * 440 * timeline)
    stereo_audio = np.column_stack((left, -left))
    file_path = tmp_path / "out_of_phase.wav"
    sf.write(file_path, stereo_audio, sample_rate)

    result = analyze_audio(file_path)

    assert result["rms_dbfs"] == pytest.approx(-23.01, abs=0.05)
    assert result["stereo_correlation"] == pytest.approx(-1.0, abs=0.001)
    assert result["stereo_analysis"]["mono_compatibility_status"] == "risk"
    # PCM quantization leaves a residual after an otherwise exact cancellation.
    assert result["stereo_analysis"]["mono_fold_down_loss_db"] > 60


def test_true_peak_and_dynamic_range_are_measured(tmp_path: Path) -> None:
    sample_rate = 48000
    timeline = np.arange(sample_rate * 4, dtype=np.float32) / sample_rate
    signal = np.concatenate(
        [
            0.05 * np.sin(2 * np.pi * 997 * timeline[:sample_rate]),
            0.4 * np.sin(2 * np.pi * 997 * timeline[sample_rate:]),
        ]
    )
    file_path = tmp_path / "varying_level.wav"
    sf.write(file_path, signal, sample_rate)

    result = analyze_audio(file_path)

    assert result["true_peak"] >= result["peak"]
    assert result["true_peak_db"] >= result["peak_dbfs"]
    assert result["dynamic_range_db"] > 10


def test_silent_audio_has_explicit_non_failure_status(tmp_path: Path) -> None:
    file_path = tmp_path / "silence.wav"
    sf.write(file_path, np.zeros((48000, 2), dtype=np.float32), 48000)

    result = analyze_audio(file_path)

    assert result["analysis_status"] == "silent"
    assert result["basic_warnings"] == [
        "Audio is silent; mix metrics are not meaningful."
    ]


def test_very_short_audio_has_explicit_non_failure_status(tmp_path: Path) -> None:
    file_path = tmp_path / "short.wav"
    sf.write(file_path, np.full((10, 1), 0.1, dtype=np.float32), 48000)

    result = analyze_audio(file_path)

    assert result["analysis_status"] == "too_short"
    assert result["basic_warnings"] == [
        "Audio is too short for a reliable mix analysis."
    ]
