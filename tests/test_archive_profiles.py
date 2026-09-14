from __future__ import annotations

from subverse.archive_profiles import (
    _audio_file,
    _commercial_friendly_license,
    _seconds,
    _subject_matches,
)


def test_only_commercial_friendly_licenses_are_accepted() -> None:
    assert _commercial_friendly_license(
        "https://creativecommons.org/licenses/by/4.0/"
    )
    assert _commercial_friendly_license(
        "http://creativecommons.org/licenses/by-sa/3.0/"
    )
    assert _commercial_friendly_license(
        "https://creativecommons.org/publicdomain/zero/1.0/"
    )
    assert not _commercial_friendly_license(
        "https://creativecommons.org/licenses/by-nc-sa/4.0/"
    )
    assert not _commercial_friendly_license(
        "https://creativecommons.org/licenses/by-nd/4.0/"
    )


def test_genre_subject_matching_is_exact() -> None:
    assert _subject_matches(["Electronic", "Ambient"], "electronic")
    assert _subject_matches("Hip-Hop", "hiphop")
    assert not _subject_matches(["Electronic", "Metalcore"], "metal")
    assert not _subject_matches(["Popular Music"], "pop")


def test_audio_file_prefers_full_length_flac() -> None:
    selected = _audio_file(
        [
            {
                "name": "preview.mp3",
                "format": "VBR MP3",
                "length": "00:30",
                "size": "1000",
            },
            {
                "name": "track.mp3",
                "format": "VBR MP3",
                "length": "03:30",
                "size": "5000000",
            },
            {
                "name": "track.flac",
                "format": "Flac",
                "length": "03:30",
                "size": "20000000",
                "source": "original",
            },
        ]
    )

    assert selected is not None
    assert selected["name"] == "track.flac"


def test_archive_duration_parser() -> None:
    assert _seconds("03:30") == 210
    assert _seconds("01:02:03") == 3723
    assert _seconds("215.5") == 215.5
    assert _seconds("unknown") is None
