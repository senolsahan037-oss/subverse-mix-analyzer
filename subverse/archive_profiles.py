from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .genre_profiles import (
    MIN_PROFILE_SOURCE_COUNT,
    GenreProfileError,
    GenreProfileStore,
    build_genre_profile,
)
from .analyzer import AudioDecodeError
from .mix_analyzer import extract_mix_features
from .source_limits import MAX_TRACK_DOWNLOAD_BYTES

ARCHIVE_SEARCH_URL = "https://archive.org/advancedsearch.php"
ARCHIVE_METADATA_URL = "https://archive.org/metadata"
ARCHIVE_DOWNLOAD_URL = "https://archive.org/download"
DEFAULT_TRACKS_PER_GENRE = 24

GENRE_QUERIES = {
    "electronic": 'subject:"electronic"',
    "hiphop": '(subject:"hip hop" OR subject:"hiphop" OR subject:"hip-hop")',
    "rock": 'subject:"rock"',
    "pop": 'subject:"pop"',
    "jazz": 'subject:"jazz"',
    "metal": 'subject:"metal"',
}
GENRE_NAMES = {
    "electronic": "Electronic",
    "hiphop": "Hip-Hop",
    "rock": "Rock",
    "pop": "Pop",
    "jazz": "Jazz",
    "metal": "Metal",
}


class ArchiveProfileError(RuntimeError):
    pass


def _request_json(url: str) -> Dict[str, Any]:
    request = Request(
        url,
        headers={"User-Agent": "Subverse-Genre-Profile-Builder/1.0"},
    )
    try:
        with urlopen(request, timeout=45) as response:
            return json.load(response)
    except (OSError, ValueError) as exc:
        raise ArchiveProfileError("Internet Archive request failed.") from exc


def _commercial_friendly_license(license_url: str) -> bool:
    normalized = license_url.strip().lower().replace("http://", "https://")
    return any(
        marker in normalized
        for marker in (
            "creativecommons.org/licenses/by/",
            "creativecommons.org/licenses/by-sa/",
            "creativecommons.org/publicdomain/zero/",
            "creativecommons.org/publicdomain/mark/",
        )
    )


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _subject_matches(subject: Any, genre: str) -> bool:
    normalized = {
        item.strip().lower().replace("_", " ")
        for item in _as_list(subject)
    }
    aliases = {
        "electronic": {"electronic", "electronic music", "electronica"},
        "hiphop": {"hip hop", "hiphop", "hip-hop"},
        "rock": {"rock"},
        "pop": {"pop"},
        "jazz": {"jazz"},
        "metal": {"metal"},
    }[genre]
    return bool(normalized.intersection(aliases))


def search_items(genre: str, rows: int = 1000) -> List[Dict[str, Any]]:
    try:
        genre_query = GENRE_QUERIES[genre]
    except KeyError as exc:
        raise ArchiveProfileError(f"Unsupported genre '{genre}'.") from exc
    params = [
        ("q", f"mediatype:audio AND {genre_query} AND licenseurl:http*"),
        ("fl[]", "identifier"),
        ("fl[]", "title"),
        ("fl[]", "creator"),
        ("fl[]", "downloads"),
        ("fl[]", "licenseurl"),
        ("fl[]", "subject"),
        ("sort[]", "downloads desc"),
        ("rows", str(rows)),
        ("page", "1"),
        ("output", "json"),
    ]
    payload = _request_json(f"{ARCHIVE_SEARCH_URL}?{urlencode(params)}")
    return list(payload.get("response", {}).get("docs", []))


def _seconds(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    parts = text.split(":")
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        return None
    if len(numbers) == 2:
        return numbers[0] * 60.0 + numbers[1]
    if len(numbers) == 3:
        return numbers[0] * 3600.0 + numbers[1] * 60.0 + numbers[2]
    return None


def _audio_file(files: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    candidates: List[tuple[int, float, Dict[str, Any]]] = []
    for file in files:
        name = str(file.get("name") or "")
        lowered = name.lower()
        if (
            not name
            or file.get("private") is True
            or any(token in lowered for token in ("sample", "preview", "spectrogram"))
            or not lowered.endswith((".flac", ".mp3", ".ogg"))
        ):
            continue
        format_name = str(file.get("format") or "").lower()
        if lowered.endswith(".flac") or "flac" in format_name:
            preference = 4
        elif lowered.endswith(".mp3") and file.get("source") == "original":
            preference = 3
        elif lowered.endswith(".mp3") or "vbr mp3" in format_name:
            preference = 2
        elif lowered.endswith(".ogg") or "ogg vorbis" in format_name:
            preference = 1
        else:
            continue
        try:
            size = int(file.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        if size > MAX_TRACK_DOWNLOAD_BYTES:
            continue
        duration = _seconds(file.get("length"))
        if duration is not None and not 90.0 <= duration <= 900.0:
            continue
        candidates.append((preference, duration or 0.0, file))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate[0], candidate[1]))[2]


def select_sources(
    genre: str,
    count: int,
) -> List[Dict[str, Any]]:
    if count < MIN_PROFILE_SOURCE_COUNT:
        raise ArchiveProfileError(
            f"At least {MIN_PROFILE_SOURCE_COUNT} tracks are required."
        )
    sources: List[Dict[str, Any]] = []
    creators: set[str] = set()
    for item in search_items(genre):
        license_url = str(item.get("licenseurl") or "")
        creator = str(item.get("creator") or "").strip()
        if (
            not _commercial_friendly_license(license_url)
            or not _subject_matches(item.get("subject"), genre)
            or not creator
            or creator.casefold() in creators
        ):
            continue
        identifier = str(item.get("identifier") or "")
        if not identifier:
            continue
        metadata = _request_json(
            f"{ARCHIVE_METADATA_URL}/{quote(identifier, safe='')}"
        )
        file = _audio_file(metadata.get("files", []))
        if file is None:
            continue
        sources.append(
            {
                "identifier": identifier,
                "item_title": str(item.get("title") or ""),
                "creator": creator,
                "downloads": int(item.get("downloads") or 0),
                "license_url": license_url,
                "subject": _as_list(item.get("subject")),
                "file_name": str(file["name"]),
                "file_size": int(file.get("size") or 0),
                "file_duration_seconds": _seconds(file.get("length")),
            }
        )
        creators.add(creator.casefold())
        if len(sources) == count:
            break
    if len(sources) < count:
        raise ArchiveProfileError(
            f"Only {len(sources)} eligible distinct-creator sources were found "
            f"for '{genre}'."
        )
    return sources


def _download_source(source: Dict[str, Any], destination: Path) -> None:
    identifier = quote(str(source["identifier"]), safe="")
    file_name = quote(str(source["file_name"]), safe="/")
    url = f"{ARCHIVE_DOWNLOAD_URL}/{identifier}/{file_name}"
    request = Request(
        url,
        headers={"User-Agent": "Subverse-Genre-Profile-Builder/1.0"},
    )
    bytes_written = 0
    try:
        with urlopen(request, timeout=8) as response, destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > MAX_TRACK_DOWNLOAD_BYTES:
                    raise ArchiveProfileError(
                        "An Internet Archive source exceeded the download limit."
                    )
                output.write(chunk)
    except OSError as exc:
        raise ArchiveProfileError(
            "An Internet Archive source could not be downloaded."
        ) from exc


def build_archive_profile(
    genre: str,
    tracks_per_genre: int = DEFAULT_TRACKS_PER_GENRE,
) -> Dict[str, Any]:
    sources = select_sources(genre, tracks_per_genre)
    temporary_root = Path(tempfile.mkdtemp(prefix=f"subverse-archive-{genre}-"))
    try:
        paths: List[Path] = []
        downloaded_sources: List[Dict[str, Any]] = []
        for index, source in enumerate(sources):
            suffix = Path(str(source["file_name"])).suffix.lower() or ".audio"
            path = temporary_root / f"{index + 1}{suffix}"
            try:
                _download_source(source, path)
            except ArchiveProfileError:
                path.unlink(missing_ok=True)
                continue
            paths.append(path)
            downloaded_sources.append(source)
        if len(paths) < MIN_PROFILE_SOURCE_COUNT:
            raise ArchiveProfileError(
                f"Only {len(paths)} full-length sources could be downloaded for '{genre}'."
            )
        valid_paths: List[Path] = []
        valid_sources: List[Dict[str, Any]] = []
        for path, source in zip(paths, downloaded_sources):
            try:
                extract_mix_features(path, path.name)
            except AudioDecodeError:
                path.unlink(missing_ok=True)
                continue
            valid_paths.append(path)
            valid_sources.append(source)
        if len(valid_paths) < MIN_PROFILE_SOURCE_COUNT:
            raise ArchiveProfileError(
                f"Only {len(valid_paths)} decodable full-length sources remain for '{genre}'."
            )
        profile = build_genre_profile(genre, GENRE_NAMES[genre], valid_paths)
        profile["provenance"] = {
            "provider": "Internet Archive",
            "selection": (
                "exact genre subject, commercial-friendly Creative Commons or "
                "public-domain license, downloads descending, one item per creator"
            ),
            "audio_retained": False,
            "sources": [
                {
                    **source,
                    "item_url": (
                        f"https://archive.org/details/{source['identifier']}"
                    ),
                }
                for source in valid_sources
            ],
        }
        return profile
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build measured genre profiles from licensed, popular Internet "
            "Archive audio without an API key."
        )
    )
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument(
        "--genres",
        nargs="+",
        required=True,
        choices=tuple(GENRE_QUERIES),
    )
    parser.add_argument(
        "--tracks-per-genre",
        type=int,
        default=DEFAULT_TRACKS_PER_GENRE,
    )
    args = parser.parse_args()
    if args.tracks_per_genre < MIN_PROFILE_SOURCE_COUNT:
        parser.error(
            f"--tracks-per-genre must be at least {MIN_PROFILE_SOURCE_COUNT}."
        )

    store = GenreProfileStore(args.catalog)
    for genre in args.genres:
        try:
            store.upsert(build_archive_profile(genre, args.tracks_per_genre))
        except (ArchiveProfileError, GenreProfileError) as exc:
            parser.error(f"{genre}: {exc}")


if __name__ == "__main__":
    main()
