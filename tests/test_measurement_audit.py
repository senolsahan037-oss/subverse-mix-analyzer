from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from subverse.analyzer import analyze_audio


def _write(path: Path, audio: np.ndarray, sample_rate: int = 48_000) -> None:
    sf.write(path, audio, sample_rate, subtype="FLOAT")


def _ffmpeg_integrated_lufs(path: Path) -> float:
    process = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-filter_complex",
            "ebur128",
            "-f",
            "null",
            "-",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stderr
    summary = process.stderr.rsplit("Summary:", maxsplit=1)[-1]
    integrated = re.search(
        r"Integrated loudness:\s+I:\s+(-?\d+\.\d) LUFS",
        summary,
    )
    assert integrated, summary
    return float(integrated.group(1))


def test_direct_level_math_matches_known_sine(tmp_path: Path) -> None:
    sample_rate = 48_000
    time = np.arange(sample_rate * 10) / sample_rate
    signal = 0.1 * np.sin(2 * np.pi * 997 * time)
    path = tmp_path / "sine.wav"
    _write(path, signal)

    result = analyze_audio(path)

    assert result["sample_peak_dbfs"] == pytest.approx(-20.0, abs=0.002)
    assert result["rms_dbfs"] == pytest.approx(-23.0103, abs=0.002)
    assert result["crest_factor_db"] == pytest.approx(3.0103, abs=0.003)


def test_integrated_loudness_agrees_with_ffmpeg_ebur128(tmp_path: Path) -> None:
    sample_rate = 48_000
    time = np.arange(sample_rate * 12) / sample_rate
    envelope = np.where(time < 4, 0.025, np.where(time < 8, 0.1, 0.35))
    left = envelope * np.sin(2 * np.pi * 997 * time)
    right = 0.9 * envelope * np.sin(2 * np.pi * 997 * time + 0.2)
    path = tmp_path / "level_steps.wav"
    _write(path, np.column_stack((left, right)))

    result = analyze_audio(path)

    assert result["integrated_lufs"] == pytest.approx(
        _ffmpeg_integrated_lufs(path),
        abs=0.15,
    )
