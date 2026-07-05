import argparse
import logging
import pathlib

from lrcget.db.database import (
    delete_missing_track,
    init_db,
    read_missing_track,
    read_track,
    write_missing_track,
    write_track,
)
from lrcget.utils.files import download_lyrics, get_track_info, get_tracks
from lrcget.utils.lrclib import fetch_track, LrclibTimeoutError, TrackNotFoundError
from lrcget.utils.types import LrcGetResponse

logger = logging.getLogger(__name__)


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


def _should_mark_known_missing(track_data: LrcGetResponse) -> bool:
    """Return true when a track has no synced lyrics and is not instrumental."""
    return not bool(track_data.get("instrumental")) and not bool(
        track_data.get("syncedLyrics")
    )


def run_sync(
    music_dir: str,
    timeout: int,
    exts: list[str] | None = None,
    force_missing: bool = False,
    ignore_missing: bool = False,
) -> int:
    logger.info("Starting lyric sync for directory: %s", music_dir)
    init_db()

    try:
        # section: input path validation + file discovery
        music_path = pathlib.Path(music_dir)
        if not music_path.is_dir():
            logger.error("Music directory is not a directory: %s", music_dir)
            return 1

        track_list = get_tracks(music_path, audio_exts=exts)

        # section: process each local track independently
        for track in track_list:
            logger.debug("Processing track file: %s", track)
            track_info = get_track_info(track)

            # section: skip early when metadata is incomplete
            if not track_info:
                logger.debug("Skipping file with incomplete metadata: %s", track)
                continue

            fetched_track = None
            track_db_id = None
            fetch_timed_out = False
            is_cached = False

            # section: known-missing cache gates
            missing_lookup = read_missing_track(**track_info)
            if missing_lookup and ignore_missing:
                logger.info(
                    "Skipping known-missing track %s - %s",
                    track_info["artist"],
                    track_info["track"],
                )
                continue

            if (
                missing_lookup
                and not missing_lookup["is_expired"]
                and not force_missing
            ):
                logger.info(
                    "Skipping known-missing track %s - %s",
                    track_info["artist"],
                    track_info["track"],
                )
                continue
            if missing_lookup and (missing_lookup["is_expired"] or force_missing):
                logger.info(
                    "Known-missing cache expired for %s - %s; retrying lookup",
                    track_info["artist"],
                    track_info["track"],
                )

            # section: prefer cached track rows before any remote fetch
            track_lookup = read_track(**track_info)

            if track_lookup:
                fetched_track = track_lookup["remote_obj"]
                track_db_id = track_lookup["id"]
                is_cached = True
                delete_missing_track(**track_info)

                # cached rows can still represent known-missing cases
                if _should_mark_known_missing(fetched_track):
                    write_missing_track(
                        track_info,
                        existing_id=missing_lookup["id"] if missing_lookup else None,
                    )
                    logger.warning(
                        "Cached track %s - %s has no synced lyrics and is not instrumental; marking known-missing",
                        track_info["artist"],
                        track_info["track"],
                    )
                    continue

                logger.debug(
                    "Using cached lyrics for %s - %s",
                    track_info["artist"],
                    track_info["track"],
                )
            else:
                # section: remote fetch path
                logger.info(
                    "Fetching lyrics from LRCLIB for %s - %s",
                    track_info["artist"],
                    track_info["track"],
                )
                try:
                    fetched_track = fetch_track(**track_info, timeout=timeout)
                except TrackNotFoundError:
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

            # section: track exists but is effectively known-missing
            if fetched_track and _should_mark_known_missing(fetched_track):
                write_missing_track(
                    track_info,
                    existing_id=missing_lookup["id"] if missing_lookup else None,
                )
                logger.warning(
                    "No synced lyrics available for non-instrumental track %s - %s; marking known-missing",
                    track_info["artist"],
                    track_info["track"],
                )
                continue

            # section: nothing usable returned from cache or remote
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

            # section: finalize cache state and write lyrics
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
    except KeyboardInterrupt:
        logger.warning("Sync interrupted by user")
        return 130

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
    missing_group = parser.add_mutually_exclusive_group()
    missing_group.add_argument(
        "--force-missing",
        action="store_true",
        help="Re-fetch all tracks currently in the known-missing cache, ignoring expiry",
    )
    missing_group.add_argument(
        "--ignore-missing",
        action="store_true",
        help="Skip tracks in the known-missing cache, even when the cache entry is expired",
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

    return run_sync(
        args.music_dir,
        args.timeout,
        exts=exts,
        force_missing=args.force_missing,
        ignore_missing=args.ignore_missing,
    )


if __name__ == "__main__":
    raise SystemExit(main())
