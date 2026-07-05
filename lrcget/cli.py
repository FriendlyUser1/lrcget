import argparse
import logging
import pathlib
from typing import Literal

from prompt_toolkit import prompt

from lrcget.db.database import (
    delete_missing_track,
    init_db,
    read_missing_track,
    read_track,
    write_missing_track,
    write_track,
)
from lrcget.utils.files import download_lyrics, get_track_info, get_tracks
from lrcget.utils.lrclib import (
    fetch_track,
    LrclibTimeoutError,
    search_track,
    TrackNotFoundError,
)
from lrcget.utils.types import coerceTrackInfo, LrcGetResponse, TrackInfo

logger = logging.getLogger(__name__)


def _search_fallback(
    raw_track_info: TrackInfo,
    timeout: int,
    reason: Literal["partial_metadata", "strict_fetch_not_found"],
) -> LrcGetResponse | None:
    """Single hook for all LRCLIB search-based fallback behavior.

    This is intentionally centralized so upcoming interactive result selection
    and "none of these" handling only need to be implemented once.
    """

    # TODO if partial_metadata, prompt user to add their own attributes
    prompt("test: ")
    return

    logger.info(
        "Running search fallback (%s) for file=%s track=%s artist=%s album=%s",
        reason,
        raw_track_info["file"],
        raw_track_info["track"],
        raw_track_info["artist"],
        raw_track_info["album"],
    )

    found_tracks = search_track(
        raw_track_info["file"],
        timeout,
        track=raw_track_info["track"],
        artist=raw_track_info["artist"],
        album=raw_track_info["album"],
    )

    selected_track = None
    # TODO User selection

    return selected_track


def _parse_extensions(exts_arg: str | None) -> list[str] | None:
    """Parse a comma-separated extension list into normalized suffixes."""
    if exts_arg is None:
        return None

    parsed_exts: list[str] = []

    for raw_ext in exts_arg.split(","):
        normalized = raw_ext.strip().lower()
        if not normalized:
            continue

        if not normalized.startswith("."):
            normalized = f".{normalized}"

        parsed_exts.append(normalized)

    return parsed_exts


def run_sync(music_dir: str, timeout: int, exts: list[str] | None = None) -> int:
    logger.info("Starting lyric sync for directory: %s", music_dir)
    init_db()

    music_path = pathlib.Path(music_dir)
    if not music_path.is_dir():
        logger.error("Music directory is not a directory: %s", music_dir)
        return 1

    track_list = get_tracks(music_path, audio_exts=exts)

    for track in track_list:
        logger.debug("Processing track file: %s", track)
        raw_track_info = get_track_info(track)

        if not raw_track_info:
            logger.debug("Skipping file with unreadable metadata: %s", track)
            continue

        track_info = coerceTrackInfo(raw_track_info)

        if not track_info:
            searched_track = _search_fallback(
                raw_track_info,
                timeout,
                reason="partial_metadata",
            )
            # TODO stop debug
            exit(0)

            continue

        fetched_track = None
        track_db_id = None
        fetch_timed_out = False
        is_cached = False

        missing_lookup = read_missing_track(**track_info)
        if missing_lookup and not missing_lookup["is_expired"]:
            logger.info(
                "Skipping known-missing track %s - %s",
                track_info["artist"],
                track_info["track"],
            )
            continue
        if missing_lookup and missing_lookup["is_expired"]:
            logger.info(
                "Known-missing cache expired for %s - %s; retrying lookup",
                track_info["artist"],
                track_info["track"],
            )

        track_lookup = read_track(**track_info)

        if track_lookup:
            fetched_track = track_lookup["remote_obj"]
            track_db_id = track_lookup["id"]
            is_cached = True
            logger.debug(
                "Using cached lyrics for %s - %s",
                track_info["artist"],
                track_info["track"],
            )
        else:
            logger.info(
                "Fetching lyrics from LRCLIB for %s - %s",
                track_info["artist"],
                track_info["track"],
            )
            try:
                fetched_track = fetch_track(**track_info, timeout=timeout)
            except TrackNotFoundError:
                searched_track = _search_fallback(
                    raw_track_info,
                    timeout,
                    reason="strict_fetch_not_found",
                )
                if searched_track:
                    fetched_track = searched_track
                    logger.info(
                        "Using search fallback result for %s - %s",
                        track_info["artist"],
                        track_info["track"],
                    )
                else:
                    write_missing_track(
                        track_info,
                        existing_id=missing_lookup["id"] if missing_lookup else None,
                    )
                    logger.warning(
                        "No lyrics available for %s - %s",
                        track_info["artist"],
                        track_info["track"],
                    )
                    continue
            except LrclibTimeoutError:
                fetch_timed_out = True

        if not fetched_track:
            if fetch_timed_out:
                logger.warning(
                    "Skipping %s - %s due to timeout; will retry on next run",
                    track_info["artist"],
                    track_info["track"],
                )
                continue

            logger.warning(
                "No lyrics available for %s - %s",
                track_info["artist"],
                track_info["track"],
            )
            continue

        if missing_lookup:
            delete_missing_track(**track_info)

        if track_db_id is None:
            track_db_id = write_track(
                fetched_track,
                track_info,
                existing_id=track_lookup["id"] if track_lookup else None,
            )

            if not track_db_id:
                logger.error(
                    "Failed to persist track data for %s - %s",
                    track_info["artist"],
                    track_info["track"],
                )
                continue

        download_lyrics(track, track_db_id, is_cached=is_cached)

    logger.info("Finished lyric sync run")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lrcget",
        description="Fetch and write synced .lrc lyrics for local audio files.",
    )
    parser.add_argument("music_dir", help="The directory to search for audio files")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "-t", "--timeout", type=int, help="LRCLIB fetch timeout (seconds)", default=15
    )
    parser.add_argument(
        "--exts",
        type=str,
        help="Comma-separated audio extensions to scan (e.g. mp3,flac or .mp3,.flac)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(levelname)s:%(name)s] %(message)s",
    )

    exts = _parse_extensions(args.exts)
    if args.exts is not None and not exts:
        parser.error("--exts must include at least one valid extension")

    try:
        return run_sync(args.music_dir, args.timeout, exts=exts)
    except KeyboardInterrupt:
        logger.info("Sync interrupted by user")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
