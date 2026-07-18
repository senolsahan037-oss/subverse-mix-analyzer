from __future__ import annotations

import asyncio
import io
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

from backend.app import main
from backend.app.schemas import AnalysisResponse


def _wav_bytes(audio: np.ndarray, sample_rate: int = 48000) -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, audio, sample_rate, format="WAV")
    return buffer.getvalue()


async def _post_file(filename: str, payload: bytes) -> httpx.Response:
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            "/analyze",
            files={"file": (filename, payload, "audio/wav")},
        )


def test_analyze_response_matches_declared_schema_and_cleans_temp_file(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(main.settings, "temp_dir", tmp_path)
    payload = _wav_bytes(np.full((48000, 1), 0.1, dtype=np.float32))

    response = asyncio.run(_post_file("valid.wav", payload))

    assert response.status_code == 200
    result = AnalysisResponse.model_validate(response.json())
    assert result.filename == "valid.wav"
    assert result.status == "ok"
    assert result.analysis_status == "ok"
    assert list(tmp_path.iterdir()) == []


def test_decode_error_is_422_without_internal_details_and_cleans_temp_file(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(main.settings, "temp_dir", tmp_path)

    response = asyncio.run(_post_file("broken.wav", b"not audio data"))

    assert response.status_code == 422
    assert response.json() == {
        "detail": "The uploaded file could not be decoded as WAV or MP3 audio."
    }
    assert list(tmp_path.iterdir()) == []


def test_upload_limit_is_enforced_and_cleans_partial_temp_file(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(main.settings, "temp_dir", tmp_path)
    monkeypatch.setattr(main.settings, "max_upload_bytes", 8)

    response = asyncio.run(_post_file("large.wav", b"012345678"))

    assert response.status_code == 413
    assert response.json() == {
        "detail": "Uploaded file exceeds the configured size limit."
    }
    assert list(tmp_path.iterdir()) == []
