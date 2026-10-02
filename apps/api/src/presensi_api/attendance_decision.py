from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from presensi_api.api.errors import ApiProblem
from presensi_api.api.security.roles import AuthenticatedUser, RoleCode
from presensi_api.api.v1.schemas.attendance import (
    AttendanceDecisionReason,
    AttendanceRecordResponse,
    AttendanceSource,
    AttendanceStatus,
    RecognitionEventDecisionResponse,
    RecognitionEventRequest,
    RecognitionOutcome,
)
from presensi_api.db.models import (
    AttendanceRecord,
    AttendanceSession,
    Device,
    PracticumSchedule,
    RecognitionEvent,
    SessionStudent,
    Student,
)
from presensi_api.session_lifecycle import (
    as_utc,
    close_expired_sessions,
    scheduled_start_at,
)


def _request_fingerprint(request: RecognitionEventRequest) -> str:
    canonical = json.dumps(
        request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _metadata(event: RecognitionEvent) -> dict[str, object]:
    return dict(event.quality_metadata)


def _response_for_event(
    session: Session,
    event: RecognitionEvent,
    *,
    replayed: bool,
) -> RecognitionEventDecisionResponse:
    metadata = _metadata(event)
    reported_outcome = metadata.get("reported_outcome", event.outcome)
    outcome = cast(RecognitionOutcome, reported_outcome)
    record = session.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.recognition_event_id == event.id
        )
    )
    if record is not None:
        attendance = AttendanceRecordResponse(
            id=record.id,
            session_id=record.session_id,
            student_id=record.student_id,
            status=cast(AttendanceStatus, record.status),
            source=cast(AttendanceSource, record.source),
            recognition_event_id=record.recognition_event_id,
            recorded_at=as_utc(record.recorded_at),
        )
        return RecognitionEventDecisionResponse(
            event_id=event.event_uuid,
            recognition_event_id=event.id,
            outcome=outcome,
            decision="attendance_recorded",
            reason=None,
            attendance=attendance,
            replayed=replayed,
        )

    decision = metadata.get("attendance_decision")
    reason: AttendanceDecisionReason | None = None
    if isinstance(decision, dict):
        saved_reason = decision.get("reason")
        if isinstance(saved_reason, str):
            reason = cast(AttendanceDecisionReason, saved_reason)
    return RecognitionEventDecisionResponse(
        event_id=event.event_uuid,
        recognition_event_id=event.id,
        outcome=outcome,
        decision="no_attendance",
        reason=reason,
        attendance=None,
        replayed=replayed,
    )


def _idempotent_response(
    session: Session,
    existing: RecognitionEvent,
    request: RecognitionEventRequest,
) -> RecognitionEventDecisionResponse:
    metadata = _metadata(existing)
    if metadata.get("idempotency_fingerprint") != _request_fingerprint(request):
        raise ApiProblem(
            409,
            "event_id_reused",
            "The event_id has already been used with a different payload.",
        )
    return _response_for_event(session, existing, replayed=True)


def decide_recognition_event(
    db: Session,
    request: RecognitionEventRequest,
    principal: AuthenticatedUser | None,
) -> RecognitionEventDecisionResponse:
    """Persist one AI event and create a final record only when domain rules pass."""
    close_expired_sessions(db, session_id=request.session_id)
    attendance_session = db.scalar(
        select(AttendanceSession)
        .where(AttendanceSession.id == request.session_id)
        .with_for_update()
    )
    if attendance_session is None:
        raise ApiProblem(404, "session_not_found", "Sesi presensi tidak ditemukan.")

    device = db.get(Device, request.device_id)
    if device is None:
        raise ApiProblem(404, "device_not_found", "Perangkat tidak ditemukan.")
    schedule = db.get(PracticumSchedule, attendance_session.practicum_schedule_id)
    if schedule is None:
        raise ApiProblem(404, "session_not_found", "Sesi presensi tidak ditemukan.")

    existing = db.scalar(
        select(RecognitionEvent).where(RecognitionEvent.event_uuid == request.event_id)
    )
    if existing is not None:
        return _idempotent_response(db, existing, request)

    candidate = (
        db.get(Student, request.student_id) if request.student_id is not None else None
    )
    candidate_exists = request.student_id is None or candidate is not None
    stored_outcome = request.outcome
    if request.outcome == "matched" and not candidate_exists:
        # Keep the event auditable without violating the candidate FK/check constraint.
        stored_outcome = "error"

    metadata: dict[str, object] = {
        "idempotency_fingerprint": _request_fingerprint(request),
        "liveness_passed": request.liveness_passed,
        "liveness_score": (
            float(request.liveness_score)
            if request.liveness_score is not None
            else None
        ),
        "reported_outcome": request.outcome,
        "reported_student_id": str(request.student_id)
        if request.student_id is not None
        else None,
    }
    event = RecognitionEvent(
        event_uuid=request.event_id,
        session_id=request.session_id,
        device_id=request.device_id,
        recognized_student_id=candidate.id if candidate is not None else None,
        occurred_at=request.occurred_at,
        outcome=stored_outcome,
        model_name=request.model_name,
        model_version=request.model_version,
        confidence=request.confidence,
        similarity=request.similarity,
        margin=request.margin,
        quality_metadata=metadata,
    )
    db.add(event)
    db.flush()
    device.last_seen_at = datetime.now(UTC)
    device.model_version = request.model_version

    reason: AttendanceDecisionReason | None = None
    if (
        principal is not None
        and RoleCode.TEACHER in principal.roles
        and RoleCode.ADMIN not in principal.roles
        and schedule.teacher_user_id != principal.id
    ):
        reason = "session_not_accessible"
    elif not device.is_active:
        reason = "device_inactive"
    elif not device.camera_enabled:
        reason = "device_camera_disabled"
    elif device.laboratory_id != schedule.laboratory_id:
        reason = "device_laboratory_mismatch"
    elif attendance_session.status != "active":
        reason = "session_inactive"
    elif not candidate_exists:
        reason = "student_not_found"
    elif (
        request.student_id is not None
        and db.get(
            SessionStudent,
            {"session_id": request.session_id, "student_id": request.student_id},
        )
        is None
    ):
        reason = "student_not_in_session_roster"
    elif request.outcome != "matched":
        reason = "recognition_not_matched"
    elif request.liveness_passed is False:
        reason = "liveness_failed"
    else:
        existing_record = db.scalar(
            select(AttendanceRecord).where(
                AttendanceRecord.session_id == request.session_id,
                AttendanceRecord.student_id == request.student_id,
            )
        )
        if existing_record is not None:
            reason = "attendance_already_recorded"

    if reason is None:
        assert request.student_id is not None
        grace_start = (
            scheduled_start_at(schedule, attendance_session.opened_at)
            if attendance_session.opened_by_user_id is None
            else as_utc(attendance_session.opened_at)
        )
        grace_cutoff = grace_start + timedelta(
            minutes=attendance_session.grace_period_minutes
        )
        attendance_status = (
            "present" if as_utc(request.occurred_at) <= grace_cutoff else "late"
        )
        record = AttendanceRecord(
            session_id=request.session_id,
            student_id=request.student_id,
            recognition_event_id=event.id,
            recorded_by_user_id=None,
            status=attendance_status,
            source="face_recognition",
        )
        db.add(record)
        metadata["attendance_decision"] = {
            "decision": "attendance_recorded",
            "status": attendance_status,
        }
    else:
        metadata["attendance_decision"] = {
            "decision": "no_attendance",
            "reason": reason,
        }
    event.quality_metadata = dict(metadata)
    flag_modified(event, "quality_metadata")
    db.commit()
    db.refresh(event)
    return _response_for_event(db, event, replayed=False)
