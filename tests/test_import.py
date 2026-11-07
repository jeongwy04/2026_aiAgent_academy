import json
import uuid
from datetime import datetime

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.database import session_scope, set_user_context
from app.models import ImportEvidence, ImportJob, ListenEvent, Track


def activity(video="abcdefghijk", at="2025-01-01T00:00:00.123Z", **changes):
    return {"header": "YouTube Music", "title": "예시 곡 을(를) 시청했습니다.",
            "titleUrl": f"https://music.youtube.com/watch?v={video}", "time": at,
            "products": ["YouTube"], "subtitles": [{"name": "채널 이름", "url": "https://www.youtube.com/channel/example"}], **changes}


def upload(client, headers, rows):
    return client.post("/api/v1/imports", headers=headers,
                       files={"file": ("history.json", json.dumps(rows, ensure_ascii=False).encode(), "application/json")})


def test_import_batch_results_retry_stats_and_isolation(client, member):
    headers, user, _ = member()
    rows = [activity(), activity(video="abcdefghijl"), activity(header="YouTube"),
            activity(title="unrecognized"), activity(time="broken")]
    response = upload(client, headers, rows)
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["total"], result["accepted"], result["inserted"], result["duplicates"], result["excluded"], result["review"], result["errors"]) == (5, 2, 2, 0, 1, 1, 1)
    job_id = result["job_id"]
    assert client.get(f"/api/v1/imports/{job_id}", headers=headers).json()["result"] == result
    issues = client.get(f"/api/v1/imports/{job_id}/issues", headers=headers).json()
    assert issues["total"] == 2
    assert {i["status"] for i in issues["items"]} == {"review", "error"}
    first_tracks = client.get("/api/v1/tracks", headers=headers).json()
    assert first_tracks["total"] == 2
    track = first_tracks["items"][0]
    assert track["artist"] is None
    stats = client.get(f"/api/v1/tracks/{track['id']}/stats", headers=headers).json()
    assert stats["event_count"] == 1 and stats["total_listened_ms"] is None
    assert stats["unknown_duration_event_count"] == 1
    answer = client.post("/api/v1/chat", headers=headers,
        json={"question": "이 노래 총 재생 시간이 얼마야?", "track_id": track["id"]}).json()
    assert answer["status"] == "answered" and answer["total_listened_ms"] is None
    retry = upload(client, headers, rows).json()
    assert retry["inserted"] == 0 and retry["duplicates"] == 2 and retry["new_tracks"] == 0
    other, _, _ = member()
    for suffix in ("", "/issues"):
        assert client.get(f"/api/v1/imports/{job_id}{suffix}", headers=other).status_code == 404
    assert client.get("/api/v1/tracks", headers=other).json()["total"] == 0
    assert upload(client, other, rows).json()["inserted"] == 2


def test_overlap_repeat_occurrences_and_late_arrival(client, member):
    headers, _, _ = member()
    repeated = activity()
    result = upload(client, headers, [repeated, repeated]).json()
    assert result["inserted"] == 2  # Same-file multiplicity is preserved.
    retry = upload(client, headers, [repeated, repeated, activity(at="2024-01-01T00:00:00Z")]).json()
    assert (retry["inserted"], retry["duplicates"]) == (1, 2)
    track = client.get("/api/v1/tracks", headers=headers).json()["items"][0]
    stats = client.get(f"/api/v1/tracks/{track['id']}/stats", headers=headers).json()
    assert stats["event_count"] == 3 and stats["first_recorded_at"].startswith("2024-01-01")


def test_android_and_import_share_track_but_not_duration(client, member, make_event):
    headers, _, _ = member()
    assert upload(client, headers, [activity()]).json()["inserted"] == 1
    track = client.get("/api/v1/tracks", headers=headers).json()["items"][0]
    event = make_event(external_id="abcdefghijk", observed_at="2026-01-02T00:00:00Z", ms=45_000)
    assert client.post("/api/v1/listens/sync", headers=headers, json={"events": [event]}).status_code == 200
    assert client.get("/api/v1/tracks", headers=headers).json()["total"] == 1
    stats = client.get(f"/api/v1/tracks/{track['id']}/stats", headers=headers).json()
    assert (stats["event_count"], stats["total_listened_ms"], stats["measured_event_count"], stats["unknown_duration_event_count"]) == (2, 45_000, 1, 1)


def test_reupload_repairs_old_missing_artist_without_adding_listens(client, member):
    headers, user, _ = member()
    rows = [activity(title="Effie - Red Horse 을(를) 시청했습니다.", subtitles=[{"name": "Effie"}])]
    assert upload(client, headers, rows).json()["inserted"] == 1
    track = client.get("/api/v1/tracks", headers=headers).json()["items"][0]
    assert (track["title"], track["artist"]) == ("Red Horse", "Effie")
    # Model a track previously imported with parser 1.0.0.
    with session_scope(get_settings().database_url) as session:
        set_user_context(session, user["id"])
        old = session.get(Track, uuid.UUID(track["id"]))
        old.title = "Effie - Red Horse"
        old.artist = None
    retry = upload(client, headers, rows)
    assert retry.status_code == 200, retry.text
    result = retry.json()
    assert result["parser_version"] == "1.1.0"
    assert (result["inserted"], result["duplicates"], result["new_tracks"]) == (0, 1, 0)
    items = client.get("/api/v1/tracks?q=Effie", headers=headers).json()["items"]
    assert len(items) == 1
    assert (items[0]["id"], items[0]["title"], items[0]["artist"]) == (track["id"], "Red Horse", "Effie")
    stats = client.get(f"/api/v1/tracks/{track['id']}/stats", headers=headers).json()
    assert stats["event_count"] == 1 and stats["total_listened_ms"] is None


def test_import_preserves_existing_android_metadata(client, member, make_event):
    headers, _, _ = member()
    event = make_event(external_id="abcdefghijk", title="기기에서 받은 제목", artist="기기에서 받은 가수")
    assert client.post("/api/v1/listens/sync", headers=headers, json={"events": [event]}).status_code == 200
    response = upload(client, headers, [activity(title="Watched Export Title", subtitles=[{"name": "Export Artist - Topic"}])])
    assert response.status_code == 200, response.text
    assert response.json()["new_tracks"] == 0
    track = client.get("/api/v1/tracks", headers=headers).json()["items"][0]
    assert (track["title"], track["artist"]) == ("기기에서 받은 제목", "기기에서 받은 가수")


@pytest.mark.parametrize("batch_size", [1, 500])
@pytest.mark.parametrize("rich_first", [True, False])
def test_metadata_survives_other_occurrences_with_less_information(client, member, monkeypatch, batch_size, rich_first):
    headers, _, _ = member()
    monkeypatch.setenv("IMPORT_BATCH_SIZE", str(batch_size))
    get_settings.cache_clear()
    rich = activity(title="Watched More", subtitles=[{"name": "ILLIT - Topic"}])
    bare = activity(title="Watched More", at="2025-01-02T00:00:00Z", subtitles=[])
    response = upload(client, headers, [rich, bare] if rich_first else [bare, rich])
    assert response.status_code == 200, response.text
    assert response.json()["new_tracks"] == 1
    track = client.get("/api/v1/tracks", headers=headers).json()["items"][0]
    assert (track["title"], track["artist"]) == ("More", "ILLIT")


def test_storage_failure_rolls_back_every_data_batch(client, member, monkeypatch):
    from app.services import import_service
    headers, user, _ = member()
    monkeypatch.setenv("IMPORT_BATCH_SIZE", "1")
    get_settings.cache_clear()
    original = import_service._save_batch
    calls = []
    def fail_second(*args):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("simulated second batch failure")
        return original(*args)
    monkeypatch.setattr(import_service, "_save_batch", fail_second)
    response = upload(client, headers, [activity(), activity(video="abcdefghijl")])
    assert response.status_code == 503, response.text
    job_id = response.json()["job_id"]
    assert client.get(f"/api/v1/imports/{job_id}", headers=headers).json()["status"] == "failed"
    assert client.get("/api/v1/tracks", headers=headers).json()["total"] == 0
    with session_scope(get_settings().database_url) as session:
        set_user_context(session, user["id"])
        assert session.scalar(select(func.count()).select_from(ImportEvidence).where(ImportEvidence.user_id == uuid.UUID(user["id"]))) == 0
    monkeypatch.setattr(import_service, "_save_batch", original)
    assert upload(client, headers, [activity(), activity(video="abcdefghijl")]).json()["inserted"] == 2


def test_invalid_upload_no_job_and_auth_required(client, member):
    headers, user, _ = member()
    assert upload(client, {}, [activity()]).status_code == 401
    response = client.post("/api/v1/imports", headers=headers, files={"file": ("bad.json", b"[{", "application/json")})
    assert response.status_code == 422
    assert client.post("/api/v1/imports", headers=headers, files={"file": ("bad.txt", b"[]", "text/plain")}).status_code == 422
    with session_scope(get_settings().database_url) as session:
        set_user_context(session, user["id"])
        assert session.scalar(select(func.count()).select_from(ImportJob).where(ImportJob.user_id == uuid.UUID(user["id"]))) == 0


def test_import_upload_size_limit(client, member, monkeypatch):
    headers, _, _ = member()
    monkeypatch.setenv("IMPORT_UPLOAD_MAX_BYTES", "1024")
    get_settings.cache_clear()
    assert client.post("/api/v1/imports", headers=headers, files={"file": ("big.json", b" " * 2048, "application/json")}).status_code == 413
