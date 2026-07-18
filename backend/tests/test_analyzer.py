from __future__ import annotations

from pathlib import Path

import numpy as np
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
        "frequency_bands",
        "frequency_balance",
        "stereo_correlation",
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
