from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, cast, get_args
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.config import AuthConfigurationError, AuthSettings
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.roles import (
    AuthenticatedUser,
    Permission,
    RoleCode,
    principal_for_user,
)
from presensi_api.api.v1.schemas.attendance import (
    AttendanceDecisionReason,
    AttendanceStatus,
    RecognitionOutcome,
)
from presensi_api.api.v1.schemas.sessions import (
    SessionAttendanceSummary,
    SessionDashboardDevice,
    SessionDashboardSnapshot,
    SessionRecentActivity,
)
from presensi_api.db.models import (
    AttendanceRecord,
    AttendanceSession,
    Device,
    PracticumSchedule,
    RecognitionEvent,
    SessionStudent,
    User,
)
from presensi_api.db.session import get_db_session
from presensi_api.session_lifecycle import as_utc, close_expired_sessions

router = APIRouter(prefix="/sessions", tags=["sessions"])
DbSession = Annotated[Session, Depends(get_db_session)]
SessionOperator = Annotated[
    AuthenticatedUser, Depends(require_permissions(Permission.SESSION_OPERATE))
]


def _session_for_principal(
    db: Session, session_id: UUID, principal: AuthenticatedUser
) -> tuple[AttendanceSession, PracticumSchedule]:
    close_expired_sessions(db, session_id=session_id)
    attendance_session = db.get(AttendanceSession, session_id)
    if attendance_session is None:
        raise ApiProblem(404, "session_not_found", "Sesi presensi tidak ditemukan.")
    schedule = db.get(PracticumSchedule, attendance_session.practicum_schedule_id)
    if schedule is None or (
        RoleCode.TEACHER in principal.roles
        and RoleCode.ADMIN not in principal.roles
        and schedule.teacher_user_id != principal.id
    ):
        raise ApiProblem(404, "session_not_found", "Sesi presensi tidak ditemukan.")
    return attendance_session, schedule


def _online_threshold_seconds() -> int:
    try:
        configured = int(os.getenv("DEVICE_ONLINE_THRESHOLD_SECONDS", "60"))
    except ValueError:
        return 60
    return min(max(configured, 5), 3600)


def _poll_interval_seconds() -> float:
    try:
        configured = float(os.getenv("SESSION_DASHBOARD_POLL_SECONDS", "2"))
    except ValueError:
        return 2.0
    return min(max(configured, 0.25), 30.0)


def _attendance_status(value: str) -> AttendanceStatus:
    return cast(AttendanceStatus, value)


def _recognition_outcome(value: str) -> RecognitionOutcome:
    return cast(RecognitionOutcome, value)


def _decision_reason(event: RecognitionEvent) -> AttendanceDecisionReason | None:
    decision = event.quality_metadata.get("attendance_decision")
    if not isinstance(decision, dict):
        return None
    reason = decision.get("reason")
    if isinstance(reason, str) and reason in get_args(AttendanceDecisionReason):
        return cast(AttendanceDecisionReason, reason)
    return None


def _build_snapshot(
    db: Session,
    attendance_session: AttendanceSession,
    schedule: PracticumSchedule,
) -> SessionDashboardSnapshot:
    db.expire_all()
    attendance_session = cast(
        AttendanceSession, db.get(AttendanceSession, attendance_session.id)
    )
    schedule = cast(PracticumSchedule, db.get(PracticumSchedule, schedule.id))

    total_roster = (
        db.scalar(
            select(func.count())
            .select_from(SessionStudent)
            .where(SessionStudent.session_id == attendance_session.id)
        )
        or 0
    )
    status_counts = {
        status: count
        for status, count in db.execute(
            select(AttendanceRecord.status, func.count())
            .where(AttendanceRecord.session_id == attendance_session.id)
            .group_by(AttendanceRecord.status)
        ).all()
    }
    present = status_counts.get("present", 0)
    late = status_counts.get("late", 0)

    recognition_rows = db.execute(
        select(
            RecognitionEvent,
            SessionStudent.full_name_snapshot,
            AttendanceRecord.status,
        )
        .outerjoin(
            SessionStudent,
            and_(
                SessionStudent.session_id == RecognitionEvent.session_id,
                SessionStudent.student_id == RecognitionEvent.recognized_student_id,
            ),
        )
        .outerjoin(
            AttendanceRecord,
            AttendanceRecord.recognition_event_id == RecognitionEvent.id,
        )
        .where(RecognitionEvent.session_id == attendance_session.id)
        .order_by(RecognitionEvent.occurred_at.desc(), RecognitionEvent.id.desc())
        .limit(12)
    ).all()
    activities = [
        SessionRecentActivity(
            id=recognition.id,
            occurred_at=as_utc(recognition.occurred_at),
            kind="recognition",
            student_name=student_name,
            recognition_outcome=_recognition_outcome(recognition.outcome),
            attendance_status=(
                _attendance_status(attendance_status)
                if attendance_status is not None
                else None
            ),
            decision_reason=_decision_reason(recognition),
        )
        for recognition, student_name, attendance_status in recognition_rows
    ]

    manual_rows = db.execute(
        select(
            AttendanceRecord,
            SessionStudent.full_name_snapshot,
        )
        .join(
            SessionStudent,
            and_(
                SessionStudent.session_id == AttendanceRecord.session_id,
                SessionStudent.student_id == AttendanceRecord.student_id,
            ),
        )
        .where(
            AttendanceRecord.session_id == attendance_session.id,
            AttendanceRecord.recognition_event_id.is_(None),
        )
        .order_by(AttendanceRecord.recorded_at.desc(), AttendanceRecord.id.desc())
        .limit(12)
    ).all()
    activities.extend(
        SessionRecentActivity(
            id=record.id,
            occurred_at=as_utc(record.recorded_at),
            kind="attendance",
            student_name=student_name,
            recognition_outcome=None,
            attendance_status=_attendance_status(record.status),
            decision_reason=None,
        )
        for record, student_name in manual_rows
    )
    activities.sort(key=lambda activity: activity.occurred_at, reverse=True)

    now = datetime.now(UTC)
    online_cutoff = now - timedelta(seconds=_online_threshold_seconds())
    device_rows = db.scalars(
        select(Device)
        .where(Device.laboratory_id == schedule.laboratory_id)
        .order_by(Device.name, Device.id)
    ).all()
    devices = [
        SessionDashboardDevice(
            id=device.id,
            name=device.name,
            device_type=cast(Literal["edge_pc", "camera_gateway"], device.device_type),
            is_online=(
                device.is_active
                and device.last_seen_at is not None
                and as_utc(device.last_seen_at) >= online_cutoff
            ),
            last_seen_at=(
                as_utc(device.last_seen_at) if device.last_seen_at is not None else None
            ),
        )
        for device in device_rows
    ]

    return SessionDashboardSnapshot(
        session_id=attendance_session.id,
        session_status=cast(
            Literal["active", "closed", "cancelled"], attendance_session.status
        ),
        generated_at=now,
        summary=SessionAttendanceSummary(
            total_roster=total_roster,
            present=present,
            late=late,
            not_present=max(total_roster - present - late, 0),
        ),
        devices=devices,
        recent_activity=activities[:10],
    )


def _principal_from_token(
    db: Session, token: str
) -> tuple[AuthenticatedUser, datetime] | None:
    try:
        settings = AuthSettings.from_environment()
        claims = jwt.decode(
            token,
            settings.signing_secret,
            algorithms=["HS256"],
            issuer=settings.issuer,
            options={"require": ["sub", "iat", "exp", "jti", "iss", "token_use"]},
        )
        if claims.get("token_use") != "access":
            return None
        user_id = UUID(claims["sub"])
        expires_at = datetime.fromtimestamp(float(claims["exp"]), UTC)
    except (
        AuthConfigurationError,
        jwt.InvalidTokenError,
        KeyError,
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    principal = principal_for_user(db, user)
    return (principal, expires_at) if principal.roles else None


@router.get(
    "/{session_id}/dashboard",
    response_model=SessionDashboardSnapshot,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Get a live attendance dashboard snapshot",
)
def get_session_dashboard(
    session_id: UUID,
    principal: SessionOperator,
    db: DbSession,
) -> SessionDashboardSnapshot:
    attendance_session, schedule = _session_for_principal(db, session_id, principal)
    snapshot = _build_snapshot(db, attendance_session, schedule)
    db.commit()
    return snapshot


@router.websocket("/{session_id}/updates")
async def stream_session_updates(
    websocket: WebSocket,
    session_id: UUID,
    db: DbSession,
) -> None:
    await websocket.accept()
    try:
        authentication = await asyncio.wait_for(websocket.receive_json(), timeout=5)
    except (TimeoutError, WebSocketDisconnect):
        await websocket.close(code=4401, reason="Authentication required")
        return
    token = (
        authentication.get("access_token")
        if isinstance(authentication, dict)
        and authentication.get("type") == "authenticate"
        else None
    )
    if not isinstance(token, str) or len(token) > 8192:
        await websocket.close(code=4401, reason="Authentication required")
        return
    authentication_result = _principal_from_token(db, token)
    if authentication_result is None:
        await websocket.close(code=4401, reason="Authentication required")
        return
    principal, token_expires_at = authentication_result
    if Permission.SESSION_OPERATE not in principal.permissions:
        await websocket.close(code=4403, reason="Permission denied")
        return
    try:
        attendance_session, schedule = _session_for_principal(db, session_id, principal)
    except ApiProblem:
        await websocket.close(code=4404, reason="Session not found")
        return

    try:
        while True:
            if datetime.now(UTC) >= token_expires_at:
                await websocket.close(code=4401, reason="Authentication expired")
                return
            refreshed_authentication = _principal_from_token(db, token)
            if refreshed_authentication is None:
                await websocket.close(code=4401, reason="Authentication required")
                return
            refreshed_principal, _ = refreshed_authentication
            if Permission.SESSION_OPERATE not in refreshed_principal.permissions:
                await websocket.close(code=4403, reason="Permission denied")
                return
            try:
                attendance_session, schedule = _session_for_principal(
                    db, session_id, refreshed_principal
                )
            except ApiProblem:
                await websocket.close(code=4404, reason="Session not found")
                return
            snapshot = _build_snapshot(db, attendance_session, schedule)
            await websocket.send_json(
                {"type": "snapshot", "data": snapshot.model_dump(mode="json")}
            )
            db.commit()
            try:
                await asyncio.wait_for(
                    websocket.receive_text(), timeout=_poll_interval_seconds()
                )
            except TimeoutError:
                db.expire_all()
    except WebSocketDisconnect:
        return
