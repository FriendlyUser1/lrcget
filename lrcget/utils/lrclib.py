# LRCLIB API interface
import json
import logging
from typing import List

import requests

from lrcget.utils.types import LrcGetResponse

logger = logging.getLogger(__name__)

BASE_URL = "https://lrclib.net/api"
HEADERS = {
    "user-agent": "LRCGET v0.2.0 (https://github.com/FriendlyUser1/lrcget)",
    "accept": "application/json",
}


class LrclibError(Exception):
    """LRCLIB API base exception"""

    pass


class TrackNotFoundError(LrclibError):
    """Track does not exist"""

    pass


class LrclibTimeoutError(LrclibError):
    """LRCLIB request timed out"""

    pass


def fetch_track(
    track: str, artist: str, album: str, duration: float, timeout: int
) -> LrcGetResponse | None:
    """Fetch lyrics from LRCLIB"""
    logger.debug("Requesting lyrics for %s - %s", artist, track)
    try:
        result = lrclib_get(track, artist, album, duration, timeout)
        logger.debug("Received lyrics for %s - %s", artist, track)
        return result
    except requests.Timeout as e:
        logger.warning(
            "LRCLIB request timed out after %ss for %s - %s",
            timeout,
            artist,
            track,
        )
        raise LrclibTimeoutError(
            "Timed out fetching lyrics for '%s - %s'" % (artist, track)
        ) from e
    except requests.RequestException as e:
        logger.error(
            "LRCLIB request failed for %s - %s: %s",
            artist,
            track,
            e,
            exc_info=True,
        )
    except LrclibError as e:
        logger.error("LRCLIB response error for %s - %s: %s", artist, track, e)
        if isinstance(e, TrackNotFoundError):
            raise

    return None


def search_track(
    file: str,
    timeout: int,
    track: str | None = None,
    artist: str | None = None,
    album: str | None = None,
) -> List[LrcGetResponse] | None:
    """Search for lyrics from LRCLIB"""
    logger.debug(
        "Searching for lyrics for %s - %s (file: %s)",
        artist,
        track,
        file,
    )
    try:
        result = lrclib_search(file, timeout, track, artist, album)
        logger.debug("Received search results for %s - %s", artist, track)
        return result
    except requests.Timeout as e:
        logger.warning(
            "LRCLIB search request timed out after %ss for %s - %s",
            timeout,
            artist,
            track,
        )
        raise LrclibTimeoutError(
            "Timed out searching for lyrics for '%s - %s'" % (artist, track)
        ) from e
    except requests.RequestException as e:
        logger.error(
            "LRCLIB search request failed for %s - %s: %s",
            artist,
            track,
            e,
            exc_info=True,
        )
    except LrclibError as e:
        logger.error("LRCLIB search response error for %s - %s: %s", artist, track, e)
        if isinstance(e, TrackNotFoundError):
            raise

    return None


def lrclib_get(
    track: str, artist: str, album: str, length: float, timeout: int
) -> LrcGetResponse:
    """Get lyrics by specifics from LRCLIB

    Args:
        track (str): Track name
        artist (str): Artist name
        album (str): Album name
        length (float): Track length in seconds
        timeout (int): Request timeout in seconds

    Raises:
        TrackNotFoundError: Track not found
        requests.RequestException: Network errors
        LrclibError: API errors

    Returns:
        LrcGetResponse | None: Successful response or None
    """

    params = {
        "track_name": track,
        "artist_name": artist,
        "album_name": album,
        "duration": length,
    }

    logger.debug("Calling LRCLIB /get with params: %s", params)

    res = requests.get(
        f"{BASE_URL}/get", params=params, headers=HEADERS, timeout=timeout
    )

    logger.debug("LRCLIB response status: %s", res.status_code)

    if res.status_code == 404:
        raise TrackNotFoundError("Track not found: '%s - %s'" % (artist, track))

    res.raise_for_status()

    try:
        data = res.json()
    except requests.exceptions.JSONDecodeError as e:
        logger.error("LRCLIB returned invalid JSON for %s - %s", artist, track)
        raise LrclibError(f"Invalid JSON response from API: {res.text}") from e

    logger.debug("LRCLIB payload keys: %s", sorted(data.keys()))

    return LrcGetResponse(**data)


def lrclib_search(
    file: str,
    timeout: int,
    track: str | None = None,
    artist: str | None = None,
    album: str | None = None,
) -> List[LrcGetResponse] | None:
    """Get less strict matching lyrics from LRCLIB

    Args:
        file (str): Track file name
        timeout (int): Request timeout in seconds
        track (str | None, optional): Track name. Defaults to None.
        artist (str | None, optional): Artist name. Defaults to None.
        album (str | None, optional): Album name. Defaults to None.
    Raises:
        TrackNotFoundError: Track not found
        requests.RequestException: Network errors
        LrclibError: API errors

    Returns:
        LrcSearchResponse | None: Successful response or None
    """

    if not track:
        params = {"q": file}
    else:
        params = {"track_name": track}
        if artist:
            params["artist_name"] = artist
        if album:
            params["album_name"] = album

    logger.debug("Calling LRCLIB /search with params: %s", params)

    res = requests.get(
        f"{BASE_URL}/search", params=params, headers=HEADERS, timeout=timeout
    )

    logger.debug("LRCLIB response status: %s", res.status_code)

    if res.status_code == 404:
        raise TrackNotFoundError("Track not found: '%s - %s'" % (artist, track))

    res.raise_for_status()

    try:
        data = res.json()
    except requests.exceptions.JSONDecodeError as e:
        logger.error("LRCLIB returned invalid JSON for %s - %s", artist, track)
        raise LrclibError(f"Invalid JSON response from API: {res.text}") from e

    return data
