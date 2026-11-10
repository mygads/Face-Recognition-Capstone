from datetime import UTC, datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.roles import (
    AuthenticatedUser,
    Permission,
    RoleCode,
)
from presensi_api.api.v1.schemas.attendance import (
    AttendanceCorrectionDecisionRequest,
    AttendanceCorrectionRequest,
    AttendanceCorrectionResponse,
    AttendanceRecordResponse,
    AttendanceSource,
    AttendanceStatus,
    ManualMarkRequest,
    ManualMarkResponse,
    RecognitionEventDecisionResponse,
    RecognitionEventRequest,
)
from presensi_api.api.v1.schemas.common import PageResponse, Pagination
from presensi_api.attendance_decision import decide_recognition_event
from presensi_api.attendance_manual import mark_manual_attendance
from presensi_api.db.models import (
    AttendanceCorrection,
    AttendanceRecord,
    AttendanceSession,
    AuditLog,
    PracticumSchedule,
)
from presensi_api.db.session import get_db_session
from presensi_api.session_lifecycle import as_utc

router = APIRouter(prefix="/attendance", tags=["attendance"])
DbSession = Annotated[Session, Depends(get_db_session)]
AttendanceOperator = Annotated[
    AuthenticatedUser, Depends(require_permissions(Permission.SESSION_OPERATE))
]
ManualMarkOperator = Annotated[
    AuthenticatedUser, Depends(require_permissions(Permission.ATTENDANCE_MANUAL))
]
CorrectionProposer = Annotated[
    AuthenticatedUser, Depends(require_permissions(Permission.ATTENDANCE_CORRECT))
]


@router.post(
    "/recognition-events",
    response_model=RecognitionEventDecisionResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Record an AI recognition event and decide attendance",
    description=(
        "Stores the recognition event for audit. Creates a final attendance record "
        "only when device, session, roster, liveness, and duplicate rules pass."
    ),
)
def ingest_recognition_event(
    request: RecognitionEventRequest,
    principal: AttendanceOperator,
    session: DbSession,
) -> RecognitionEventDecisionResponse:
    return decide_recognition_event(session, request, principal)


@router.post(
    "/sessions/{session_id}/manual-marks",
    response_model=ManualMarkResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Record a teacher-chosen manual attendance mark",
    description=(
        "Stores a final attendance record with source 'manual' for a roster "
        "member without overwriting existing records. Never accepts image or "
        "embedding fields."
    ),
)
def create_manual_mark(
    session_id: UUID,
    request: ManualMarkRequest,
    principal: ManualMarkOperator,
    session: DbSession,
) -> ManualMarkResponse:
    record = mark_manual_attendance(session, session_id, request, principal)
    return ManualMarkResponse(
        record=AttendanceRecordResponse(
            id=record.id,
            session_id=record.session_id,
            student_id=record.student_id,
            status=cast(AttendanceStatus, record.status),
            source=cast(AttendanceSource, record.source),
            recognition_event_id=record.recognition_event_id,
            recorded_at=as_utc(record.recorded_at),
            occurred_at=as_utc(record.occurred_at)
            if record.occurred_at is not None
            else None,
            rule_version=record.rule_version,
            note=record.note,
        )
    )


@router.get(
    "",
    response_model=PageResponse[AttendanceRecordResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List final attendance records",
    description=(
        "Final attendance only: one row per student/session after session, "
        "roster, liveness, and duplicate validation. Teachers see only "
        "their own schedules."
    ),
)
def list_attendance(
    principal: Annotated[
        AuthenticatedUser, Depends(require_permissions(Permission.ATTENDANCE_READ))
    ],
    session: DbSession,
    session_id: UUID | None = None,
    student_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageResponse[AttendanceRecordResponse]:
    query = (
        select(AttendanceRecord)
        .join(
            AttendanceSession,
            AttendanceSession.id == AttendanceRecord.session_id,
        )
        .join(
            PracticumSchedule,
            PracticumSchedule.id == AttendanceSession.practicum_schedule_id,
        )
    )
    if RoleCode.ADMIN not in principal.roles:
        if RoleCode.TEACHER in principal.roles:
            from presensi_api.api.security.scope import (
                teacher_class_ids as _tc,
            )

            _classes = _tc(session, principal.id)
            if _classes:
                query = query.where(
                    (PracticumSchedule.class_id.in_(_classes))
                    | (PracticumSchedule.teacher_user_id == principal.id)
                )
            else:
                query = query.where(PracticumSchedule.teacher_user_id == principal.id)
        elif RoleCode.LABORANT in principal.roles:
            from presensi_api.api.security.scope import laborant_lab_ids as _ll

            _labs = _ll(session, principal.id)
            if _labs:
                query = query.where(PracticumSchedule.laboratory_id.in_(_labs))
            else:
                query = query.where(PracticumSchedule.id.is_(None))
    if session_id is not None:
        query = query.where(AttendanceRecord.session_id == session_id)
    if student_id is not None:
        query = query.where(AttendanceRecord.student_id == student_id)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(
        query.order_by(AttendanceRecord.recorded_at.desc(), AttendanceRecord.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return PageResponse(
        items=[
            AttendanceRecordResponse(
                id=row.id,
                session_id=row.session_id,
                student_id=row.student_id,
                status=cast(AttendanceStatus, row.status),
                source=cast(AttendanceSource, row.source),
                recognition_event_id=row.recognition_event_id,
                recorded_at=as_utc(row.recorded_at),
                occurred_at=as_utc(row.occurred_at)
                if row.occurred_at is not None
                else None,
                rule_version=row.rule_version,
                note=row.note,
            )
            for row in rows
        ],
        pagination=Pagination(total=total, limit=limit, offset=offset),
    )


@router.post(
    "/corrections",
    response_model=AttendanceCorrectionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Create an audited pending attendance correction request",
    description=(
        "Stores a teacher correction request for a schedule they own. The request "
        "remains pending and does not change final attendance until an ADMIN "
        "decides it via POST /attendance/corrections/{correction_id}/decision."
    ),
)
def request_attendance_correction(
    request: AttendanceCorrectionRequest,
    principal: CorrectionProposer,
    session: DbSession,
) -> AttendanceCorrectionResponse:
    from uuid import uuid4

    from presensi_api.api.security.scope import (
        laborant_lab_ids as _ll,
    )
    from presensi_api.api.security.scope import (
        teacher_class_ids as _tc,
    )
    from presensi_api.db.models import SessionStudent

    def _scope_allows(schedule: PracticumSchedule) -> bool:
        if RoleCode.ADMIN in principal.roles:
            return True
        if RoleCode.TEACHER in principal.roles:
            if schedule.teacher_user_id == principal.id:
                return True
            if schedule.class_id in _tc(session, principal.id):
                return True
            return False
        if RoleCode.LABORANT in principal.roles:
            if schedule.laboratory_id in _ll(session, principal.id):
                return True
            return False
        return True

    def _pending_exists_for_record(record_id: UUID) -> bool:
        return (
            session.scalar(
                select(AttendanceCorrection.id).where(
                    AttendanceCorrection.attendance_record_id == record_id,
                    AttendanceCorrection.decision_status == "pending",
                )
            )
            is not None
        )

    def _pending_exists_for_missing(sid: UUID, stid: UUID) -> bool:
        return (
            session.scalar(
                select(AttendanceCorrection.id).where(
                    AttendanceCorrection.session_id == sid,
                    AttendanceCorrection.student_id == stid,
                    AttendanceCorrection.decision_status == "pending",
                )
            )
            is not None
        )

    def _to_response(correction: AttendanceCorrection) -> AttendanceCorrectionResponse:
        return AttendanceCorrectionResponse(
            id=correction.id,
            attendance_record_id=correction.attendance_record_id,
            incident_ref=correction.incident_ref,
            session_id=correction.session_id,
            student_id=correction.student_id,
            previous_status=cast(AttendanceStatus, correction.previous_status),
            corrected_status=cast(AttendanceStatus, correction.corrected_status),
            decision_status=cast(
                Literal["pending", "approved", "rejected"],
                correction.decision_status,
            ),
            reason=correction.reason,
            created_at=as_utc(correction.created_at),
            decided_at=(
                as_utc(correction.decided_at)
                if correction.decided_at is not None
                else None
            ),
            decided_by_user_id=correction.decided_by_user_id,
            decision_note=correction.decision_note,
        )

    def _resolve_incident(target_session_id: UUID) -> UUID:
        # Kasus salah identitas: tautkan ke insiden pending pada sesi yang sama
        # agar kedua koreksi diputus atomik. Tanpa tautan, buat insiden baru.
        if request.incident_ref is None:
            return uuid4()
        anchor = session.scalars(
            select(AttendanceCorrection).where(
                AttendanceCorrection.incident_ref == request.incident_ref,
                AttendanceCorrection.session_id == target_session_id,
                AttendanceCorrection.decision_status == "pending",
            )
        ).first()
        if anchor is None:
            raise ApiProblem(
                404,
                "correction_incident_not_found",
                "Insiden koreksi tidak ditemukan pada sesi ini.",
            )
        return anchor.incident_ref  # type: ignore[return-value]

    if request.attendance_record_id is not None:
        record = session.get(AttendanceRecord, request.attendance_record_id)
        if record is None:
            raise ApiProblem(
                404, "attendance_record_not_found", "Presensi tidak ditemukan."
            )
        attendance_session = session.get(AttendanceSession, record.session_id)
        schedule = (
            session.get(PracticumSchedule, attendance_session.practicum_schedule_id)
            if attendance_session is not None
            else None
        )
        if schedule is None:
            raise ApiProblem(
                404, "attendance_record_not_found", "Presensi tidak ditemukan."
            )
        if not _scope_allows(schedule):
            raise ApiProblem(
                404, "attendance_record_not_found", "Presensi tidak ditemukan."
            )
        if _pending_exists_for_record(record.id):
            raise ApiProblem(
                409,
                "correction_already_pending",
                "Sudah ada pengajuan koreksi aktif untuk target ini.",
            )
        try:
            correction = AttendanceCorrection(
                attendance_record_id=record.id,
                session_id=record.session_id,
                student_id=record.student_id,
                requested_by_user_id=principal.id,
                incident_ref=_resolve_incident(record.session_id),
                previous_status=record.status,
                corrected_status=request.corrected_status,
                reason=request.reason,
                decision_status="pending",
            )
            session.add(correction)
            session.flush()
        except IntegrityError as exc:
            raise ApiProblem(
                409,
                "correction_already_pending",
                "Sudah ada pengajuan koreksi aktif untuk target ini.",
            ) from exc
        session.add(
            AuditLog(
                actor_user_id=principal.id,
                action="attendance.correction.requested",
                entity_type="attendance_correction",
                entity_id=correction.id,
                after_state={
                    "attendance_record_id": str(record.id),
                    "incident_ref": str(correction.incident_ref),
                    "previous_status": record.status,
                    "corrected_status": request.corrected_status,
                    "decision_status": "pending",
                },
            )
        )
        session.commit()
        session.refresh(correction)
        return _to_response(correction)
    # Missing-record case: session closed, student has no record (dianggap absen).
    assert request.session_id is not None and request.student_id is not None
    attendance_session = session.get(AttendanceSession, request.session_id)
    if attendance_session is None:
        raise ApiProblem(404, "session_not_found", "Sesi tidak ditemukan.")
    if attendance_session.status in ("active", "manual_override"):
        raise ApiProblem(
            409,
            "session_still_active",
            "Sesi masih berjalan; gunakan tandai manual. Koreksi tanpa record "
            "hanya untuk sesi yang sudah ditutup.",
        )
    schedule = session.get(PracticumSchedule, attendance_session.practicum_schedule_id)
    if schedule is None:
        raise ApiProblem(404, "session_not_found", "Sesi tidak ditemukan.")
    if not _scope_allows(schedule):
        raise ApiProblem(404, "session_not_found", "Sesi tidak ditemukan.")
    if _pending_exists_for_missing(request.session_id, request.student_id):
        raise ApiProblem(
            409,
            "correction_already_pending",
            "Sudah ada pengajuan koreksi aktif untuk target ini.",
        )
    roster = session.get(SessionStudent, (request.session_id, request.student_id))
    if roster is None:
        raise ApiProblem(
            404, "student_not_in_session_roster", "Siswa tidak termasuk roster sesi."
        )
    existing = session.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.session_id == request.session_id,
            AttendanceRecord.student_id == request.student_id,
        )
    )
    if existing is not None:
        raise ApiProblem(
            409,
            "attendance_already_recorded",
            "Siswa sudah memiliki catatan presensi; gunakan koreksi record yang ada.",
        )
    try:
        correction = AttendanceCorrection(
            attendance_record_id=None,
            session_id=request.session_id,
            student_id=request.student_id,
            requested_by_user_id=principal.id,
            incident_ref=_resolve_incident(request.session_id),
            previous_status="absent",
            corrected_status=request.corrected_status,
            reason=request.reason,
            decision_status="pending",
        )
        session.add(correction)
        session.flush()
    except IntegrityError as exc:
        raise ApiProblem(
            409,
            "correction_already_pending",
            "Sudah ada pengajuan koreksi aktif untuk target ini.",
        ) from exc
    session.add(
        AuditLog(
            actor_user_id=principal.id,
            action="attendance.correction.requested",
            entity_type="attendance_correction",
            entity_id=correction.id,
            after_state={
                "session_id": str(request.session_id),
                "student_id": str(request.student_id),
                "incident_ref": str(correction.incident_ref),
                "previous_status": "absent",
                "corrected_status": request.corrected_status,
                "decision_status": "pending",
            },
        )
    )
    session.commit()
    session.refresh(correction)
    return _to_response(correction)


@router.get(
    "/corrections",
    response_model=PageResponse[AttendanceCorrectionResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List attendance correction requests",
    description=(
        "Lists correction requests with pending/approved/rejected status. "
        "Teachers see only corrections for schedules they own."
    ),
)
def list_attendance_corrections(
    principal: Annotated[
        AuthenticatedUser, Depends(require_permissions(Permission.ATTENDANCE_CORRECT))
    ],
    session: DbSession,
    decision_status: Literal["pending", "approved", "rejected"] | None = None,
    session_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageResponse[AttendanceCorrectionResponse]:
    query = (
        select(AttendanceCorrection)
        .outerjoin(
            AttendanceRecord,
            AttendanceRecord.id == AttendanceCorrection.attendance_record_id,
        )
        .outerjoin(
            AttendanceSession,
            (AttendanceSession.id == AttendanceRecord.session_id)
            | (AttendanceSession.id == AttendanceCorrection.session_id),
        )
        .outerjoin(
            PracticumSchedule,
            PracticumSchedule.id == AttendanceSession.practicum_schedule_id,
        )
    )
    if RoleCode.ADMIN not in principal.roles:
        if RoleCode.TEACHER in principal.roles:
            from presensi_api.api.security.scope import (
                teacher_class_ids as _tc2,
            )

            _classes2 = _tc2(session, principal.id)
            if _classes2:
                query = query.where(
                    (PracticumSchedule.class_id.in_(_classes2))
                    | (PracticumSchedule.teacher_user_id == principal.id)
                )
            else:
                query = query.where(
                    (PracticumSchedule.teacher_user_id == principal.id)
                    | (PracticumSchedule.teacher_user_id.is_(None))
                )
        elif RoleCode.LABORANT in principal.roles:
            from presensi_api.api.security.scope import laborant_lab_ids as _ll2

            _labs2 = _ll2(session, principal.id)
            if _labs2:
                query = query.where(PracticumSchedule.laboratory_id.in_(_labs2))
            else:
                query = query.where(PracticumSchedule.id.is_(None))
    if decision_status is not None:
        query = query.where(AttendanceCorrection.decision_status == decision_status)
    if session_id is not None:
        query = query.where(
            (AttendanceRecord.session_id == session_id)
            | (AttendanceCorrection.session_id == session_id)
        )
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(
        query.order_by(
            AttendanceCorrection.created_at.desc(), AttendanceCorrection.id.desc()
        )
        .limit(limit)
        .offset(offset)
    ).all()
    return PageResponse(
        items=[
            AttendanceCorrectionResponse(
                id=row.id,
                attendance_record_id=row.attendance_record_id,
                incident_ref=row.incident_ref,
                session_id=row.session_id,
                student_id=row.student_id,
                previous_status=cast(AttendanceStatus, row.previous_status),
                corrected_status=cast(AttendanceStatus, row.corrected_status),
                decision_status=cast(
                    Literal["pending", "approved", "rejected"], row.decision_status
                ),
                reason=row.reason,
                created_at=as_utc(row.created_at),
                decided_at=(
                    as_utc(row.decided_at) if row.decided_at is not None else None
                ),
                decided_by_user_id=row.decided_by_user_id,
                decision_note=row.decision_note,
            )
            for row in rows
        ],
        pagination=Pagination(total=total, limit=limit, offset=offset),
    )


@router.get(
    "/corrections/{correction_id}",
    response_model=AttendanceCorrectionResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Get an attendance correction request",
)
def get_attendance_correction(
    correction_id: UUID,
    principal: CorrectionProposer,
    session: DbSession,
) -> AttendanceCorrectionResponse:
    correction = session.scalar(
        select(AttendanceCorrection)
        .where(AttendanceCorrection.id == correction_id)
        .with_for_update()
    )
    if correction is None:
        raise ApiProblem(
            404, "attendance_correction_not_found", "Koreksi tidak ditemukan."
        )
    # Scope check: teacher/lab must see the underlying schedule.
    record = (
        session.get(AttendanceRecord, correction.attendance_record_id)
        if correction.attendance_record_id is not None
        else None
    )
    sid = record.session_id if record is not None else correction.session_id
    if sid is not None and RoleCode.ADMIN not in principal.roles:
        sched_session = session.get(AttendanceSession, sid)
        sched = (
            session.get(PracticumSchedule, sched_session.practicum_schedule_id)
            if sched_session is not None
            else None
        )
        if sched is not None:
            from presensi_api.api.security.scope import (
                laborant_lab_ids as _ll3,
            )
            from presensi_api.api.security.scope import (
                teacher_class_ids as _tc3,
            )

            allowed = False
            if RoleCode.TEACHER in principal.roles:
                if sched.teacher_user_id == principal.id:
                    allowed = True
                elif sched.class_id in _tc3(session, principal.id):
                    allowed = True
            elif RoleCode.LABORANT in principal.roles:
                if sched.laboratory_id in _ll3(session, principal.id):
                    allowed = True
            else:
                allowed = True
            if not allowed:
                raise ApiProblem(
                    404,
                    "attendance_correction_not_found",
                    "Koreksi tidak ditemukan.",
                )
    return AttendanceCorrectionResponse(
        id=correction.id,
        attendance_record_id=correction.attendance_record_id,
        incident_ref=correction.incident_ref,
        session_id=correction.session_id,
        student_id=correction.student_id,
        previous_status=cast(AttendanceStatus, correction.previous_status),
        corrected_status=cast(AttendanceStatus, correction.corrected_status),
        decision_status=cast(
            Literal["pending", "approved", "rejected"], correction.decision_status
        ),
        reason=correction.reason,
        created_at=as_utc(correction.created_at),
        decided_at=(
            as_utc(correction.decided_at) if correction.decided_at is not None else None
        ),
        decided_by_user_id=correction.decided_by_user_id,
        decision_note=correction.decision_note,
    )


@router.post(
    "/corrections/{correction_id}/decision",
    response_model=AttendanceCorrectionResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Decide an attendance correction (ADMIN only)",
    description=(
        "Approves or rejects a pending correction. Approved corrections update "
        "the linked attendance record to corrected_status. Rejected corrections "
        "leave the final record unchanged."
    ),
)
def decide_attendance_correction(
    correction_id: UUID,
    request: AttendanceCorrectionDecisionRequest,
    principal: Annotated[
        AuthenticatedUser, Depends(require_permissions(Permission.ATTENDANCE_CORRECT))
    ],
    session: DbSession,
) -> AttendanceCorrectionResponse:
    if RoleCode.ADMIN not in principal.roles:
        raise ApiProblem(
            403,
            "attendance_correction_forbidden",
            "Hanya ADMIN yang boleh memutuskan koreksi.",
        )
    correction = session.scalar(
        select(AttendanceCorrection)
        .where(AttendanceCorrection.id == correction_id)
        .with_for_update()
    )
    if correction is None:
        raise ApiProblem(
            404, "attendance_correction_not_found", "Koreksi tidak ditemukan."
        )
    if correction.decision_status != "pending":
        raise ApiProblem(409, "correction_already_decided", "Koreksi sudah diputuskan.")
    from presensi_api.db.models import SessionStudent as _SessionStudent

    record = (
        session.get(AttendanceRecord, correction.attendance_record_id)
        if correction.attendance_record_id is not None
        else None
    )
    if record is not None:
        if record.status != correction.previous_status:
            raise ApiProblem(
                409,
                "correction_stale",
                "Status presensi sudah berubah sejak koreksi diajukan.",
            )
    else:
        # Missing-record case: must have session+student, no existing record.
        if correction.session_id is None or correction.student_id is None:
            raise ApiProblem(
                404, "attendance_record_not_found", "Presensi tidak ditemukan."
            )
        roster = session.get(
            _SessionStudent, (correction.session_id, correction.student_id)
        )
        if roster is None:
            raise ApiProblem(
                404,
                "student_not_in_session_roster",
                "Siswa tidak termasuk roster sesi.",
            )
        existing = session.scalar(
            select(AttendanceRecord).where(
                AttendanceRecord.session_id == correction.session_id,
                AttendanceRecord.student_id == correction.student_id,
            )
        )
        if existing is not None:
            raise ApiProblem(
                409,
                "attendance_already_recorded",
                "Siswa sudah memiliki catatan presensi.",
            )
    now = datetime.now(UTC)
    record_before: str | None = None
    created_record_id: str | None = None
    siblings: list[AttendanceCorrection] = []
    if correction.incident_ref is not None:
        siblings = list(
            session.scalars(
                select(AttendanceCorrection).where(
                    AttendanceCorrection.incident_ref == correction.incident_ref,
                    AttendanceCorrection.id != correction.id,
                    AttendanceCorrection.decision_status == "pending",
                )
            ).all()
        )
    if request.decision == "approved" and record is not None:
        if record.status != correction.corrected_status:
            record_before = record.status
            record.status = correction.corrected_status
    if request.decision == "approved" and record is None:
        assert correction.session_id is not None and correction.student_id is not None
        record = AttendanceRecord(
            session_id=correction.session_id,
            student_id=correction.student_id,
            status=correction.corrected_status,
            source="manual",
            recognition_event_id=None,
            recorded_at=now,
            recorded_by_user_id=principal.id,
            note=(correction.reason[:500] if correction.reason else None),
        )
        session.add(record)
        session.flush()
        correction.attendance_record_id = record.id
        created_record_id = str(record.id)
        record_before = "absent (tanpa record)"

    for sibling in siblings:
        if request.decision == "approved":
            sib_record = (
                session.get(AttendanceRecord, sibling.attendance_record_id)
                if sibling.attendance_record_id is not None
                else None
            )
            if sib_record is not None:
                if sib_record.status == sibling.previous_status:
                    sib_record.status = sibling.corrected_status
            elif sibling.session_id is not None and sibling.student_id is not None:
                sib_existing = session.scalar(
                    select(AttendanceRecord).where(
                        AttendanceRecord.session_id == sibling.session_id,
                        AttendanceRecord.student_id == sibling.student_id,
                    )
                )
                if sib_existing is None:
                    sib_record = AttendanceRecord(
                        session_id=sibling.session_id,
                        student_id=sibling.student_id,
                        status=sibling.corrected_status,
                        source="manual",
                        recognition_event_id=None,
                        recorded_at=now,
                        recorded_by_user_id=principal.id,
                        note=(sibling.reason[:500] if sibling.reason else None),
                    )
                    session.add(sib_record)
                    session.flush()
                    sibling.attendance_record_id = sib_record.id
        sibling.decision_status = request.decision
        sibling.decided_by_user_id = principal.id
        sibling.decided_at = now
        if sibling.decision_note is None:
            sibling.decision_note = request.decision_note
        session.add(
            AuditLog(
                actor_user_id=principal.id,
                action="attendance.correction.decided",
                entity_type="attendance_correction",
                entity_id=sibling.id,
                before_state={"decision_status": "pending"},
                after_state={
                    "decision": request.decision,
                    "incident_ref": str(correction.incident_ref),
                    "applied_with": str(correction.id),
                },
            )
        )
    correction.decision_status = request.decision
    correction.decided_by_user_id = principal.id
    correction.decided_at = now
    correction.decision_note = request.decision_note
    session.add(
        AuditLog(
            actor_user_id=principal.id,
            action="attendance.correction.decided",
            entity_type="attendance_correction",
            entity_id=correction.id,
            before_state={
                "decision_status": "pending",
                "record_status": (
                    record_before
                    if record_before is not None
                    else (record.status if record is not None else None)
                ),
            },
            after_state={
                "attendance_record_id": (
                    str(record.id) if record is not None else created_record_id
                ),
                "decision": request.decision,
                "previous_status": correction.previous_status,
                "corrected_status": correction.corrected_status,
                "record_status": record.status if record is not None else None,
                "decision_note": request.decision_note,
                "created_record": created_record_id,
            },
        )
    )
    session.commit()
    session.refresh(correction)
    if record is not None:
        session.refresh(record)
    return AttendanceCorrectionResponse(
        id=correction.id,
        attendance_record_id=correction.attendance_record_id,
        incident_ref=correction.incident_ref,
        session_id=correction.session_id,
        student_id=correction.student_id,
        previous_status=cast(AttendanceStatus, correction.previous_status),
        corrected_status=cast(AttendanceStatus, correction.corrected_status),
        decision_status=cast(
            Literal["pending", "approved", "rejected"], correction.decision_status
        ),
        reason=correction.reason,
        created_at=as_utc(correction.created_at),
        decided_at=(
            as_utc(correction.decided_at) if correction.decided_at is not None else None
        ),
        decided_by_user_id=correction.decided_by_user_id,
        decision_note=correction.decision_note,
    )
