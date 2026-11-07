from __future__ import annotations

import hashlib
import json
import re
import tempfile
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

PARSER_VERSION = "1.0.0"
SOURCE = "google_takeout_my_activity"
DEFAULT_MAX_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_ITEMS = 500_000
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)
YOUTUBE_HOSTS = {"music.youtube.com", "www.youtube.com", "youtube.com", "m.youtube.com"}


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON property: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f"Non-standard JSON constant: {value}")


def load_records(input_path: str | Path, member: str | None = None,
                 max_bytes: int = DEFAULT_MAX_BYTES,
                 max_items: int = DEFAULT_MAX_ITEMS) -> tuple[list, dict]:
    """Bounded whole-document loader. ZIP content is read without extraction."""
    if max_bytes <= 0 or max_items <= 0:
        raise ValueError("Limits must be positive")
    input_path = Path(input_path)
    if input_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(input_path) as archive:
            candidates = [e for e in archive.infolist()
                          if not e.is_dir() and e.filename.lower().endswith(".json")]
            if member is not None:
                candidates = [e for e in candidates if e.filename == member]
            if len(candidates) != 1:
                raise ValueError("Expected exactly one JSON member; select it with --member")
            entry = candidates[0]
            if entry.file_size > max_bytes:
                raise ValueError("Uncompressed JSON exceeds byte limit")
            with archive.open(entry) as stream:
                payload = stream.read(max_bytes + 1)
            member_name = entry.filename
    elif input_path.suffix.lower() == ".json":
        if member is not None:
            raise ValueError("--member is only supported for ZIP input")
        if input_path.stat().st_size > max_bytes:
            raise ValueError("JSON exceeds byte limit")
        with input_path.open("rb") as stream:
            payload = stream.read(max_bytes + 1)
        member_name = None
    else:
        raise ValueError("Only .zip and .json are supported")
    if len(payload) > max_bytes:
        raise ValueError("JSON exceeds byte limit")
    records = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_unique_keys,
                         parse_constant=_invalid_constant)
    if not isinstance(records, list):
        raise ValueError("Top-level JSON must be an array")
    if len(records) > max_items:
        raise ValueError("JSON exceeds item limit")
    metadata = {
        "input_name": input_path.name,
        "member": member_name,
        "json_sha256": hashlib.sha256(payload).hexdigest(),
        "json_bytes": len(payload),
    }
    return records, metadata


def _result(status: str, reason: str, **kwargs) -> dict:
    return {"status": status, "reason": reason, **kwargs}


def _display_title(raw: str) -> str | None:
    if raw.startswith("Watched "):
        return raw[len("Watched "):].strip() or None
    match = re.fullmatch(r"(.+?)\s*을\(를\)\s*(?:시청|감상)했습니다\.?", raw)
    return match.group(1).strip() if match else None


def classify(record: object) -> dict:
    """Return exactly one status: accepted, excluded, review, or error.

    No mutation, network request, database write, or approximate matching.
    """
    if not isinstance(record, dict):
        return _result("error", "record_not_object")
    header = record.get("header")
    if not isinstance(header, str) or not header.strip():
        return _result("error", "missing_or_invalid_header")
    if header != "YouTube Music":
        return _result("excluded", "not_youtube_music")

    raw_url = record.get("titleUrl")
    if raw_url is None or raw_url == "":
        return _result("review", "missing_url")
    if not isinstance(raw_url, str) or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in raw_url):
        return _result("error", "invalid_url")
    try:
        url = urlsplit(raw_url)
        if (url.scheme != "https" or url.hostname not in YOUTUBE_HOSTS
                or url.username is not None or url.password is not None
                or url.port not in (None, 443)):
            return _result("review", "unsupported_url")
    except ValueError:
        return _result("error", "invalid_url")

    if url.path == "/results":
        return _result("excluded", "search_activity")
    if url.path == "/playlist":
        return _result("excluded", "playlist_activity")
    if url.path != "/watch":
        return _result("review", "unsupported_activity_path")
    if url.hostname != "music.youtube.com":
        return _result("review", "watch_host_needs_review")
    try:
        query = parse_qs(url.query, keep_blank_values=True, max_num_fields=100)
    except ValueError:
        return _result("error", "invalid_query")
    ids = query.get("v", [])
    if len(ids) != 1 or not VIDEO_ID.fullmatch(ids[0]):
        return _result("error", "missing_or_invalid_video_id")

    raw_time = record.get("time")
    if not isinstance(raw_time, str) or not TIMESTAMP.fullmatch(raw_time):
        return _result("error", "missing_or_invalid_time")
    if raw_time[-1] != "Z" and (int(raw_time[-5:-3]) > 23 or int(raw_time[-2:]) > 59):
        return _result("error", "missing_or_invalid_time")
    try:
        at = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        if at.utcoffset() is None:
            raise ValueError("Missing offset")
        utc = at.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (ValueError, OverflowError):
        return _result("error", "missing_or_invalid_time")

    raw_title = record.get("title")
    if not isinstance(raw_title, str) or not raw_title.strip():
        return _result("review", "missing_title")
    title = _display_title(raw_title.strip())
    if not title:
        return _result("review", "unrecognized_action_title", video_id=ids[0], played_at=utc)

    # Channel metadata is not a verified artist identity.
    subtitles = record.get("subtitles", [])
    if not isinstance(subtitles, list) or any(
        not isinstance(s, dict)
        or ("name" in s and not isinstance(s["name"], str))
        or ("url" in s and not isinstance(s["url"], str))
        for s in subtitles
    ):
        return _result("review", "invalid_channel_metadata")
    channels = [{k: s[k] for k in ("name", "url") if k in s} for s in subtitles]
    key_payload = json.dumps([SOURCE, ids[0], utc], ensure_ascii=False, separators=(",", ":"))
    return _result("accepted", "validated_music_watch", event={
        "source": SOURCE,
        "provider": "youtube",
        "external_id": ids[0],
        "played_at": utc,
        "source_time": raw_time,
        "source_event_key": hashlib.sha256(key_payload.encode("utf-8")).hexdigest(),
        "raw_title": raw_title,
        "display_title": title,
        "source_url": raw_url,
        "channels": channels,
        "listened_ms": None,
        "qualified": None,
    })


def _write_line(stream, record):
    stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_import(input_path: str | Path, output_dir: str | Path, *,
               member: str | None = None, max_bytes: int = DEFAULT_MAX_BYTES,
               max_items: int = DEFAULT_MAX_ITEMS) -> dict:
    """Validate the input and publish a new output directory only on success."""
    output_dir = Path(output_dir).absolute()
    if output_dir.exists():
        raise FileExistsError("Output directory already exists; select a new directory")
    records, metadata = load_records(input_path, member, max_bytes, max_items)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    counts = Counter({"accepted": 0, "excluded": 0, "review": 0, "error": 0})
    reasons = {name: Counter() for name in counts}
    keys = Counter()
    unique_videos = set()
    with tempfile.TemporaryDirectory(prefix=".takeout-filter-", dir=output_dir.parent) as tmp:
        staging = Path(tmp) / "result"
        staging.mkdir()
        handles = {s: (staging / name).open("w", encoding="utf-8", newline="\n") for s, name in (
            ("accepted", "accepted.jsonl"), ("review", "review.jsonl"), ("error", "errors.jsonl"))}
        try:
            for index, record in enumerate(records):
                result = classify(record)
                status = result["status"]
                counts[status] += 1
                reasons[status][result["reason"]] += 1
                if status == "accepted":
                    event = result["event"]
                    keys[event["source_event_key"]] += 1
                    unique_videos.add(event["external_id"])
                    _write_line(handles[status], {"source_index": index, **event})
                elif status in handles:
                    # Only anomalous music candidates / invalid records retain their source.
                    _write_line(handles[status], {"source_index": index, **result, "record": record})
        finally:
            for handle in handles.values():
                handle.close()
        assert sum(counts.values()) == len(records)
        summary = {
            "complete": True, "parser_version": PARSER_VERSION, **metadata,
            "total": len(records), "counts": dict(counts),
            "reasons": {k: dict(v) for k, v in reasons.items()},
            "unique_accepted_video_ids": len(unique_videos),
            "repeated_accepted_event_keys": sum(n - 1 for n in keys.values()),
            "deduplication_applied": False,
            "scope": "filter_and_validation_only",
        }
        (staging / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        staging.rename(output_dir)
    return summary
