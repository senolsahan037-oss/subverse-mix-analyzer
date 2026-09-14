from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from subverse import jamendo_profiles


def _track(
    track_id: str,
    artist_id: str,
    *,
    downloadable: bool = True,
    licensed: bool = True,
) -> dict[str, object]:
    return {
        "id": track_id,
        "name": f"Track {track_id}",
        "artist_id": artist_id,
        "artist_name": f"Artist {artist_id}",
        "audiodownload_allowed": downloadable,
        "audiodownload": (
            f"https://example.test/{track_id}.mp3" if downloadable else ""
        ),
        "license_ccurl": (
            "https://creativecommons.org/licenses/by/4.0/"
            if licensed
            else ""
        ),
        "shareurl": f"https://example.test/tracks/{track_id}",
        "releasedate": "2025-01-01",
        "stats": {"listened_all": int(track_id) * 100},
    }


def test_track_selection_requires_license_download_and_distinct_artist() -> None:
    selected = jamendo_profiles._eligible_tracks(
        [
            _track("1", "artist-1"),
            _track("2", "artist-1"),
            _track("3", "artist-2", downloadable=False),
            _track("4", "artist-3", licensed=False),
            _track("5", "artist-4"),
            _track("6", "artist-5"),
        ],
        count=3,
    )

    assert [track["id"] for track in selected] == ["1", "5", "6"]


def test_jamendo_builder_deletes_audio_and_keeps_provenance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tracks = [
        _track("1", "artist-1"),
        _track("2", "artist-2"),
        _track("3", "artist-3"),
    ]
    work_path = tmp_path / "temporary-downloads"
    monkeypatch.setattr(
        jamendo_profiles,
        "fetch_featured_tracks",
        lambda client_id, genre, count: tracks,
    )
    monkeypatch.setattr(
        jamendo_profiles.tempfile,
        "mkdtemp",
        lambda prefix: str(work_path),
    )

    def fake_download(url: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        sample_rate = 48_000
        time = np.arange(sample_rate) / sample_rate
        frequency = 100 + int(destination.name.split("-", maxsplit=1)[0])
        sf.write(
            destination,
            0.1 * np.sin(2 * np.pi * frequency * time),
            sample_rate,
            format="WAV",
        )

    monkeypatch.setattr(jamendo_profiles, "_download_track", fake_download)

    profile = jamendo_profiles.build_jamendo_profile(
        "client-id",
        "electronic",
        tracks_per_genre=3,
    )

    assert not work_path.exists()
    assert profile["source_count"] == 3
    assert profile["provenance"]["audio_retained"] is False
    assert [
        source["track_id"]
        for source in profile["provenance"]["sources"]
    ] == ["1", "2", "3"]
