from __future__ import annotations

from subverse.fma_profiles import (
    GENRE_NAMES,
    _eligible_source,
    _feature_labels,
    _is_commercial_license,
    select_sources_from_metadata,
)


def test_feature_labels_support_sequence_class_labels() -> None:
    assert _feature_labels(
        [
            {
                "name": "genres",
                "type": {
                    "_type": "Sequence",
                    "feature": {"names": ["Electronic", "Rock"]},
                },
            }
        ],
        "genres",
    ) == ["Electronic", "Rock"]

    assert _feature_labels(
        [
            {
                "name": "genres",
                "type": {
                    "_type": "List",
                    "feature": {"names": ["Jazz", "Metal"]},
                },
            }
        ],
        "genres",
    ) == ["Jazz", "Metal"]


def test_fma_license_filter_is_commercial_friendly() -> None:
    assert _is_commercial_license("CC-BY 4.0")
    assert _is_commercial_license("CC-BY-SA 3.0")
    assert _is_commercial_license("CC0 1.0")
    assert not _is_commercial_license("CC-BY-NC-SA 4.0")
    assert not _is_commercial_license("CC-BY-ND 4.0")
    assert _is_commercial_license("Attribution 3.0 International")
    assert _is_commercial_license("Attribution-ShareAlike 3.0 International")
    assert not _is_commercial_license(
        "Attribution-NonCommercial-ShareAlike 3.0 International"
    )


def test_only_genres_present_in_the_balanced_source_are_exposed() -> None:
    assert set(GENRE_NAMES) == {"electronic", "hiphop", "pop", "rock"}


def test_eligible_source_requires_exact_genre_and_studio_context() -> None:
    row = {
        "audio": [{"src": "https://example.test/audio.mp3"}],
        "title": "Studio Track",
        "artist": "Artist",
        "album_title": "Album",
        "genres": [51, 73],
        "listens": 1200,
        "license": 0,
        "allow_commercial_use": 1,
        "url": "https://example.test/track",
    }
    source = _eligible_source(42, row, 51, ["CC-BY 4.0"])

    assert source is not None
    assert source["row_idx"] == 42
    assert source["listens"] == 1200
    assert _eligible_source(42, row, 82, ["CC-BY 4.0"]) is None

    live_row = {**row, "album_title": "Live at WFMU"}
    assert _eligible_source(42, live_row, 51, ["CC-BY 4.0"]) is None


def test_metadata_selection_maps_small_subset_rows_and_distinct_artists(
    tmp_path,
) -> None:
    tracks = tmp_path / "tracks.csv"
    tracks.write_text(
        ",album,artist,artist,set,track,track,track,track\n"
        ",title,id,name,subset,genre_top,listens,license,title\n"
        "track_id,,,,,,,,\n"
        "1,A,10,A,small,Electronic,20,Attribution 3.0,T1\n"
        "2,B,20,B,medium,Electronic,999,Attribution 3.0,T2\n"
        "3,C,10,A feat. C,small,Electronic,30,Attribution 3.0,T3\n"
        "4,D,30,C,small,Electronic,10,Attribution-ShareAlike 3.0,T4\n"
        "5,E,40,D,small,Electronic,5,Attribution 4.0,T5\n"
        "6,E,50,E,small,Electronic,50,Attribution 4.0,T6\n",
        encoding="utf-8",
    )

    selected = select_sources_from_metadata(
        tracks,
        ["electronic"],
        count=3,
    )["electronic"]

    assert [source["track_id"] for source in selected] == [6, 3, 4]
    assert [source["row_idx"] for source in selected] == [4, 1, 2]


def test_raw_metadata_adds_direct_original_audio_urls(tmp_path) -> None:
    tracks = tmp_path / "tracks.csv"
    tracks.write_text(
        ",album,artist,artist,set,track,track,track,track\n"
        ",title,id,name,subset,genre_top,listens,license,title\n"
        "track_id,,,,,,,,\n"
        "1,A,10,A,small,Electronic,30,Attribution 3.0,T1\n"
        "2,B,20,B,small,Electronic,20,Attribution 3.0,T2\n"
        "3,C,30,C,small,Electronic,10,Attribution 3.0,T3\n",
        encoding="utf-8",
    )
    raw = tmp_path / "raw_tracks.csv"
    raw.write_text(
        "track_id,track_file,track_url\n"
        "1,music/A One.mp3,https://example.test/t1\n"
        "2,music/B.mp3,https://example.test/t2\n"
        "3,music/C.mp3,https://example.test/t3\n",
        encoding="utf-8",
    )

    selected = select_sources_from_metadata(
        tracks,
        ["electronic"],
        count=3,
        raw_tracks_csv=raw,
    )["electronic"]

    assert selected[0]["audio_url"] == (
        "https://files.freemusicarchive.org/"
        "storage-freemusicarchive-org/music/A%20One.mp3"
    )
    assert selected[0]["audio_source"] == "FMA original full track"
