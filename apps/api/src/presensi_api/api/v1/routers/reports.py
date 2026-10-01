from datetime import UTC, datetime, time, timedelta
from io import BytesIO, StringIO
from typing import Annotated, Any, cast
from urllib.parse import quote
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

router = APIRouter(prefix="/reports", tags=["reports"])
DbSession = Annotated[Session, Depends(get_db_session)]
ReportReader = Annotated[
    AuthenticatedUser, Depends(require_permissions(Permission.REPORTS_READ))
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
