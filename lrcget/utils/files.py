import json
import logging
import math
import sqlite3
from pathlib import Path
from typing import List

from mutagen import File, MutagenError  # pyright: ignore[reportPrivateImportUsage]

from lrcget.db.database import get_connection

from lrcget.utils.types import KnownTrackInfo, TrackInfo

logger = logging.getLogger(__name__)

DEFAULT_AUDIO_EXTS = [".mp3", ".opus", ".flac", ".ogg", ".wav"]


def _first_non_empty_string(value: object) -> str | None:
    """Extract the first non-empty string from mutagen tag values"""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None

    if isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, str):
                stripped = item.strip()
                if stripped:
                    return stripped

    text_attr = getattr(value, "text", None)
    if isinstance(text_attr, str):
        stripped = text_attr.strip()
        return stripped or None

    if isinstance(text_attr, (list, tuple)):
        for item in text_attr:
            if isinstance(item, str):
                stripped = item.strip()
                if stripped:
                    return stripped

    return None


def _extract_tag_value(mut: object, keys: list[str]) -> str | None:
    """Try multiple tag keys and return the first valid string"""
    for key in keys:
        try:
            raw = mut[key]  # pyright: ignore[reportIndexIssue]
        except (KeyError, TypeError, AttributeError):
            continue

        parsed = _first_non_empty_string(raw)
        if parsed:
            return parsed

    return None


def get_tracks(music_dir: Path, audio_exts: list[str] | None = None) -> List[Path]:
    """Get the list of audio files in the given directory"""
    selected_exts = {
        ext.lower() if ext.startswith(".") else f".{ext.lower()}"
        for ext in (audio_exts or DEFAULT_AUDIO_EXTS)
        if ext
    }
    track_list: List[Path] = []

    logger.info(
        "Scanning for audio files under %s with extensions: %s",
        music_dir,
        ",".join(sorted(selected_exts)),
    )

    for walk in music_dir.walk():
        for file_name in walk[2]:
            file = walk[0] / file_name
            if file.suffix.lower() in selected_exts:
                track_list.append(file)

    logger.info("Found %s audio files", len(track_list))
    return track_list


def get_track_info(track: Path) -> TrackInfo | None:
    """Read metadata from a local audio file"""
    # tag types
    # mp3: ID3
    # wav: ID3
    # opus: VCommentDict
    # flac: VCommentDict
    #  ogg: VCommentDict

    try:
        logger.debug("Loading metadata for %s", track.name)
        mut = File(track)
    except MutagenError as e:
        logger.error("Error reading file %s: %s", track.name, e)
        return None

    if not mut or not mut.info or not mut.tags:
        logger.error("Error reading metadata of %s", track.name)
        return None

    logger.debug(
        "Loaded metadata for %s %s",
        track.name,
        mut.info,
    )

    # TODO consider sorting by mutagen's deciphered filetype instead of file extensions
    if track.suffix.lower() in [".mp3", ".wav"]:
        # ID3 https://id3.org/id3v2.4.0-frames
        # track: TIT2
        # album: TALB
        # artist: TPE1 (TPE1-4)
        track_name = _extract_tag_value(mut, ["TIT2"])
        artist_name = _extract_tag_value(mut, ["TPE1", "TPE2", "TOPE", "TPE3", "TPE4"])
        album_name = _extract_tag_value(mut, ["TALB"])
    else:
        # vorbis comment dict
        track_name = _extract_tag_value(mut, ["title", "TITLE"])
        artist_name = _extract_tag_value(mut, ["artist", "ARTIST"])
        album_name = _extract_tag_value(mut, ["album", "ALBUM"])

    # if not track_name or not artist_name or not album_name:
    #     logger.info("Skipping %s: required tags missing.", track.name)
    #     return None

    raw_length = getattr(mut.info, "length", None)
    # if not isinstance(raw_length, (int, float)):
    #     logger.info("Skipping %s: invalid track length.", track.name)
    #     return None

    length = round(float(raw_length), 2) if raw_length else None
    # if not math.isfinite(length) or length <= 0:
    #     logger.info("Skipping %s: non-positive track length.", track.name)
    #     return None

    track_info: TrackInfo = {
        "file": track.stem,
        "track": track_name,
        "artist": artist_name,
        "album": album_name,
        "duration": length,
    }

    logger.debug(
        "Loaded track metadata: file=%s, track=%s artist=%s album=%s duration=%ss",
        track_info["file"],
        track_info["track"],
        track_info["artist"],
        track_info["album"],
        track_info["duration"],
    )

    return track_info


def download_lyrics(track: Path, track_db_id: int, is_cached: bool = False):
    """Download synced lyrics (.lrc) next to the audio file"""
    if is_cached:
        logger.debug(
            "Skipping lyrics write for %s because cached lyrics are in use",
            track,
        )
        return

    db = None

    try:
        db = get_connection()
        cur = db.cursor()

        cur.execute(
            "SELECT synced_lyrics, remote_obj FROM tracks WHERE id = ?",
            (track_db_id,),
        )
        row = cur.fetchone()

        if not row:
            logger.error("No database record found for track id %s", track_db_id)
            return

        synced_lyrics = row["synced_lyrics"]

        if not synced_lyrics:
            remote_obj_raw = row["remote_obj"]
            if isinstance(remote_obj_raw, str):
                try:
                    remote_obj = json.loads(remote_obj_raw)
                    synced_lyrics = remote_obj.get("syncedLyrics")
                except json.JSONDecodeError:
                    logger.error(
                        "Invalid JSON in remote_obj for track id %s",
                        track_db_id,
                    )

        if not synced_lyrics:
            logger.info("No synced lyrics available for track id %s", track_db_id)
            return

        lrc_path = track.with_suffix(".lrc")

        if lrc_path.exists():
            try:
                existing_lyrics = lrc_path.read_text(encoding="utf-8")
            except OSError as e:
                logger.warning(
                    "Failed to read existing lyrics file at %s before update: %s",
                    lrc_path,
                    e,
                )
            else:
                if existing_lyrics == synced_lyrics:
                    logger.debug(
                        "Skipping lyrics write for %s because lyrics are unchanged",
                        lrc_path,
                    )
                    return

        lrc_path.write_text(synced_lyrics, encoding="utf-8")
        logger.info("Wrote synced lyrics to %s", lrc_path)

    except sqlite3.Error as e:
        logger.error(
            "Database error while downloading lyrics for id %s: %s",
            track_db_id,
            e,
            exc_info=True,
        )
    except OSError as e:
        logger.error(
            "Failed to write lyrics file for %s: %s",
            track,
            e,
            exc_info=True,
        )
    finally:
        if db:
            db.close()
