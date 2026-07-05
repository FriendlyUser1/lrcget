from typing import TypedDict


class LrcGetResponse(TypedDict):
    id: int
    name: str | None
    trackName: str
    artistName: str
    albumName: str
    duration: float
    instrumental: bool
    plainLyrics: str | None
    syncedLyrics: str | None
    lyricsfile: str | None


class TrackRecord(TypedDict):
    id: int
    remote_id: int
    remote_obj: str
    track: str
    artist: str
    album: str
    duration: float
    synced_lyrics: str | None


class KnownTrackInfo(TypedDict):
    track: str
    artist: str
    album: str
    duration: float


class TrackInfo(TypedDict):
    file: str
    track: str | None
    artist: str | None
    album: str | None
    duration: float | None


def coerceTrackInfo(track_info: TrackInfo) -> KnownTrackInfo | None:
    if (
        track_info["track"] is None
        or track_info["artist"] is None
        or track_info["album"] is None
        or track_info["duration"] is None
    ):
        return None

    return KnownTrackInfo(
        track=track_info["track"],
        artist=track_info["artist"],
        album=track_info["album"],
        duration=track_info["duration"],
    )


class TrackLookupResult(TypedDict):
    id: int
    remote_obj: LrcGetResponse


class MissingTrackLookupResult(TypedDict):
    id: int
    is_expired: bool
