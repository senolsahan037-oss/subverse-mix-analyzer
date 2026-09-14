from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

from subverse import main
from subverse_mix.settings import settings as engine_settings
from subverse.genre_profiles import GenreProfileStore, build_genre_profile
from subverse.schemas import AnalysisResponse, MixAnalysisResponse


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


def test_root_serves_the_mix_check_ui() -> None:
    async def get_ui() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return (
                await client.get("/"),
                await client.get("/assets/styles.css"),
                await client.get("/assets/app.js"),
            )

    page, styles, script = asyncio.run(get_ui())

    assert page.status_code == 200
    assert page.headers["x-content-type-options"] == "nosniff"
    assert page.headers["cross-origin-opener-policy"] == "same-origin-allow-popups"
    assert 'html lang="en"' in page.text
    assert 'class="tool-only-shell"' in page.text
    assert "See the signal." not in page.text
    # The only brand wordmark on the tool shell is the website sign-in hand-off.
    assert page.text.count("SUBVERSELAB") == 1
    assert "SIGN IN ON SUBVERSELAB" in page.text
    assert "Terms" not in page.text
    assert "Privacy" not in page.text
    assert "Maximum duration 6 minutes" in page.text
    assert "does not align song sections automatically" in page.text
    assert "Explore This Analysis" in page.text
    assert 'id="guide-questions"' in page.text
    assert 'name="use_closest_profile"' in page.text
    assert "Use closest measured profile" in page.text
    assert "What small experiment can I try?" in script.text
    assert "What can this analysis not tell me?" in script.text
    assert "textarea" not in page.text
    assert styles.status_code == 200
    assert "--purple: #8b4dff" in styles.text
    assert script.status_code == 200
    assert 'authorizedFetch("/analyze/track"' in script.text
    assert "Continue with Google" not in page.text
    assert "Download JSON" in page.text
    assert 'id="analysis-workspace"' in page.text


def test_public_operational_pages_are_available() -> None:
    async def get_pages() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return [
                await client.get("/health"),
                await client.get("/api/config"),
                await client.get("/terms"),
                await client.get("/privacy"),
            ]

    health, config, terms, privacy = asyncio.run(get_pages())
    assert health.json() == {"status": "ok"}
    assert config.status_code == 200
    assert config.json()["max_analysis_seconds"] == 360
    assert "Terms of Use" in terms.text
    assert "Privacy Notice" in privacy.text


async def _post_job_and_wait(filename: str, payload: bytes) -> httpx.Response:
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/analyze/jobs",
            files={"file": (filename, payload, "audio/wav")},
        )
        assert created.status_code == 202
        job_id = created.json()["job_id"]
        for _ in range(100):
            response = await client.get(f"/analyze/jobs/{job_id}")
            if response.json()["status"] in {"completed", "failed"}:
                return response
            await asyncio.sleep(0.01)
    raise AssertionError("Analysis job did not finish in time")


async def _post_mix(
    payload: bytes,
    reference_payload: bytes | None = None,
    genre: str | None = None,
    use_closest_profile: bool = False,
    analysis_stage: str = "mix",
    reference_stage: str | None = None,
) -> httpx.Response:
    files = {"file": ("mix.wav", payload, "audio/wav")}
    if reference_payload is not None:
        files["reference"] = (
            "reference.wav",
            reference_payload,
            "audio/wav",
        )
    data = {"analysis_stage": analysis_stage}
    if genre is not None:
        data["genre"] = genre
    if use_closest_profile:
        data["use_closest_profile"] = "true"
    if reference_stage is not None:
        data["reference_stage"] = reference_stage
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/analyze/mix", files=files, data=data)


def test_analyze_response_matches_declared_schema_and_cleans_temp_file(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(main.settings, "temp_dir", tmp_path)
    payload = _wav_bytes(np.full((48000, 1), 0.1, dtype=np.float32))

    response = asyncio.run(_post_file("valid.wav", payload))

    assert response.status_code == 200
    result = AnalysisResponse.model_validate(response.json())
    assert result.filename == "valid.wav"
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


def test_sample_rate_resource_limit_is_enforced(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(main.settings, "temp_dir", tmp_path)
    monkeypatch.setattr(main.settings, "max_sample_rate", 44_100)
    # The decode limit is enforced by the shared engine's own settings.
    monkeypatch.setattr(engine_settings, "max_sample_rate", 44_100)
    payload = _wav_bytes(np.zeros((48_000, 1), dtype=np.float32), sample_rate=48_000)

    response = asyncio.run(_post_file("high-rate.wav", payload))

    assert response.status_code == 422
    assert "sample rate exceeds" in response.json()["detail"]
    assert list(tmp_path.iterdir()) == []


def test_analysis_requires_sign_in_when_production_auth_is_enabled(
    monkeypatch,
) -> None:
    monkeypatch.setattr(main.settings, "auth_required", True)
    payload = _wav_bytes(np.zeros((48_000, 1), dtype=np.float32))

    response = asyncio.run(_post_file("anonymous.wav", payload))

    assert response.status_code == 401
    assert response.json() == {"detail": "Sign in with Google to continue."}


def test_analysis_job_returns_completed_result_and_cleans_temp_file(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(main.settings, "temp_dir", tmp_path)
    payload = _wav_bytes(np.full((48000, 1), 0.1, dtype=np.float32))

    response = asyncio.run(_post_job_and_wait("queued.wav", payload))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["progress"] == 100
    assert AnalysisResponse.model_validate(body["result"]).filename == "queued.wav"
    assert list(tmp_path.iterdir()) == []


def test_mix_endpoint_is_descriptive_when_no_genre_is_selected(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(main.settings, "temp_dir", tmp_path)
    time = np.arange(48_000 * 2) / 48_000
    payload = _wav_bytes(0.1 * np.sin(2 * np.pi * 100 * time))

    response = asyncio.run(_post_mix(payload))

    assert response.status_code == 200
    result = MixAnalysisResponse.model_validate(response.json())
    assert result.mode == "general"
    assert result.selected_genre is None
    assert result.recommendation_basis is None
    assert result.genre_affinity
    assert result.comparison is None
    assert result.findings == []
    assert result.recommendations_enabled is False
    assert "direct measurements" in result.summary
    assert result.mix.waveform.waveform_contract_version == (
        "2026-07-30.waveform.1"
    )
    assert result.mix.waveform.normalized is False
    assert result.mix.waveform.bin_count == 1200
    assert list(tmp_path.iterdir()) == []


def test_analysis_duration_limit_is_enforced_and_cleans_temp_file(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(main.settings, "temp_dir", tmp_path)
    monkeypatch.setattr(main.settings, "max_analysis_seconds", 1)
    payload = _wav_bytes(np.zeros((96_000, 1), dtype=np.float32))

    response = asyncio.run(_post_file("too-long.wav", payload))

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Audio duration exceeds the configured 1 second limit."
    }
    assert list(tmp_path.iterdir()) == []


def _tone_profile_store(tmp_path: Path, profiles: dict[str, float]) -> GenreProfileStore:
    """Build a catalog of synthetic profiles, one per (id -> centre frequency)."""
    time = np.arange(48_000 * 2) / 48_000
    store = GenreProfileStore(tmp_path / "tone-genres.json")
    for profile_id, centre in profiles.items():
        source_paths = []
        for index, ratio in enumerate((0.9, 1.0, 1.1)):
            path = tmp_path / f"{profile_id}-{index}.wav"
            sf.write(path, 0.1 * np.sin(2 * np.pi * centre * ratio * time), 48_000)
            source_paths.append(path)
        store.upsert(build_genre_profile(profile_id, profile_id.title(), source_paths))
    return store


def test_mix_endpoint_can_use_the_closest_profile_for_visible_guidance(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(main.settings, "temp_dir", tmp_path)
    monkeypatch.setattr(
        main,
        "genre_profile_store",
        _tone_profile_store(tmp_path, {"low": 100.0, "high": 1000.0}),
    )
    time = np.arange(48_000 * 2) / 48_000
    payload = _wav_bytes(0.1 * np.sin(2 * np.pi * 100 * time))

    response = asyncio.run(_post_mix(payload, use_closest_profile=True))

    assert response.status_code == 200
    result = MixAnalysisResponse.model_validate(response.json())
    assert result.closest_profile_status == "clear"
    assert result.genre_affinity[0].profile_id == "low"
    assert result.genre_affinity[0].distance_unit == "dB"
    assert result.genre_affinity[0].clear is True
    assert result.genre_affinity[0].separation_db >= 1.0
    assert result.mode == "affinity"
    assert result.selected_genre is None
    assert result.recommendation_basis == "closest_profile"
    assert result.comparison is not None
    assert result.comparison.target_id == "low"
    assert result.comparison_policy == "mix_to_genre"
    assert "technically nearest measured profile" in result.summary
    assert list(tmp_path.iterdir()) == [] or all(
        entry.suffix in {".wav", ".json"} for entry in tmp_path.iterdir()
    )


def test_mix_endpoint_refuses_a_nearest_profile_that_is_not_clearly_nearest(
    tmp_path: Path, monkeypatch
) -> None:
    """Two identical profiles tie: the ranking is shown, no target is used."""
    monkeypatch.setattr(main.settings, "temp_dir", tmp_path)
    monkeypatch.setattr(
        main,
        "genre_profile_store",
        _tone_profile_store(tmp_path, {"twina": 100.0, "twinb": 100.0}),
    )
    time = np.arange(48_000 * 2) / 48_000
    payload = _wav_bytes(0.1 * np.sin(2 * np.pi * 100 * time))

    response = asyncio.run(_post_mix(payload, use_closest_profile=True))

    assert response.status_code == 200
    result = MixAnalysisResponse.model_validate(response.json())
    assert len(result.genre_affinity) == 2
    assert result.closest_profile_status == "ambiguous"
    assert result.genre_affinity[0].clear is False
    assert result.genre_affinity[0].separation_db < 1.0
    assert result.mode == "general"
    assert result.comparison is None
    assert result.recommendation_basis is None
    assert result.findings == []
    assert any("clearly nearest" in item for item in result.limitations)


def test_mix_endpoint_reference_takes_priority_and_cleans_both_files(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(main.settings, "temp_dir", tmp_path)
    time = np.arange(48_000 * 2) / 48_000
    mix_payload = _wav_bytes(0.1 * np.sin(2 * np.pi * 100 * time))
    reference_payload = _wav_bytes(0.1 * np.sin(2 * np.pi * 1000 * time))

    response = asyncio.run(
        _post_mix(
            mix_payload,
            reference_payload,
            genre="electronic",
            use_closest_profile=True,
            reference_stage="mix",
        )
    )

    assert response.status_code == 200
    result = MixAnalysisResponse.model_validate(response.json())
    assert result.mode == "reference"
    assert result.selected_genre == "electronic"
    assert result.recommendation_basis == "reference"
    assert list(tmp_path.iterdir()) == []


def test_mix_endpoint_genre_only_requires_measured_profile(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(main.settings, "temp_dir", tmp_path)
    monkeypatch.setattr(
        main,
        "genre_profile_store",
        GenreProfileStore(tmp_path / "empty-genres.json"),
    )
    payload = _wav_bytes(np.full((48_000, 1), 0.1, dtype=np.float32))

    response = asyncio.run(_post_mix(payload, genre="unknown"))

    assert response.status_code == 422
    assert response.json() == {
        "detail": "The selected genre does not have a measured profile."
    }
    assert list(tmp_path.iterdir()) == []


def test_reference_requires_declared_stage(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "temp_dir", tmp_path)
    payload = _wav_bytes(np.full((48_000, 1), 0.1, dtype=np.float32))

    response = asyncio.run(_post_mix(payload, payload))

    assert response.status_code == 422
    assert "reference_stage must be declared" in response.json()["detail"]
    assert list(tmp_path.iterdir()) == []


def test_genre_list_endpoint_returns_measured_catalog(
    tmp_path: Path, monkeypatch
) -> None:
    source_paths = []
    time = np.arange(48_000) / 48_000
    for index, frequency in enumerate((90.0, 100.0, 110.0)):
        path = tmp_path / f"source-{index}.wav"
        sf.write(path, 0.1 * np.sin(2 * np.pi * frequency * time), 48_000)
        source_paths.append(path)
    catalog_path = tmp_path / "genres.json"
    store = GenreProfileStore(catalog_path)
    store.upsert(build_genre_profile("house", "House", source_paths))
    monkeypatch.setattr(main, "genre_profile_store", store)

    async def get_genres() -> httpx.Response:
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/mix/genres")

    response = asyncio.run(get_genres())

    assert response.status_code == 200
    assert response.json()["genres"] == [
        {
            "id": "house",
            "name": "House",
            "source_count": 3,
            "measurement_contract": "2026-07-29.mix.2",
            "role": "genre",
        }
    ]


def test_malformed_genre_profile_returns_controlled_catalog_error(
    tmp_path: Path, monkeypatch
) -> None:
    catalog_path = tmp_path / "malformed-genres.json"
    catalog_path.write_text(
        json.dumps({"version": 1, "profiles": [None]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        main,
        "genre_profile_store",
        GenreProfileStore(catalog_path),
    )

    async def get_genres() -> httpx.Response:
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/mix/genres")

    response = asyncio.run(get_genres())

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Genre profile catalog is unavailable."
    }
