"""Synchronous MVP import: batched statements, one atomic data transaction.

No LLM calls. Same-user imports serialize in PostgreSQL. Each upload retains
its provenance, while repeated events are not counted again.
"""
import hashlib
import json
import uuid
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import session_scope, set_user_context
from app.models import ImportEvidence, ImportIssue, ImportJob, ListenEvent, Track, utcnow
from app.schemas.import_job import ImportSummary
from app.services.listen_service import insert_for
from app.services.takeout_filter import PARSER_VERSION, classify, load_records

EVENT_NAMESPACE = uuid.UUID("1227412e-a27a-4b07-a2ce-bca59fc81294")
BATCH_SIZE = 500


class ImportStoreError(RuntimeError):
    def __init__(self, job_id):
        self.job_id = job_id
        super().__init__("Import transaction failed")


def _chunks(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _track_key(external_id):
    # Same identity as Android's source_key for an explicit external ID.
    return hashlib.sha256(json.dumps(["youtube_music", "id", external_id], ensure_ascii=False).encode()).hexdigest()


def prepare_import(path: str | Path, member: str | None = None):
    records, metadata = load_records(path, member)
    counts = Counter({"accepted": 0, "excluded": 0, "review": 0, "error": 0})
    reasons = {s: Counter() for s in counts}
    accepted, issues = [], []
    occurrences = Counter()
    for index, record in enumerate(records):
        result = classify(record)
        if result["status"] == "accepted":
            event = result["event"]
            if len(event["display_title"]) > 300:
                result = {"status": "review", "reason": "title_exceeds_database_limit"}
            elif datetime.fromisoformat(event["played_at"].replace("Z", "+00:00")) > utcnow() + timedelta(minutes=5):
                result = {"status": "error", "reason": "future_activity_time"}
        status = result["status"]
        counts[status] += 1
        reasons[status][result["reason"]] += 1
        if status == "accepted":
            event = result["event"]
            occurrences[event["source_event_key"]] += 1
            accepted.append({"index": index, "event": event, "raw": record,
                             "occurrence": occurrences[event["source_event_key"]]})
        elif status in ("review", "error"):
            issues.append({"source_index": index, "status": status, "reason": result["reason"], "raw_record": record})
    return metadata, counts, reasons, accepted, issues


def _save_batch(session: Session, user_id: uuid.UUID, job_id: uuid.UUID, batch: list) -> tuple[int, int]:
    identities = {_track_key(item["event"]["external_id"]): item["event"] for item in batch}
    track_rows = [{"id": uuid.uuid4(), "user_id": user_id, "source_key": key,
                   "external_id": event["external_id"], "title": event["display_title"],
                   "artist": None, "album": None, "created_at": utcnow()} for key, event in identities.items()]
    created = session.execute(insert_for(session, Track).values(track_rows).on_conflict_do_nothing(
        index_elements=[Track.user_id, Track.source_key]).returning(Track.id)).scalars().all()
    tracks = dict(session.execute(select(Track.source_key, Track.id).where(
        Track.user_id == user_id, Track.source_key.in_(identities))).all())
    events = []
    for item in batch:
        e = item["event"]
        events.append({"user_id": user_id,
            "event_id": uuid.uuid5(EVENT_NAMESPACE, f"{user_id}:{e['source_event_key']}:{item['occurrence']}"),
            "track_id": tracks[_track_key(e["external_id"])],
            "observed_at": datetime.fromisoformat(e["played_at"].replace("Z", "+00:00")),
            "listened_ms": None, "source": e["source"], "source_event_key": e["source_event_key"],
            "occurrence_no": item["occurrence"], "updated_at": utcnow()})
    inserted = session.execute(insert_for(session, ListenEvent).values(events).on_conflict_do_nothing()
                               .returning(ListenEvent.event_id)).scalars().all()
    # Catch a client-forged Android UUID collision instead of silently treating
    # an unrelated existing event as the imported one.
    actual = {e.event_id: e for e in session.scalars(select(ListenEvent).where(
        ListenEvent.user_id == user_id, ListenEvent.event_id.in_([e["event_id"] for e in events])))}
    for expected in events:
        stored = actual.get(expected["event_id"])
        if stored is None or stored.source != expected["source"] or stored.track_id != expected["track_id"] or stored.source_event_key != expected["source_event_key"] or stored.occurrence_no != expected["occurrence_no"]:
            raise HTTPException(409, "청취 이벤트 식별자가 충돌했습니다. 가져오기가 취소되었습니다.")
    session.execute(insert_for(session, ImportEvidence).values([
        {"user_id": user_id, "job_id": job_id, "source_index": item["index"],
         "event_id": event["event_id"], "raw_record": item["raw"]}
        for item, event in zip(batch, events)
    ]))
    return len(inserted), len(created)


def import_takeout(user_id: uuid.UUID, path: str | Path, *, member: str | None = None,
                   batch_size: int = BATCH_SIZE) -> ImportSummary:
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    # Parse before creating a job or taking a DB lock. No original file persists.
    metadata, counts, reasons, accepted, issues = prepare_import(path, member)
    url = get_settings().database_url
    job_id = uuid.uuid4()
    with session_scope(url) as session:
        set_user_context(session, str(user_id))
        session.add(ImportJob(id=job_id, user_id=user_id, json_sha256=metadata["json_sha256"],
                            parser_version=PARSER_VERSION, status="processing", created_at=utcnow()))
    try:
        with session_scope(url) as session:
            set_user_context(session, str(user_id))
            if session.bind.dialect.name == "postgresql":
                lock_key = int.from_bytes(hashlib.sha256(user_id.bytes).digest()[:8], "big", signed=True)
                if not session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": lock_key}):
                    raise HTTPException(409, "이미 다른 가져오기를 처리 중입니다. 완료 후 다시 시도해 주세요.")
            inserted = new_tracks = 0
            for batch in _chunks(accepted, batch_size):
                added, new = _save_batch(session, user_id, job_id, batch)
                inserted += added
                new_tracks += new
            for batch in _chunks(issues, batch_size):
                session.execute(insert_for(session, ImportIssue).values([
                    {"user_id": user_id, "job_id": job_id, **issue} for issue in batch]))
            result = ImportSummary(job_id=job_id, parser_version=PARSER_VERSION,
                json_sha256=metadata["json_sha256"], total=sum(counts.values()),
                accepted=counts["accepted"], inserted=inserted, duplicates=counts["accepted"] - inserted,
                excluded=counts["excluded"], review=counts["review"], errors=counts["error"],
                new_tracks=new_tracks, distinct_tracks=len({r["event"]["external_id"] for r in accepted}),
                reasons={k: dict(v) for k, v in reasons.items()})
            assert result.total == result.inserted + result.duplicates + result.excluded + result.review + result.errors
            job = session.get(ImportJob, job_id)
            job.status = "completed"
            job.result = result.model_dump(mode="json")
            job.completed_at = utcnow()
        # The data transaction commits before the caller can return success.
        return result
    except Exception as error:
        try:
            with session_scope(url) as session:
                set_user_context(session, str(user_id))
                job = session.get(ImportJob, job_id)
                if job is not None and job.status != "completed":
                    job.status = "failed"
                    job.error_code = "conflict" if isinstance(error, HTTPException) else "storage_failure"
                    job.completed_at = utcnow()
        except Exception:
            pass  # Original failure remains primary; never claim completion.
        if isinstance(error, HTTPException):
            raise
        raise ImportStoreError(job_id) from error


def owned_job(session: Session, user_id: uuid.UUID, job_id: uuid.UUID) -> ImportJob:
    job = session.scalar(select(ImportJob).where(ImportJob.id == job_id, ImportJob.user_id == user_id))
    if job is None:
        raise HTTPException(404, "가져오기 작업을 찾을 수 없습니다.")
    return job
