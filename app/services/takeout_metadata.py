"""Conservative display metadata from Takeout titles and channel hints.

Channel names describe uploaders, so a plain channel name alone is insufficient.
These are export-derived hints, not a verified music catalog or identity lookup.
"""
import re

from app.utils import normalized


TOPIC = re.compile(r"\s+-\s+Topic\s*$", re.IGNORECASE)
SEPARATOR = re.compile(r"\s+[-–—]\s+")
VIDEO_SUFFIX = re.compile(
    r"\s*(?:\((?:Official(?:\s+(?:Music|MacBook))?\s+(?:Video|Audio)|M/V|MV)\)"
    r"|(?:OFFICIAL\s+)?(?:M/V|MV)\.?)(?:\s+with\b.*)?\s*$", re.IGNORECASE,
)
AMBIGUOUS = re.compile(r"\b(?:cover|remix|mashup|guide)\b|커버|리믹스|매시업|가이드", re.IGNORECASE)
QUOTES = (("'", "'"), ('"', '"'), ("‘", "’"), ("“", "”"))


def _song(value: str) -> str:
    value = VIDEO_SUFFIX.sub("", value).strip()
    for left, right in QUOTES:
        if value.startswith(left) and value.endswith(right):
            return value[1:-1].strip()
    return value


def extract_metadata(title: str, channels: list[dict]) -> dict:
    """Keep the original title and a missing artist whenever attribution is unclear."""
    fallback = {"display_title": title, "artist": None, "metadata_basis": None}
    names = {normalized(c["name"]): c["name"].strip()
             for c in channels if c.get("name", "").strip()}
    parts = SEPARATOR.split(title, maxsplit=1)

    def found(song, artist, basis):
        song, artist = song.strip(), artist.strip()
        if not song or not artist or len(song) > 300 or len(artist) > 300:
            return fallback
        return {"display_title": song, "artist": artist, "metadata_basis": basis}

    if len(names) == 1:
        channel = next(iter(names.values()))
        if TOPIC.search(channel):
            artist = TOPIC.sub("", channel).strip()
            song = title
            if len(parts) == 2:
                if normalized(parts[0]) == normalized(artist):
                    song = _song(parts[1])
                elif normalized(parts[1]) == normalized(artist):
                    song = _song(parts[0])
            return found(song, artist, "topic_channel")

    # A remix/cover uploader and the named original performer need not be the same artist.
    if AMBIGUOUS.search(title):
        return fallback

    if len(names) == 1 and len(parts) == 2:
        channel = next(iter(names))
        if normalized(parts[0]) == channel:
            return found(_song(parts[1]), parts[0], "title_and_channel")
        if normalized(parts[1]) == channel:
            return found(_song(parts[0]), parts[1], "title_and_channel")

    # Label-uploaded music videos often spell out Artist 'Song' MV in the title.
    for left, right in QUOTES:
        match = re.fullmatch(
            rf"(.+?)\s+{re.escape(left)}(.+?){re.escape(right)}\s+"
            r"(?:OFFICIAL\s+)?(?:M/V|MV|MUSIC VIDEO)(?:\s+with\b.*)?",
            title, re.IGNORECASE,
        )
        if match:
            artist = re.sub(r"\s+[-–—]$", "", match[1]).strip()
            if not artist.startswith("["):
                return found(match[2], artist, "quoted_music_video_title")
    return fallback
