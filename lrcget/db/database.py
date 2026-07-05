import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from lrcget.utils.types import (
    KnownTrackInfo,
    LrcGetResponse,
    MissingTrackLookupResult,
    TrackLookupResult,
    TrackRecord,
)

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "lrcget.db"


def get_connection():
    """Create and return a database connection"""
    try:
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        logger.debug("Connected to database: %s", DB_PATH)
        return con
    except sqlite3.Error:
        logger.error("Failed to connect to database: %s", DB_PATH, exc_info=True)
        raise


def init_db():
    """Initialise the database schema"""
    con = None

    try:
        logger.debug("Initialising database schema")
        con = get_connection()
        cur = con.cursor()

        cur.execute(
            """CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            remote_id INTEGER,
            remote_obj JSON,
            track TEXT NOT NULL,
            artist TEXT NOT NULL,
            album TEXT NOT NULL,
            duration FLOAT NOT NULL,
            synced_lyrics TEXT
        );"""
        )

        cur.execute(
            """CREATE TABLE IF NOT EXISTS missing_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            last_checked TEXT DEFAULT CURRENT_TIMESTAMP,
            track TEXT NOT NULL,
            artist TEXT NOT NULL,
            album TEXT NOT NULL,
            duration FLOAT NOT NULL,
            UNIQUE(track, artist, album, duration)
        );"""
        )

        con.commit()
        logger.debug("Database schema initialised")
    except sqlite3.Error as e:
        logger.critical("Failed to initialise database: %s", e, exc_info=True)
        raise
    finally:
        if con:
            con.close()


# ? feature: add metadata to the top of synced lyrics
# def create_synced_lyrics()


def write_track(
    fetched_track: LrcGetResponse,
    local_track: KnownTrackInfo,
    existing_id: int | None = None,
) -> int | None:
    """Write remote track data to the database and return the inserted record's id"""
    db = None

    try:
        db = get_connection()
        cur = db.cursor()

        if existing_id:
            cur.execute(
                """UPDATE tracks
                SET remote_id = ?,
                    remote_obj = ?,
                    synced_lyrics = ?
                WHERE id = ?""",
                (
                    fetched_track["id"],
                    json.dumps(fetched_track),
                    fetched_track["syncedLyrics"],
                    existing_id,
                ),
            )
            db.commit()

            if cur.rowcount != 1:
                logger.error(
                    "Failed to update expired track '%s - %s' for db id %s",
                    fetched_track["artistName"],
                    fetched_track["trackName"],
                    existing_id,
                )
                return None

            logger.info(
                "Refreshed track '%s - %s' at db id %s",
                fetched_track["artistName"],
                fetched_track["trackName"],
                existing_id,
            )
            return existing_id
        else:
            cur.execute(
                """INSERT INTO tracks (remote_id, remote_obj, track, artist, album, duration, synced_lyrics)
                VALUES(?, ?, ?, ?, ?, ?, ?)""",
                (
                    fetched_track["id"],
                    json.dumps(fetched_track),
                    local_track["track"],
                    local_track["artist"],
                    local_track["album"],
                    local_track["duration"],
                    fetched_track["syncedLyrics"],
                ),
            )

            db.commit()

            last_id = cur.lastrowid

            if not last_id:
                logger.error(
                    "Inserted track '%s - %s' has no row id",
                    fetched_track["artistName"],
                    fetched_track["trackName"],
                )
                return None

            logger.info(
                "Stored track '%s - %s' with db id %s",
                fetched_track["artistName"],
                fetched_track["trackName"],
                last_id,
            )

            return last_id
    except sqlite3.IntegrityError as e:
        logger.warning(
            "Integrity error while writing track '%s - %s': %s",
            local_track["artist"],
            local_track["track"],
            e,
        )
        return None
    except sqlite3.Error as e:
        logger.error(
            "Database error while writing track '%s - %s': %s",
            local_track["artist"],
            local_track["track"],
            e,
            exc_info=True,
        )
        return None
    finally:
        if db:
            db.close()


def read_track(
    track: str, artist: str, album: str, duration: float
) -> TrackLookupResult | None:
    db = None

    try:
        db = get_connection()
        cur = db.cursor()

        logger.debug(
            "Checking cached lyrics for %s - %s (%s)",
            artist,
            track,
            album,
        )

        cur.execute(
            "SELECT id, remote_obj FROM tracks WHERE track = ? AND artist = ? AND album = ? AND duration = ?",
            (track, artist, album, duration),
        )

        row: TrackRecord | None = cur.fetchone()

        if row:
            cached_track: LrcGetResponse = json.loads(row["remote_obj"])

            return {
                "id": row["id"],
                "remote_obj": cached_track,
            }

        logger.debug(
            "No cached track matching '%s - %s' on '%s' (%ss)",
            artist,
            track,
            album,
            duration,
        )
        return None

    except sqlite3.Error as e:
        logger.error(
            "Database read failed for '%s - %s' on '%s': %s",
            artist,
            track,
            album,
            e,
            exc_info=True,
        )
        raise
    finally:
        if db:
            db.close()


def read_missing_track(
    track: str, artist: str, album: str, duration: float
) -> MissingTrackLookupResult | None:
    """Read a known-missing track cache entry."""
    db = None

    try:
        db = get_connection()
        cur = db.cursor()

        cur.execute(
            "SELECT id, last_checked FROM missing_tracks WHERE track = ? AND artist = ? AND album = ? AND duration = ?",
            (track, artist, album, duration),
        )

        row = cur.fetchone()

        if not row:
            return None

        last_checked = datetime.fromisoformat(row["last_checked"])
        is_expired = datetime.now() - last_checked > timedelta(days=3)

        return {
            "id": row["id"],
            "is_expired": is_expired,
        }
    except sqlite3.Error as e:
        logger.error(
            "Database read failed for missing track '%s - %s' on '%s': %s",
            artist,
            track,
            album,
            e,
            exc_info=True,
        )
        raise
    finally:
        if db:
            db.close()


def write_missing_track(
    local_track: KnownTrackInfo, existing_id: int | None = None
) -> int | None:
    """Create or refresh a known-missing track cache entry."""
    db = None

    try:
        db = get_connection()
        cur = db.cursor()

        if existing_id:
            cur.execute(
                """UPDATE missing_tracks
                SET last_checked = CURRENT_TIMESTAMP
                WHERE id = ?""",
                (existing_id,),
            )

            db.commit()

            if cur.rowcount != 1:
                logger.error(
                    "Failed to refresh missing-track cache for %s - %s (id %s)",
                    local_track["artist"],
                    local_track["track"],
                    existing_id,
                )
                return None

            logger.info(
                "Refreshed missing-track cache for %s - %s (id %s)",
                local_track["artist"],
                local_track["track"],
                existing_id,
            )

            return existing_id

        cur.execute(
            """INSERT INTO missing_tracks (track, artist, album, duration)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(track, artist, album, duration)
            DO UPDATE SET last_checked = CURRENT_TIMESTAMP""",
            (
                local_track["track"],
                local_track["artist"],
                local_track["album"],
                local_track["duration"],
            ),
        )

        db.commit()

        cache_entry = read_missing_track(
            local_track["track"],
            local_track["artist"],
            local_track["album"],
            local_track["duration"],
        )
        if not cache_entry:
            return None

        logger.info(
            "Stored missing-track cache for %s - %s (id %s)",
            local_track["artist"],
            local_track["track"],
            cache_entry["id"],
        )

        return cache_entry["id"]
    except sqlite3.Error as e:
        logger.error(
            "Database error while writing missing-track cache for '%s - %s': %s",
            local_track["artist"],
            local_track["track"],
            e,
            exc_info=True,
        )
        return None
    finally:
        if db:
            db.close()


def delete_missing_track(track: str, artist: str, album: str, duration: float) -> None:
    """Remove known-missing cache entry once lyrics are available."""
    db = None

    try:
        db = get_connection()
        cur = db.cursor()
        cur.execute(
            "DELETE FROM missing_tracks WHERE track = ? AND artist = ? AND album = ? AND duration = ?",
            (track, artist, album, duration),
        )
        db.commit()
    except sqlite3.Error as e:
        logger.error(
            "Failed to delete missing-track cache for '%s - %s': %s",
            artist,
            track,
            e,
            exc_info=True,
        )
    finally:
        if db:
            db.close()
