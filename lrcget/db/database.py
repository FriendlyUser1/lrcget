import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from lrcget.utils.types import LrcGetResponse, TrackInfo, TrackLookupResult, TrackRecord

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
            remote_id INTEGER NOT NULL,
            remote_obj JSON NOT NULL,
            last_checked TEXT DEFAULT CURRENT_TIMESTAMP,
            track TEXT NOT NULL,
            artist TEXT NOT NULL,
            album TEXT NOT NULL,
            duration FLOAT NOT NULL,
            synced_lyrics TEXT
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
    local_track: TrackInfo,
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
                    last_checked = CURRENT_TIMESTAMP,
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
            "SELECT * FROM tracks WHERE track = ? AND artist = ? AND album = ? AND duration = ?",
            (track, artist, album, duration),
        )

        row: TrackRecord | None = cur.fetchone()

        if row:
            row_id = row["id"]
            last_checked = datetime.fromisoformat(row["last_checked"])
            update_due = datetime.now() - last_checked > timedelta(days=3)

            cached_track: LrcGetResponse = json.loads(row["remote_obj"])

            if update_due and not row["synced_lyrics"]:
                logger.info(
                    "Cache expired for %s - %s; caller should refresh",
                    artist,
                    track,
                )

            return {
                "id": row_id,
                "remote_obj": cached_track,
                "is_expired": update_due,
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
