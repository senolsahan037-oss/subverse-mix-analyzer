from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from subverse.mix_analyzer import analyze_mix


def _write_tone(path: Path, frequency: float, amplitude: float) -> None:
    sample_rate = 48_000
    time = np.arange(sample_rate * 4) / sample_rate
    signal = amplitude * np.sin(2 * np.pi * frequency * time)
    sf.write(path, np.column_stack((signal, signal)), sample_rate, subtype="FLOAT")


def _compare(tmp_path: Path, subject_amp: float, reference_amp: float, reference_hz: float = 440.0):
    subject = tmp_path / "subject.wav"
    reference = tmp_path / "reference.wav"
    _write_tone(subject, 440.0, subject_amp)
    _write_tone(reference, reference_hz, reference_amp)
    return analyze_mix(
        subject,
        subject.name,
        reference_path=reference,
        reference_filename=reference.name,
        reference_stage="mix",
    )


def test_comparison_matrix_same_signal_is_zero(tmp_path: Path) -> None:
    result = _compare(tmp_path, 0.1, 0.1)
    relevant = [band for band in result["comparison"]["spectral_deltas"] if band["relevant_for_findings"]]
    assert relevant
    assert max(abs(band["delta_db"]) for band in relevant) < 0.01
    assert result["findings"] == []


def test_comparison_matrix_gain_only_does_not_create_spectral_finding(tmp_path: Path) -> None:
    result = _compare(tmp_path, 0.05, 0.3)
    relevant = [band for band in result["comparison"]["spectral_deltas"] if band["relevant_for_findings"]]
    assert relevant
    assert max(abs(band["delta_db"]) for band in relevant) < 0.01
    assert result["findings"] == []


def test_comparison_matrix_inactive_tonal_difference_is_not_a_10db_finding(tmp_path: Path) -> None:
    result = _compare(tmp_path, 0.1, 0.1, reference_hz=1000.0)
    assert result["findings"] == []
    assert any(
        band["comparison_status"] == "inactive"
        for band in result["comparison"]["spectral_deltas"]
    )
