from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .genre_profiles import (
    MIN_PROFILE_SOURCE_COUNT,
    GenreProfileError,
    GenreProfileStore,
    build_genre_profile,
)

JAMENDO_TRACKS_URL = "https://api.jamendo.com/v3.0/tracks/"
OFFICIAL_FEATURED_GENRES = (
    "lounge",
    "classical",
    "electronic",
    "jazz",
    "pop",
    "hiphop",
    "relaxation",
    "rock",
    "songwriter",
    "world",
    "metal",
    "soundtrack",
)
DEFAULT_TRACKS_PER_GENRE = 24
MAX_TRACK_DOWNLOAD_BYTES = 150 * 1024 * 1024


class JamendoProfileError(RuntimeError):
    pass


def _request_json(url: str) -> Dict[str, Any]:
    request = Request(
        url,
        headers={"User-Agent": "Subverse-Genre-Profile-Builder/1.0"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (OSError, ValueError) as exc:
        raise JamendoProfileError("Jamendo API request failed.") from exc
    headers = payload.get("headers", {})
    if headers.get("status") != "success":
        message = headers.get("error_message") or "Jamendo API returned an error."
        raise JamendoProfileError(str(message))
    return payload


def _eligible_tracks(
    results: Iterable[Dict[str, Any]],
    count: int,
) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    artists: set[str] = set()
    for track in results:
        artist_id = str(track.get("artist_id") or "")
        if (
            not track.get("audiodownload_allowed")
            or not track.get("audiodownload")
            or not track.get("license_ccurl")
            or not artist_id
            or artist_id in artists
        ):
            continue
        selected.append(track)
        artists.add(artist_id)
        if len(selected) == count:
            break
    return selected


def fetch_featured_tracks(
    client_id: str,
    genre: str,
    count: int,
) -> List[Dict[str, Any]]:
    if genre not in OFFICIAL_FEATURED_GENRES:
        raise JamendoProfileError(
            f"Jamendo does not publish a featured selection for genre '{genre}'."
        )
    if count < MIN_PROFILE_SOURCE_COUNT:
        raise JamendoProfileError(
            f"At least {MIN_PROFILE_SOURCE_COUNT} tracks are required."
        )
    params = {
        "client_id": client_id,
        "format": "json",
        "limit": min(200, max(count * 5, 25)),
        "tags": genre,
        "featured": "1",
        "groupby": "artist_id",
        "boost": "popularity_total",
        "include": "licenses musicinfo stats",
        "audioformat": "mp32",
        "audiodlformat": "mp32",
        "type": "single albumtrack",
    }
    payload = _request_json(f"{JAMENDO_TRACKS_URL}?{urlencode(params)}")
    selected = _eligible_tracks(payload.get("results", []), count)
    if len(selected) < count:
        raise JamendoProfileError(
            f"Only {len(selected)} downloadable, licensed and distinct-artist "
            f"tracks were available for '{genre}'."
        )
    return selected


def _download_track(url: str, destination: Path) -> None:
    request = Request(
        url,
        headers={"User-Agent": "Subverse-Genre-Profile-Builder/1.0"},
    )
    bytes_written = 0
    try:
        with urlopen(request, timeout=60) as response, destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > MAX_TRACK_DOWNLOAD_BYTES:
                    raise JamendoProfileError(
                        "A Jamendo source track exceeded the download limit."
                    )
                output.write(chunk)
    except OSError as exc:
        raise JamendoProfileError("A Jamendo source track could not be downloaded.") from exc


def _source_provenance(track: Dict[str, Any]) -> Dict[str, Any]:
    stats = track.get("stats") or {}
    return {
        "track_id": str(track["id"]),
        "track_name": track.get("name") or "",
        "artist_id": str(track.get("artist_id") or ""),
        "artist_name": track.get("artist_name") or "",
        "license_url": track.get("license_ccurl") or "",
        "share_url": track.get("shareurl") or "",
        "releasedate": track.get("releasedate") or "",
        "popularity_evidence": {
            key: stats.get(key)
            for key in (
                "listened_all",
                "downloaded_all",
                "favorited",
                "likes",
                "dislikes",
            )
            if stats.get(key) is not None
        },
    }


def build_jamendo_profile(
    client_id: str,
    genre: str,
    tracks_per_genre: int = DEFAULT_TRACKS_PER_GENRE,
) -> Dict[str, Any]:
    selected = fetch_featured_tracks(client_id, genre, tracks_per_genre)
    temporary_root = Path(tempfile.mkdtemp(prefix=f"subverse-{genre}-"))
    try:
        paths: List[Path] = []
        for index, track in enumerate(selected):
            path = temporary_root / f"{index + 1}-{track['id']}.mp3"
            _download_track(str(track["audiodownload"]), path)
            paths.append(path)
        profile = build_genre_profile(genre, genre.title(), paths)
        profile["provenance"] = {
            "provider": "Jamendo",
            "selection": (
                "featured music-manager selection, genre relevance, "
                "popularity_total boost, one track per artist"
            ),
            "audio_retained": False,
            "sources": [_source_provenance(track) for track in selected],
        }
        return profile
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build measured genre profiles from Jamendo featured and "
            "popularity-ranked Creative Commons tracks."
        )
    )
    parser.add_argument(
        "--client-id",
        default=os.getenv("JAMENDO_CLIENT_ID"),
        help="Jamendo API client id; defaults to JAMENDO_CLIENT_ID.",
    )
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument(
        "--genres",
        nargs="+",
        required=True,
        choices=OFFICIAL_FEATURED_GENRES,
    )
    parser.add_argument(
        "--tracks-per-genre",
        type=int,
        default=DEFAULT_TRACKS_PER_GENRE,
    )
    args = parser.parse_args()
    if not args.client_id:
        parser.error(
            "A Jamendo client id is required via --client-id or JAMENDO_CLIENT_ID."
        )
    if args.tracks_per_genre < MIN_PROFILE_SOURCE_COUNT:
        parser.error(
            f"--tracks-per-genre must be at least {MIN_PROFILE_SOURCE_COUNT}."
        )

    store = GenreProfileStore(args.catalog)
    for genre in args.genres:
        try:
            profile = build_jamendo_profile(
                args.client_id,
                genre,
                args.tracks_per_genre,
            )
            store.upsert(profile)
        except (JamendoProfileError, GenreProfileError) as exc:
            parser.error(f"{genre}: {exc}")


if __name__ == "__main__":
    main()
