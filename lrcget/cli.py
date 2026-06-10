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
from lrcget.utils.lrclib import fetch_track

logger = logging.getLogger(__name__)


def run_sync(music_dir: str, timeout: int) -> int:
    logger.info("Starting lyric sync for directory: %s", music_dir)
    init_db()

    music_path = pathlib.Path(music_dir)
    if not music_path.is_dir():
        logger.error("Music directory is not a directory: %s", music_dir)
        return 1

    track_list = get_tracks(music_path)

    for track in track_list:
        logger.debug("Processing track file: %s", track)
        track_info = get_track_info(track)

        if not track_info:
            logger.debug("Skipping file with incomplete metadata: %s", track)
            continue

        fetched_track = None
        track_db_id = None

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

        if track_lookup and not track_lookup["is_expired"]:
            fetched_track = track_lookup["remote_obj"]
            track_db_id = track_lookup["id"]
            delete_missing_track(**track_info)
            logger.info(
                "Using cached lyrics for %s - %s",
                track_info["artist"],
                track_info["track"],
            )
        else:
            if track_lookup and track_lookup["is_expired"]:
                cached_remote = track_lookup["remote_obj"]
                is_instrumental = bool(cached_remote.get("instrumental"))
                if is_instrumental and not track_lookup["has_synced_lyrics"]:
                    logger.info(
                        "Track data for %s - %s expired but is instrumental with no synced lyrics; skipping fetch",
                        track_info["artist"],
                        track_info["track"],
                    )
                    fetched_track = cached_remote
                else:
                    logger.info(
                        "Track data for %s - %s expired, fetching",
                        track_info["artist"],
                        track_info["track"],
                    )
                    fetched_track = fetch_track(**track_info, timeout=timeout)
            else:
                logger.info(
                    "Fetching lyrics from LRCLIB for %s - %s",
                    track_info["artist"],
                    track_info["track"],
                )
                fetched_track = fetch_track(**track_info, timeout=timeout)

        if not fetched_track:
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

        download_lyrics(track, track_db_id)

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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(levelname)s:%(name)s] %(message)s",
    )
    return run_sync(args.music_dir, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
