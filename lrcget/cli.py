import argparse
import logging
import pathlib

from lrcget.db.database import init_db, read_track, write_track
from lrcget.utils.files import download_lyrics, get_track_info, get_tracks
from lrcget.utils.lrclib import fetch_track

logger = logging.getLogger(__name__)


def run_sync(music_dir: str) -> int:
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

        track_lookup = read_track(**track_info)

        if track_lookup and not track_lookup["is_expired"]:
            fetched_track = track_lookup["remote_obj"]
            track_db_id = track_lookup["id"]
            logger.info(
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
            fetched_track = fetch_track(**track_info)

        if not fetched_track:
            logger.warning(
                "No lyrics available for %s - %s",
                track_info["artist"],
                track_info["track"],
            )
            continue

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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(levelname)s:%(name)s] %(message)s",
    )
    return run_sync(args.music_dir)


if __name__ == "__main__":
    raise SystemExit(main())
