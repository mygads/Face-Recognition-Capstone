from datetime import UTC, date, datetime, time
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.roles import AuthenticatedUser, Permission, RoleCode
from presensi_api.api.v1.schemas.common import PageResponse, Pagination
from presensi_api.api.v1.schemas.schedules import (
    ScheduleCreateRequest,
    ScheduleResponse,
    ScheduleTeacherResponse,
    ScheduleUpdateRequest,
)
from presensi_api.db.models import (
    Laboratory,
    PracticumSchedule,
    Role,
    SchoolClass,
    User,
    UserRole,
)
from presensi_api.db.session import get_db_session

router = APIRouter(prefix="/schedules", tags=["schedules"])


def _timestamp(value: datetime) -> datetime:
    # SQLite drops tzinfo when materializing DateTime(timezone=True).
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _response(session: Session, schedule: PracticumSchedule) -> ScheduleResponse:
    school_class = session.get(SchoolClass, schedule.class_id)
    laboratory = session.get(Laboratory, schedule.laboratory_id)
    teacher = session.get(User, schedule.teacher_user_id)
    assert school_class is not None and laboratory is not None and teacher is not None
    return ScheduleResponse(
        id=schedule.id,
        class_id=schedule.class_id,
        laboratory_id=schedule.laboratory_id,
        teacher_user_id=schedule.teacher_user_id,
        subject=schedule.subject,
        weekday=schedule.weekday,
        start_time=schedule.start_time,
        end_time=schedule.end_time,
        timezone_name=schedule.timezone_name,
        effective_from=schedule.effective_from,
        effective_through=schedule.effective_through,
        is_active=schedule.is_active,
        class_name=school_class.name,
        laboratory_name=laboratory.name,
        teacher_name=teacher.full_name,
        created_at=_timestamp(schedule.created_at),
        updated_at=_timestamp(schedule.updated_at),
    )


def _teacher_role_id(session: Session) -> UUID | None:
    return session.scalar(select(Role.id).where(Role.code == RoleCode.TEACHER.value))


def _validate_references(
    session: Session,
    *,
    class_id: UUID,
    laboratory_id: UUID,
    teacher_user_id: UUID,
    principal: AuthenticatedUser,
) -> None:
    school_class = session.get(SchoolClass, class_id)
    if school_class is None or not school_class.is_active:
        raise ApiProblem(422, "invalid_schedule_class", "Pilih kelas yang aktif.")

    laboratory = session.get(Laboratory, laboratory_id)
    if laboratory is None or not laboratory.is_active:
        raise ApiProblem(
            422, "invalid_schedule_laboratory", "Pilih laboratorium yang aktif."
        )

    teacher = session.get(User, teacher_user_id)
    teacher_role_id = _teacher_role_id(session)
    has_teacher_role = (
        teacher is not None
        and teacher_role_id is not None
        and session.scalar(
            select(UserRole.user_id).where(
                UserRole.user_id == teacher_user_id,
                UserRole.role_id == teacher_role_id,
            )
        )
        is not None
    )
    if teacher is None or not teacher.is_active or not has_teacher_role:
        raise ApiProblem(
            422, "invalid_schedule_teacher", "Pilih guru dengan akun aktif."
        )

    if RoleCode.ADMIN not in principal.roles and teacher_user_id != principal.id:
        raise ApiProblem(
            403,
            "schedule_teacher_scope",
            "Guru hanya dapat mengelola jadwalnya sendiri.",
        )


def _validate_timezone(timezone_name: str) -> None:
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ApiProblem(422, "invalid_timezone", "Zona waktu tidak dikenal.") from exc


def _check_conflict(
    session: Session,
    *,
    schedule_id: UUID | None,
    class_id: UUID,
    laboratory_id: UUID,
    teacher_user_id: UUID,
    weekday: int,
    start_time: time,
    end_time: time,
    effective_from: date,
    effective_through: date | None,
    is_active: bool,
) -> None:
    if not is_active:
        return

    filters = [
        PracticumSchedule.is_active.is_(True),
        PracticumSchedule.weekday == weekday,
        PracticumSchedule.start_time < end_time,
        PracticumSchedule.end_time > start_time,
        or_(
            PracticumSchedule.effective_through.is_(None),
            PracticumSchedule.effective_through >= effective_from,
        ),
        or_(
            PracticumSchedule.class_id == class_id,
            PracticumSchedule.laboratory_id == laboratory_id,
            PracticumSchedule.teacher_user_id == teacher_user_id,
        ),
    ]
    if effective_through is not None:
        filters.append(PracticumSchedule.effective_from <= effective_through)
    query = select(PracticumSchedule).where(*filters)
    if schedule_id is not None:
        query = query.where(PracticumSchedule.id != schedule_id)
    if session.scalar(query.limit(1)) is not None:
        raise ApiProblem(
            409,
            "schedule_conflict",
            "Jadwal bertabrakan untuk kelas, laboratorium, atau guru "
            "pada waktu yang sama.",
        )


@router.get(
    "/teachers",
    response_model=list[ScheduleTeacherResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List active teachers available for schedules",
)
def list_schedule_teachers(
    principal: Annotated[
        AuthenticatedUser, Depends(require_permissions(Permission.SCHEDULE_READ))
    ],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[ScheduleTeacherResponse]:
    if RoleCode.ADMIN not in principal.roles:
        return [ScheduleTeacherResponse(id=principal.id, full_name=principal.full_name)]
    teacher_role_id = _teacher_role_id(session)
    if teacher_role_id is None:
        return []
    teachers = session.scalars(
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .where(UserRole.role_id == teacher_role_id, User.is_active.is_(True))
        .order_by(User.full_name, User.id)
    ).all()
    return [
        ScheduleTeacherResponse(id=user.id, full_name=user.full_name)
        for user in teachers
    ]


@router.get(
    "",
    response_model=PageResponse[ScheduleResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List practicum schedules",
)
def list_schedules(
    principal: Annotated[
        AuthenticatedUser, Depends(require_permissions(Permission.SCHEDULE_READ))
    ],
    session: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    weekday: Annotated[int | None, Query(ge=0, le=6)] = None,
    is_active: bool | None = None,
    class_id: UUID | None = None,
    laboratory_id: UUID | None = None,
) -> PageResponse[ScheduleResponse]:
    filters = []
    if RoleCode.ADMIN not in principal.roles:
        filters.append(PracticumSchedule.teacher_user_id == principal.id)
    if weekday is not None:
        filters.append(PracticumSchedule.weekday == weekday)
    if is_active is not None:
        filters.append(PracticumSchedule.is_active.is_(is_active))
    if class_id is not None:
        filters.append(PracticumSchedule.class_id == class_id)
    if laboratory_id is not None:
        filters.append(PracticumSchedule.laboratory_id == laboratory_id)
    query = select(PracticumSchedule).join(SchoolClass).join(Laboratory)
    if search:
        pattern = f"%{search.strip()}%"
        filters.append(
            or_(
                PracticumSchedule.subject.ilike(pattern),
                SchoolClass.name.ilike(pattern),
                SchoolClass.code.ilike(pattern),
                Laboratory.name.ilike(pattern),
                Laboratory.code.ilike(pattern),
            )
        )
    if filters:
        query = query.where(and_(*filters))
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    schedules = session.scalars(
        query.order_by(PracticumSchedule.weekday, PracticumSchedule.start_time)
        .limit(limit)
        .offset(offset)
    ).all()
    return PageResponse(
        items=[_response(session, item) for item in schedules],
        pagination=Pagination(total=total, limit=limit, offset=offset),
    )


@router.get(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Get a practicum schedule",
)
def get_schedule(
    schedule_id: UUID,
    principal: Annotated[
        AuthenticatedUser, Depends(require_permissions(Permission.SCHEDULE_READ))
    ],
    session: Annotated[Session, Depends(get_db_session)],
) -> ScheduleResponse:
    schedule = session.get(PracticumSchedule, schedule_id)
    if schedule is None or (
        RoleCode.ADMIN not in principal.roles
        and schedule.teacher_user_id != principal.id
    ):
        raise ApiProblem(404, "schedule_not_found", "Jadwal tidak ditemukan.")
    return _response(session, schedule)


@router.post(
    "",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Create a practicum schedule",
)
def create_schedule(
    request: ScheduleCreateRequest,
    principal: Annotated[
        AuthenticatedUser, Depends(require_permissions(Permission.SCHEDULE_MANAGE))
    ],
    session: Annotated[Session, Depends(get_db_session)],
) -> ScheduleResponse:
    _validate_timezone(request.timezone_name)
    _validate_references(
        session,
        class_id=request.class_id,
        laboratory_id=request.laboratory_id,
        teacher_user_id=request.teacher_user_id,
        principal=principal,
    )
    _check_conflict(
        session,
        schedule_id=None,
        class_id=request.class_id,
        laboratory_id=request.laboratory_id,
        teacher_user_id=request.teacher_user_id,
        weekday=request.weekday,
        start_time=request.start_time,
        end_time=request.end_time,
        effective_from=request.effective_from,
        effective_through=request.effective_through,
        is_active=True,
    )
    schedule = PracticumSchedule(**request.model_dump())
    session.add(schedule)
    session.commit()
    session.refresh(schedule)
    return _response(session, schedule)


@router.patch(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Update a practicum schedule",
)
def update_schedule(
    schedule_id: UUID,
    request: ScheduleUpdateRequest,
    principal: Annotated[
        AuthenticatedUser, Depends(require_permissions(Permission.SCHEDULE_MANAGE))
    ],
    session: Annotated[Session, Depends(get_db_session)],
) -> ScheduleResponse:
    schedule = session.get(PracticumSchedule, schedule_id)
    if schedule is None or (
        RoleCode.ADMIN not in principal.roles
        and schedule.teacher_user_id != principal.id
    ):
        raise ApiProblem(404, "schedule_not_found", "Jadwal tidak ditemukan.")
    changes = request.model_dump(exclude_unset=True)
    candidate = {
        field: getattr(schedule, field) for field in ScheduleCreateRequest.model_fields
    }
    candidate["is_active"] = schedule.is_active
    candidate.update(changes)
    if candidate["start_time"] >= candidate["end_time"]:
        raise ApiProblem(
            422, "invalid_schedule_time", "Waktu selesai harus setelah waktu mulai."
        )
    if (
        candidate["effective_through"] is not None
        and candidate["effective_through"] < candidate["effective_from"]
    ):
        raise ApiProblem(
            422,
            "invalid_schedule_window",
            "Tanggal akhir tidak boleh sebelum tanggal mulai.",
        )
    _validate_timezone(candidate["timezone_name"])
    _validate_references(
        session,
        class_id=candidate["class_id"],
        laboratory_id=candidate["laboratory_id"],
        teacher_user_id=candidate["teacher_user_id"],
        principal=principal,
    )
    _check_conflict(
        session,
        schedule_id=schedule_id,
        class_id=candidate["class_id"],
        laboratory_id=candidate["laboratory_id"],
        teacher_user_id=candidate["teacher_user_id"],
        weekday=candidate["weekday"],
        start_time=candidate["start_time"],
        end_time=candidate["end_time"],
        effective_from=candidate["effective_from"],
        effective_through=candidate["effective_through"],
        is_active=candidate["is_active"],
    )
    for field, value in changes.items():
        setattr(schedule, field, value)
    session.commit()
    session.refresh(schedule)
    return _response(session, schedule)
