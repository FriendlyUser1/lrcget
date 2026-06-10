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
    last_checked: str
    track: str
    artist: str
    album: str
    duration: float
    synced_lyrics: str | None


class TrackInfo(TypedDict):
    track: str
    artist: str
    album: str
    duration: float


class TrackLookupResult(TypedDict):
    id: int
    remote_obj: LrcGetResponse
    is_expired: bool
