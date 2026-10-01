from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Mapping
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from presensi_api.db.models import AttendanceRecord, AuditLog, RecognitionEvent
from presensi_api.db.session import get_session_factory

DEFAULT_RECOGNITION_EVENT_RETENTION_DAYS = 90
MAX_RECOGNITION_EVENT_RETENTION_DAYS = 3650
RETENTION_BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class RetentionSummary:
    deleted_events: int
    redacted_events: int


def recognition_event_retention_days(
    environ: Mapping[str, str] | None = None,
) -> int:
    values = os.environ if environ is None else environ
    raw = values.get("PRESENSI_RECOGNITION_EVENT_RETENTION_DAYS", "").strip()
    if not raw:
        return DEFAULT_RECOGNITION_EVENT_RETENTION_DAYS
    try:
        days = int(raw)
    except ValueError as exc:
        raise ValueError(
            "Recognition-event retention days must be an integer."
        ) from exc
    if not 1 <= days <= MAX_RECOGNITION_EVENT_RETENTION_DAYS:
        raise ValueError("Recognition-event retention days must be between 1 and 3650.")
    return days


def apply_recognition_event_retention(
    session: Session,
    *,
    retention_days: int,
    now: datetime | None = None,
    batch_size: int = RETENTION_BATCH_SIZE,
) -> RetentionSummary:
    if not 1 <= retention_days <= MAX_RECOGNITION_EVENT_RETENTION_DAYS:
        raise ValueError("retention_days must be between 1 and 3650.")
    if batch_size < 1:
        raise ValueError("batch_size must be positive.")
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware.")
    cutoff = current.astimezone(UTC) - timedelta(days=retention_days)
    deleted_count = 0
    redacted_count = 0

    while True:
        expired = session.scalars(
            select(RecognitionEvent)
            .where(
                RecognitionEvent.created_at < cutoff,
                RecognitionEvent.outcome != "redacted",
            )
            .order_by(RecognitionEvent.created_at, RecognitionEvent.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        ).all()
        if not expired:
            break
        event_ids = [event.id for event in expired]
        referenced_ids = set(
            session.scalars(
                select(AttendanceRecord.recognition_event_id).where(
                    AttendanceRecord.recognition_event_id.in_(event_ids)
                )
            ).all()
        )
        for event in expired:
            if event.id in referenced_ids:
                # Preserve the attendance FK while removing recognition-derived data.
                event.outcome = "redacted"
                event.recognized_student_id = None
                event.confidence = None
                event.similarity = None
                event.margin = None
                event.quality_metadata = {"retention_redacted": True}
                redacted_count += 1
            else:
                session.delete(event)
                deleted_count += 1
        session.flush()
        if len(expired) < batch_size:
            break

    if deleted_count or redacted_count:
        session.add(
            AuditLog(
                actor_user_id=None,
                action="recognition_events.retention_applied",
                entity_type="retention_sweep",
                entity_id=uuid4(),
                after_state={
                    "retention_days": retention_days,
                    "deleted_events": deleted_count,
                    "redacted_events": redacted_count,
                },
            )
        )
    session.commit()
    return RetentionSummary(
        deleted_events=deleted_count,
        redacted_events=redacted_count,
    )


def main() -> int:
    try:
        retention_days = recognition_event_retention_days()
    except ValueError as exc:
        print(str(exc))
        return 2
    try:
        with get_session_factory()() as session:
            result = apply_recognition_event_retention(
                session, retention_days=retention_days
            )
    except Exception:
        print("Recognition-event retention failed; no event details were logged.")
        return 1
    print(
        "Recognition-event retention completed: "
        f"deleted={result.deleted_events}, redacted={result.redacted_events}, "
        f"retention_days={retention_days}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
