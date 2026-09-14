from __future__ import annotations

import argparse
import csv
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .genre_profiles import (
    MIN_PROFILE_SOURCE_COUNT,
    GenreProfileError,
    GenreProfileStore,
    build_genre_profile,
)

DATASET_ID = "benjamin-paine/free-music-archive-small"
DATASET_CONFIG = "default"
DATASET_SPLIT = "train"
DATASET_API = "https://datasets-server.huggingface.co"
FMA_AUDIO_BASE_URL = (
    "https://files.freemusicarchive.org/storage-freemusicarchive-org"
)
PAGE_SIZE = 100
REQUEST_INTERVAL_SECONDS = 1.0
DEFAULT_TRACKS_PER_GENRE = 24

GENRE_NAMES = {
    "electronic": "Electronic",
    "hiphop": "Hip-Hop",
    "rock": "Rock",
    "pop": "Pop",
}

_EXCLUDED_CONTEXT = (
    "interview",
    "full set",
    "live at",
    "live on",
    "radio session",
    "reprise",
)
_EXCLUDED_TITLES = {"intro", "outro", "interlude", "skit"}


class FmaProfileError(RuntimeError):
    pass


def _request_json(url: str, attempts: int = 6) -> Dict[str, Any]:
    request = Request(
        url,
        headers={"User-Agent": "Subverse-Genre-Profile-Builder/1.0"},
    )
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=60) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt + 1 == attempts:
                raise FmaProfileError(
                    f"FMA dataset request failed with HTTP {exc.code}."
                ) from exc
        except (URLError, OSError, ValueError) as exc:
            if attempt + 1 == attempts:
                raise FmaProfileError(
                    f"FMA dataset request failed: {type(exc).__name__}."
                ) from exc
            retry_after = exc.headers.get("Retry-After")
            if exc.code == 429:
                try:
                    delay = float(retry_after) if retry_after else 30.0
                except ValueError:
                    delay = 30.0
                time.sleep(max(delay, 1.0))
                continue
        time.sleep(min(2 ** attempt, 12))
    raise FmaProfileError("FMA dataset request failed.")


def _dataset_url(endpoint: str, **params: Any) -> str:
    return f"{DATASET_API}/{endpoint}?{urlencode(params)}"


def _feature_labels(
    features: Iterable[Dict[str, Any]],
    feature_name: str,
) -> List[str]:
    feature = next(
        (item for item in features if item.get("name") == feature_name),
        None,
    )
    if feature is None:
        raise FmaProfileError(f"FMA dataset has no '{feature_name}' field.")
    feature_type = feature.get("type", {})
    if feature_type.get("_type") in {"Sequence", "List"}:
        feature_type = feature_type.get("feature", {})
    names = feature_type.get("names")
    if not isinstance(names, list):
        raise FmaProfileError(
            f"FMA dataset field '{feature_name}' has no class labels."
        )
    return [str(name) for name in names]


def _is_commercial_license(name: str) -> bool:
    normalized = name.upper()
    return (
        normalized.startswith("CC-BY ")
        or normalized.startswith("CC-BY-SA ")
        or normalized == "CC0 1.0"
        or (
            "ATTRIBUTION" in normalized
            and "NONCOMMERCIAL" not in normalized
            and "NO DERIVATIVES" not in normalized
            and "NODERIVATIVES" not in normalized
        )
        or "CC0" in normalized
        or "PUBLIC DOMAIN" in normalized
    )


def _audio_url(row: Dict[str, Any]) -> str:
    audio = row.get("audio")
    if not isinstance(audio, list) or not audio:
        return ""
    return str(audio[0].get("src") or "")


def _eligible_source(
    row_idx: int,
    row: Dict[str, Any],
    genre_index: int,
    license_labels: List[str],
) -> Dict[str, Any] | None:
    genres = row.get("genres")
    license_index = row.get("license")
    if (
        not isinstance(genres, list)
        or genre_index not in genres
        or row.get("allow_commercial_use") != 1
        or not isinstance(license_index, int)
        or not 0 <= license_index < len(license_labels)
    ):
        return None
    license_name = license_labels[license_index]
    if not _is_commercial_license(license_name):
        return None
    artist = str(row.get("artist") or "").strip()
    title = str(row.get("title") or "").strip()
    context = f"{title} {row.get('album_title') or ''}".casefold()
    audio_url = _audio_url(row)
    if (
        not artist
        or not title
        or not audio_url
        or any(marker in context for marker in _EXCLUDED_CONTEXT)
    ):
        return None
    return {
        "row_idx": row_idx,
        "title": title,
        "artist": artist,
        "album_title": str(row.get("album_title") or ""),
        "listens": int(row.get("listens") or 0),
        "license": license_name,
        "track_url": str(row.get("url") or ""),
        "audio_url": audio_url,
    }


def _page(offset: int) -> Dict[str, Any]:
    return _request_json(
        _dataset_url(
            "rows",
            dataset=DATASET_ID,
            config=DATASET_CONFIG,
            split=DATASET_SPLIT,
            offset=offset,
            length=PAGE_SIZE,
        )
    )


def _source_audio_url(source: Dict[str, Any]) -> str:
    row_idx = int(source["row_idx"])
    payload = _request_json(
        _dataset_url(
            "rows",
            dataset=DATASET_ID,
            config=DATASET_CONFIG,
            split=DATASET_SPLIT,
            offset=row_idx,
            length=1,
        )
    )
    rows = payload.get("rows", [])
    if len(rows) != 1 or int(rows[0].get("row_idx", -1)) != row_idx:
        raise FmaProfileError(f"FMA audio row {row_idx} is unavailable.")
    row = rows[0].get("row", {})
    if (
        str(row.get("title") or "").strip().casefold()
        != str(source["title"]).strip().casefold()
        or str(row.get("artist") or "").strip().casefold()
        != str(source["artist"]).strip().casefold()
    ):
        raise FmaProfileError(
            f"FMA audio row {row_idx} does not match track {source.get('track_id')}."
        )
    audio_url = _audio_url(row)
    if not audio_url:
        raise FmaProfileError(f"FMA audio row {row_idx} has no audio URL.")
    return audio_url


def _row_count() -> int:
    payload = _request_json(_dataset_url("size", dataset=DATASET_ID))
    splits = payload.get("size", {}).get("splits", [])
    split = next(
        (
            item
            for item in splits
            if item.get("config") == DATASET_CONFIG
            and item.get("split") == DATASET_SPLIT
        ),
        None,
    )
    if split is None or not isinstance(split.get("num_rows"), int):
        raise FmaProfileError("FMA dataset row count is unavailable.")
    return int(split["num_rows"])


def select_sources_from_metadata(
    tracks_csv: Path,
    genres: Iterable[str],
    count: int = DEFAULT_TRACKS_PER_GENRE,
    raw_tracks_csv: Path | None = None,
) -> Dict[str, List[Dict[str, Any]]]:
    requested = list(dict.fromkeys(genres))
    unsupported = [genre for genre in requested if genre not in GENRE_NAMES]
    if unsupported:
        raise FmaProfileError(f"Unsupported genre '{unsupported[0]}'.")
    if count < MIN_PROFILE_SOURCE_COUNT:
        raise FmaProfileError(
            f"At least {MIN_PROFILE_SOURCE_COUNT} tracks are required."
        )

    candidates: Dict[str, List[Dict[str, Any]]] = {
        genre: [] for genre in requested
    }
    name_to_id = {name: genre for genre, name in GENRE_NAMES.items()}
    try:
        source = tracks_csv.open(newline="", encoding="utf-8")
    except OSError as exc:
        raise FmaProfileError("FMA tracks.csv could not be opened.") from exc
    with source:
        reader = csv.reader(source)
        try:
            groups = next(reader)
            fields = next(reader)
            next(reader)
        except StopIteration as exc:
            raise FmaProfileError("FMA tracks.csv is incomplete.") from exc
        columns = {
            (group, field): index
            for index, (group, field) in enumerate(zip(groups, fields))
        }
        required = {
            ("set", "subset"),
            ("track", "genre_top"),
            ("track", "listens"),
            ("track", "license"),
            ("track", "title"),
            ("album", "title"),
            ("artist", "name"),
            ("artist", "id"),
        }
        if not required.issubset(columns):
            raise FmaProfileError("FMA tracks.csv has an incompatible schema.")

        small_row_idx = 0
        for row in reader:
            if row[columns[("set", "subset")]] != "small":
                continue
            row_idx = small_row_idx
            small_row_idx += 1
            genre_name = row[columns[("track", "genre_top")]]
            genre = name_to_id.get(genre_name)
            if genre not in candidates:
                continue
            license_name = row[columns[("track", "license")]]
            if not _is_commercial_license(license_name):
                continue
            title = row[columns[("track", "title")]].strip()
            album_title = row[columns[("album", "title")]].strip()
            artist = row[columns[("artist", "name")]].strip()
            context = f"{title} {album_title}".casefold()
            if (
                not row
                or not row[0].isdigit()
                or not title
                or not artist
                or title.casefold() in _EXCLUDED_TITLES
                or any(marker in context for marker in _EXCLUDED_CONTEXT)
            ):
                continue
            try:
                listens = int(row[columns[("track", "listens")]] or 0)
            except ValueError:
                listens = 0
            candidates[genre].append(
                {
                    "row_idx": row_idx,
                    "track_id": int(row[0]),
                    "title": title,
                    "artist": artist,
                    "artist_id": int(row[columns[("artist", "id")]]),
                    "album_title": album_title,
                    "listens": listens,
                    "license": license_name,
                }
            )

    selected: Dict[str, List[Dict[str, Any]]] = {}
    for genre, items in candidates.items():
        artists: set[str] = set()
        albums: set[str] = set()
        selected[genre] = []
        for item in sorted(
            items,
            key=lambda candidate: (-candidate["listens"], candidate["track_id"]),
        ):
            artist_key = str(item["artist_id"])
            album_key = item["album_title"].casefold()
            if artist_key in artists or album_key in albums:
                continue
            selected[genre].append(item)
            artists.add(artist_key)
            albums.add(album_key)
            if len(selected[genre]) == count:
                break
        if len(selected[genre]) < count:
            raise FmaProfileError(
                f"Only {len(selected[genre])} eligible distinct-artist tracks "
                f"were found for '{genre}'."
            )
    if raw_tracks_csv is not None:
        selected_ids = {
            source["track_id"]
            for sources in selected.values()
            for source in sources
        }
        raw_by_id: Dict[int, Dict[str, str]] = {}
        try:
            raw_source = raw_tracks_csv.open(newline="", encoding="utf-8")
        except OSError as exc:
            raise FmaProfileError("FMA raw_tracks.csv could not be opened.") from exc
        with raw_source:
            for row in csv.DictReader(raw_source):
                track_id = row.get("track_id", "")
                if track_id.isdigit() and int(track_id) in selected_ids:
                    raw_by_id[int(track_id)] = row
        missing = selected_ids.difference(raw_by_id)
        if missing:
            raise FmaProfileError(
                f"FMA raw_tracks.csv is missing track {min(missing)}."
            )
        for sources in selected.values():
            for source in sources:
                raw = raw_by_id[source["track_id"]]
                track_file = str(raw.get("track_file") or "").strip()
                if not track_file:
                    raise FmaProfileError(
                        f"FMA track {source['track_id']} has no audio path."
                    )
                source["audio_url"] = (
                    f"{FMA_AUDIO_BASE_URL}/{quote(track_file, safe='/')}"
                )
                source["track_url"] = str(raw.get("track_url") or "")
                source["audio_source"] = "FMA original full track"
    return selected


def select_sources(
    genres: Iterable[str],
    count: int = DEFAULT_TRACKS_PER_GENRE,
) -> Dict[str, List[Dict[str, Any]]]:
    requested = list(dict.fromkeys(genres))
    unsupported = [genre for genre in requested if genre not in GENRE_NAMES]
    if unsupported:
        raise FmaProfileError(f"Unsupported genre '{unsupported[0]}'.")
    if count < MIN_PROFILE_SOURCE_COUNT:
        raise FmaProfileError(
            f"At least {MIN_PROFILE_SOURCE_COUNT} tracks are required."
        )

    first = _page(0)
    genre_labels = _feature_labels(first.get("features", []), "genres")
    license_labels = _feature_labels(first.get("features", []), "license")
    genre_indices = {
        genre: genre_labels.index(GENRE_NAMES[genre])
        for genre in requested
    }
    candidates: Dict[str, List[Dict[str, Any]]] = {
        genre: [] for genre in requested
    }

    def collect(payload: Dict[str, Any]) -> None:
        for wrapped in payload.get("rows", []):
            row = wrapped.get("row", {})
            row_idx = int(wrapped.get("row_idx", -1))
            for genre, genre_index in genre_indices.items():
                source = _eligible_source(
                    row_idx,
                    row,
                    genre_index,
                    license_labels,
                )
                if source is not None:
                    candidates[genre].append(source)

    collect(first)
    for offset in range(PAGE_SIZE, _row_count(), PAGE_SIZE):
        time.sleep(REQUEST_INTERVAL_SECONDS)
        collect(_page(offset))

    selected: Dict[str, List[Dict[str, Any]]] = {}
    for genre, items in candidates.items():
        artists: set[str] = set()
        selected[genre] = []
        for item in sorted(
            items,
            key=lambda source: (-source["listens"], source["row_idx"]),
        ):
            artist_key = item["artist"].casefold()
            if artist_key in artists:
                continue
            selected[genre].append(item)
            artists.add(artist_key)
            if len(selected[genre]) == count:
                break
        if len(selected[genre]) < count:
            raise FmaProfileError(
                f"Only {len(selected[genre])} eligible distinct-artist tracks "
                f"were found for '{genre}'."
            )
    return selected


def _download_source(source: Dict[str, Any], destination: Path) -> None:
    request = Request(
        str(source["audio_url"]),
        headers={"User-Agent": "Subverse-Genre-Profile-Builder/1.0"},
    )
    try:
        with urlopen(request, timeout=90) as response, destination.open("wb") as output:
            shutil.copyfileobj(response, output)
    except OSError as exc:
        raise FmaProfileError("An FMA audio excerpt could not be downloaded.") from exc


def build_fma_profile(
    genre: str,
    sources: List[Dict[str, Any]],
) -> Dict[str, Any]:
    temporary_root = Path(tempfile.mkdtemp(prefix=f"subverse-fma-{genre}-"))
    try:
        paths: List[Path] = []
        for index, source in enumerate(sources):
            path = temporary_root / f"{index + 1}.mp3"
            hydrated_source = {
                **source,
                "audio_url": source.get("audio_url")
                or _source_audio_url(source),
            }
            _download_source(hydrated_source, path)
            paths.append(path)
        profile = build_genre_profile(genre, GENRE_NAMES[genre], paths)
        direct_audio = all(source.get("audio_source") for source in sources)
        profile["provenance"] = {
            "provider": (
                "Free Music Archive official metadata and original audio"
                if direct_audio
                else "FMA-small mirror via Hugging Face"
            ),
            "dataset": DATASET_ID,
            "selection": (
                "exact genre label, commercial-use CC BY/CC BY-SA/CC0 license, "
                "listens descending, one excerpt per artist, live/interview "
                "material excluded"
            ),
            "audio_scope": (
                "full source tracks"
                if direct_audio
                else "30-second FMA-small excerpts"
            ),
            "metric_scope": (
                "loudness-relative spectrum and measured released-master "
                "distributions; mix-stage comparisons use spectrum only"
            ),
            "audio_retained": False,
            "sources": [
                {
                    key: value
                    for key, value in source.items()
                    if key != "audio_url"
                }
                for source in sources
            ],
        }
        return profile
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build measured genre profiles from FMA-small without an account "
            "or API key."
        )
    )
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument(
        "--genres",
        nargs="+",
        required=True,
        choices=tuple(GENRE_NAMES),
    )
    parser.add_argument(
        "--tracks-per-genre",
        type=int,
        default=DEFAULT_TRACKS_PER_GENRE,
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Print selected provenance without downloading or measuring audio.",
    )
    parser.add_argument(
        "--metadata-csv",
        type=Path,
        help=(
            "Official FMA fma_metadata/tracks.csv. When supplied, selection is "
            "local and Dataset Viewer is used only for selected audio excerpts."
        ),
    )
    parser.add_argument(
        "--raw-tracks-csv",
        type=Path,
        help=(
            "Official FMA fma_metadata/raw_tracks.csv. Supplies direct original "
            "audio URLs and avoids Dataset Viewer lookup."
        ),
    )
    args = parser.parse_args()
    if args.tracks_per_genre < MIN_PROFILE_SOURCE_COUNT:
        parser.error(
            f"--tracks-per-genre must be at least {MIN_PROFILE_SOURCE_COUNT}."
        )

    try:
        selections = (
            select_sources_from_metadata(
                args.metadata_csv,
                args.genres,
                args.tracks_per_genre,
                args.raw_tracks_csv,
            )
            if args.metadata_csv is not None
            else select_sources(args.genres, args.tracks_per_genre)
        )
        if args.inspect:
            print(json.dumps(selections, ensure_ascii=False, indent=2))
            return
        store = GenreProfileStore(args.catalog)
        for genre in args.genres:
            store.upsert(build_fma_profile(genre, selections[genre]))
    except (FmaProfileError, GenreProfileError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
