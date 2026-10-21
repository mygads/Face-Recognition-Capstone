from datetime import UTC, datetime, time, timedelta
from io import BytesIO, StringIO
from typing import Annotated, Any, cast
from urllib.parse import quote
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Response
from openpyxl import Workbook
from sqlalchemy import and_, case, func, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.roles import AuthenticatedUser, Permission, RoleCode
from presensi_api.api.v1.schemas.common import Pagination
from presensi_api.api.v1.schemas.reports import (
    AtRiskPage,
    AtRiskPolicy,
    AtRiskPolicyResponse,
    AtRiskQuery,
    AtRiskReason,
    AtRiskStudentRow,
    AttendanceReportExportQuery,
    AttendanceReportPage,
    AttendanceReportQuery,
    AttendanceReportResponse,
    AttendanceReportRow,
    ReportStatus,
)
from presensi_api.db.models import (
    AttendanceRecord,
    AttendanceSession,
    Laboratory,
    PracticumSchedule,
    SchoolClass,
    SessionStudent,
    User,
)
from presensi_api.db.session import get_db_session
from presensi_api.runtime_configuration import (
    AT_RISK_POLICY_SCOPE,
    at_risk_policy,
    save_configuration,
)

router = APIRouter(prefix="/reports", tags=["reports"])
DbSession = Annotated[Session, Depends(get_db_session)]
ReportReader = Annotated[
    AuthenticatedUser, Depends(require_permissions(Permission.REPORTS_READ))
]
AtRiskPolicyManager = Annotated[
    AuthenticatedUser, Depends(require_permissions(Permission.MANAGE_SETTINGS))
]
MAX_EXPORT_ROWS = 50_000

EXPORT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("session_opened_at", "Waktu sesi"),
    ("student_number", "NIS/NISN"),
    ("student_name", "Nama siswa"),
    ("class_code", "Kode kelas"),
    ("class_name", "Kelas"),
    ("laboratory_code", "Kode lab"),
    ("laboratory_name", "Laboratorium"),
    ("subject", "Mata praktikum"),
    ("teacher_name", "Guru"),
    ("status", "Status"),
    ("source", "Sumber"),
    ("recorded_at", "Waktu tercatat"),
    ("session_id", "ID sesi"),
    ("student_id", "ID siswa"),
    ("attendance_record_id", "ID record presensi"),
)


def _status_expression() -> ColumnElement[str]:
    return case(
        (AttendanceRecord.id.is_not(None), AttendanceRecord.status),
        (AttendanceSession.status == "closed", "absent"),
        else_="not_recorded",
    )


def _date_bounds(query: AttendanceReportQuery) -> tuple[datetime, datetime]:
    timezone = ZoneInfo(query.timezone_name)
    local_start = datetime.combine(query.starts_on, time.min, tzinfo=timezone)
    local_end = datetime.combine(
        query.ends_on + timedelta(days=1), time.min, tzinfo=timezone
    )
    return local_start.astimezone(UTC), local_end.astimezone(UTC)


def _statement(
    query: AttendanceReportQuery, principal: AuthenticatedUser
) -> Select[Any]:
    start_at, end_at = _date_bounds(query)
    report_status = _status_expression()
    statement = (
        select(
            AttendanceRecord.id.label("attendance_record_id"),
            AttendanceSession.id.label("session_id"),
            SessionStudent.student_id.label("student_id"),
            SessionStudent.student_number_snapshot.label("student_number"),
            SessionStudent.full_name_snapshot.label("student_name"),
            SchoolClass.id.label("class_id"),
            SchoolClass.code.label("class_code"),
            SchoolClass.name.label("class_name"),
            Laboratory.id.label("laboratory_id"),
            Laboratory.code.label("laboratory_code"),
            Laboratory.name.label("laboratory_name"),
            PracticumSchedule.subject.label("subject"),
            User.full_name.label("teacher_name"),
            report_status.label("status"),
            AttendanceRecord.source.label("source"),
            AttendanceSession.opened_at.label("session_opened_at"),
            AttendanceRecord.recorded_at.label("recorded_at"),
        )
        .select_from(SessionStudent)
        .join(
            AttendanceSession,
            AttendanceSession.id == SessionStudent.session_id,
        )
        .join(
            PracticumSchedule,
            PracticumSchedule.id == AttendanceSession.practicum_schedule_id,
        )
        .join(SchoolClass, SchoolClass.id == PracticumSchedule.class_id)
        .join(Laboratory, Laboratory.id == PracticumSchedule.laboratory_id)
        .join(User, User.id == PracticumSchedule.teacher_user_id)
        .outerjoin(
            AttendanceRecord,
            and_(
                AttendanceRecord.session_id == SessionStudent.session_id,
                AttendanceRecord.student_id == SessionStudent.student_id,
            ),
        )
        .where(
            AttendanceSession.status != "cancelled",
            AttendanceSession.opened_at >= start_at,
            AttendanceSession.opened_at < end_at,
        )
    )
    if query.student_id is not None:
        statement = statement.where(SessionStudent.student_id == query.student_id)
    if query.student_number is not None:
        statement = statement.where(
            SessionStudent.student_number_snapshot == query.student_number.upper()
        )
    if query.class_id is not None:
        statement = statement.where(PracticumSchedule.class_id == query.class_id)
    if query.laboratory_id is not None:
        statement = statement.where(
            PracticumSchedule.laboratory_id == query.laboratory_id
        )
    if query.session_id is not None:
        statement = statement.where(AttendanceSession.id == query.session_id)
    if query.status is not None:
        statement = statement.where(report_status == query.status)
    if RoleCode.TEACHER in principal.roles and RoleCode.ADMIN not in principal.roles:
        statement = statement.where(PracticumSchedule.teacher_user_id == principal.id)
    return cast(Select[Any], statement)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _report_row(row: Row[Any]) -> AttendanceReportRow:
    data = dict(row._mapping)
    data["session_opened_at"] = _as_utc(data["session_opened_at"])
    data["recorded_at"] = _as_utc(data["recorded_at"])
    data["status"] = cast(ReportStatus, data["status"])
    return AttendanceReportRow.model_validate(data)


def _query_rows(
    db: Session,
    query: AttendanceReportQuery,
    principal: AuthenticatedUser,
    *,
    page: bool,
) -> list[AttendanceReportRow]:
    statement = _statement(query, principal).order_by(
        AttendanceSession.opened_at.desc(),
        AttendanceSession.id.desc(),
        SessionStudent.student_number_snapshot,
    )
    if page:
        statement = statement.limit(query.limit).offset(query.offset)
    return [_report_row(row) for row in db.execute(statement).all()]


@router.get(
    "/attendance",
    response_model=AttendanceReportResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Get an attendance report summary",
)
def get_attendance_report(
    query: Annotated[AttendanceReportQuery, Query()],
    principal: ReportReader,
    db: DbSession,
) -> AttendanceReportResponse:
    filtered = _statement(query, principal).subquery()
    counts = {
        status: count
        for status, count in db.execute(
            select(filtered.c.status, func.count())
            .select_from(filtered)
            .group_by(filtered.c.status)
        ).all()
    }
    # Aggregate through the filtered row query so all filters and teacher scope
    # stay identical to the paginated and exported report.
    total_rows = sum(counts.values())
    return AttendanceReportResponse(
        starts_on=query.starts_on,
        ends_on=query.ends_on,
        total_rows=total_rows,
        present_count=counts.get("present", 0),
        late_count=counts.get("late", 0),
        absent_count=counts.get("absent", 0),
        excused_count=counts.get("excused", 0),
        not_recorded_count=counts.get("not_recorded", 0),
        generated_at=datetime.now(UTC),
    )


@router.get(
    "/attendance/at-risk/policy",
    response_model=AtRiskPolicyResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Read the attendance at-risk watchlist policy",
)
def get_at_risk_policy(
    principal: ReportReader,
    db: DbSession,
) -> AtRiskPolicyResponse:
    """Return the stored watchlist thresholds (school-calibrated operational
    configuration, not a sanction rule)."""
    revision, policy, updated_at = at_risk_policy(db)
    return AtRiskPolicyResponse(
        **AtRiskPolicy.model_validate(policy).model_dump(),
        revision=revision,
        updated_at=_as_utc(updated_at) if updated_at is not None else None,
    )


@router.put(
    "/attendance/at-risk/policy",
    response_model=AtRiskPolicyResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Publish the attendance at-risk watchlist policy",
)
def put_at_risk_policy(
    request: AtRiskPolicy,
    db: DbSession,
    actor: AtRiskPolicyManager,
) -> AtRiskPolicyResponse:
    """Persist school-calibrated watchlist thresholds. The change is audited
    through the runtime-configuration version log."""
    version = save_configuration(
        db,
        scope_key=AT_RISK_POLICY_SCOPE,
        settings=request.model_dump(mode="json"),
        actor=actor,
    )
    return AtRiskPolicyResponse(
        **request.model_dump(),
        revision=version.revision,
        updated_at=_as_utc(version.created_at),
    )


def _at_risk_window(window_days: int, timezone_name: str) -> tuple[datetime, datetime]:
    timezone = ZoneInfo(timezone_name)
    now = datetime.now(UTC)
    local_start = now.astimezone(timezone) - timedelta(days=window_days)
    start = datetime.combine(local_start.date(), time.min, tzinfo=timezone).astimezone(
        UTC
    )
    return start, now


def _at_risk_statement(
    query: AtRiskQuery,
    principal: AuthenticatedUser,
    start: datetime,
    end: datetime,
) -> Select[Any]:
    statement = (
        select(
            SessionStudent.student_id.label("student_id"),
            SessionStudent.student_number_snapshot.label("student_number"),
            SessionStudent.full_name_snapshot.label("full_name"),
            SchoolClass.name.label("class_name"),
            AttendanceSession.id.label("session_id"),
            AttendanceSession.status.label("session_status"),
            AttendanceSession.opened_at.label("opened_at"),
            AttendanceSession.closed_at.label("closed_at"),
            AttendanceRecord.status.label("record_status"),
            AttendanceRecord.recorded_at.label("recorded_at"),
        )
        .select_from(SessionStudent)
        .join(
            AttendanceSession,
            AttendanceSession.id == SessionStudent.session_id,
        )
        .join(
            PracticumSchedule,
            PracticumSchedule.id == AttendanceSession.practicum_schedule_id,
        )
        .join(SchoolClass, SchoolClass.id == PracticumSchedule.class_id)
        .outerjoin(
            AttendanceRecord,
            and_(
                AttendanceRecord.session_id == SessionStudent.session_id,
                AttendanceRecord.student_id == SessionStudent.student_id,
            ),
        )
        .where(
            AttendanceSession.status != "cancelled",
            AttendanceSession.opened_at >= start,
            AttendanceSession.opened_at <= end,
        )
    )
    if query.class_id is not None:
        statement = statement.where(PracticumSchedule.class_id == query.class_id)
    if query.laboratory_id is not None:
        statement = statement.where(
            PracticumSchedule.laboratory_id == query.laboratory_id
        )
    if RoleCode.TEACHER in principal.roles and RoleCode.ADMIN not in principal.roles:
        statement = statement.where(PracticumSchedule.teacher_user_id == principal.id)
    return cast(Select[Any], statement)


def _aggregate_at_risk_rows(rows: list[Row[Any]]) -> list[dict[str, Any]]:
    buckets: dict[UUID, dict[str, Any]] = {}
    for row in rows:
        mapping = row._mapping
        student_id = cast(UUID, mapping["student_id"])
        bucket = buckets.get(student_id)
        if bucket is None:
            bucket = {
                "student_id": student_id,
                "student_number": mapping["student_number"],
                "full_name": mapping["full_name"],
                "class_name": mapping["class_name"],
                "latest_opened_at": None,
                "total_sessions": 0,
                "absent_count": 0,
                "late_count": 0,
                "last_absent_at": None,
            }
            buckets[student_id] = bucket
        bucket["total_sessions"] += 1
        opened_at = _as_utc(cast(datetime, mapping["opened_at"]))
        assert opened_at is not None
        if bucket["latest_opened_at"] is None or opened_at > bucket["latest_opened_at"]:
            bucket["latest_opened_at"] = opened_at
            bucket["class_name"] = mapping["class_name"]
        record_status = mapping["record_status"]
        session_status = mapping["session_status"]
        absent_at: datetime | None = None
        if record_status == "absent":
            absent_at = (
                _as_utc(cast(datetime | None, mapping["recorded_at"]))
                or _as_utc(cast(datetime | None, mapping["closed_at"]))
                or opened_at
            )
        elif record_status is None and session_status == "closed":
            # A closed session without a record means the student never
            # checked in. Open sessions (not_recorded) never count as absent
            # so a running session cannot flag its students.
            absent_at = (
                _as_utc(cast(datetime | None, mapping["closed_at"])) or opened_at
            )
        elif record_status == "late":
            bucket["late_count"] += 1
        if absent_at is not None:
            bucket["absent_count"] += 1
            if bucket["last_absent_at"] is None or absent_at > bucket["last_absent_at"]:
                bucket["last_absent_at"] = absent_at
    return list(buckets.values())


@router.get(
    "/attendance/at-risk",
    response_model=AtRiskPage,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List students on the attendance watchlist",
)
def list_at_risk_students(
    query: Annotated[AtRiskQuery, Query()],
    principal: ReportReader,
    db: DbSession,
) -> AtRiskPage:
    """Return students whose absence rate or lateness reaches the effective
    thresholds, for manual follow-up by teachers/counselors.

    This is a human watchlist, not a sanction: it never blocks attendance, it
    sends no external notifications, and every flag cites the effective
    thresholds so it cannot look like an opaque automated decision.
    """
    revision, policy, _updated_at = at_risk_policy(db)
    effective_window = (
        query.window_days
        if query.window_days is not None
        else int(cast(int, policy["window_days"]))
    )
    effective_absence = (
        query.absence_pct
        if query.absence_pct is not None
        else float(cast(float, policy["absence_pct_threshold"]))
    )
    effective_late = (
        query.late_count
        if query.late_count is not None
        else int(cast(int, policy["late_count_threshold"]))
    )
    start, end = _at_risk_window(effective_window, query.timezone_name)
    statement = _at_risk_statement(query, principal, start, end)
    buckets = _aggregate_at_risk_rows(list(db.execute(statement).all()))
    flagged: list[AtRiskStudentRow] = []
    for bucket in buckets:
        total = bucket["total_sessions"]
        absent = bucket["absent_count"]
        absence_pct = round(absent * 100.0 / total, 2) if total else 0.0
        reasons: list[AtRiskReason] = []
        if absence_pct >= effective_absence:
            reasons.append("tingkat_absen")
        if bucket["late_count"] >= effective_late:
            reasons.append("sering_terlambat")
        if not reasons:
            continue
        flagged.append(
            AtRiskStudentRow(
                student_id=bucket["student_id"],
                student_number=bucket["student_number"],
                full_name=bucket["full_name"],
                class_name=bucket["class_name"],
                total_sessions=total,
                absent_count=absent,
                late_count=bucket["late_count"],
                absence_pct=absence_pct,
                last_absent_at=bucket["last_absent_at"],
                reasons=reasons,
            )
        )
    flagged.sort(key=lambda item: (-item.absence_pct, -item.late_count, item.full_name))
    total_flagged = len(flagged)
    page_items = flagged[query.offset : query.offset + query.limit]
    return AtRiskPage(
        items=page_items,
        pagination=Pagination(
            total=total_flagged, limit=query.limit, offset=query.offset
        ),
        effective_window_days=effective_window,
        effective_absence_pct_threshold=effective_absence,
        effective_late_count_threshold=effective_late,
        policy_revision=revision,
        generated_at=datetime.now(UTC),
    )


@router.get(
    "/attendance/records",
    response_model=AttendanceReportPage,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List paginated attendance report rows",
)
def list_attendance_report_records(
    query: Annotated[AttendanceReportQuery, Query()],
    principal: ReportReader,
    db: DbSession,
) -> AttendanceReportPage:
    statement = _statement(query, principal)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = _query_rows(db, query, principal, page=True)
    return AttendanceReportPage(
        items=rows,
        pagination=Pagination(total=total, limit=query.limit, offset=query.offset),
    )


def _export_rows(
    db: Session, query: AttendanceReportQuery, principal: AuthenticatedUser
) -> list[AttendanceReportRow]:
    filtered = _statement(query, principal).subquery()
    total = db.scalar(select(func.count()).select_from(filtered)) or 0
    if total > MAX_EXPORT_ROWS:
        raise ApiProblem(
            413,
            "report_export_too_large",
            f"Export dibatasi maksimal {MAX_EXPORT_ROWS:,} baris. Tambahkan filter.",
        )
    return _query_rows(db, query, principal, page=False)


def _spreadsheet_value(value: object) -> str | int | float | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return str(value)


@router.get(
    "/attendance/export",
    response_class=Response,
    responses={
        **OPENAPI_ERROR_RESPONSES,
        200: {
            "description": "CSV or XLSX attendance report download.",
            "content": {
                "text/csv": {"schema": {"type": "string", "format": "binary"}},
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
                    "schema": {"type": "string", "format": "binary"}
                },
            },
        },
    },
    summary="Export attendance report rows",
)
def export_attendance_report(
    query: Annotated[AttendanceReportExportQuery, Query()],
    principal: ReportReader,
    db: DbSession,
) -> Response:
    rows = _export_rows(db, query, principal)
    filename = f"attendance-{query.starts_on}-{query.ends_on}.{query.format}"
    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
    if query.format == "csv":
        stream = StringIO(newline="")
        import csv

        writer = csv.writer(stream)
        writer.writerow([label for _, label in EXPORT_COLUMNS])
        for row in rows:
            values = row.model_dump()
            writer.writerow(
                [_spreadsheet_value(values[key]) for key, _ in EXPORT_COLUMNS]
            )
        return Response(
            content="\ufeff" + stream.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": disposition},
        )

    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Presensi")
    sheet.append([label for _, label in EXPORT_COLUMNS])
    for row in rows:
        values = row.model_dump()
        sheet.append([_spreadsheet_value(values[key]) for key, _ in EXPORT_COLUMNS])
    output = BytesIO()
    workbook.save(output)
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": disposition},
    )
