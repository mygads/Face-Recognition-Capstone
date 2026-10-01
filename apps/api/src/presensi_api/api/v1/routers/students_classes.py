from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.dependencies import require_permissions
from presensi_api.api.security.roles import Permission
from presensi_api.api.v1.schemas.common import PageResponse, Pagination
from presensi_api.api.v1.schemas.students import (
    ClassCreateRequest,
    ClassDetailResponse,
    ClassResponse,
    ClassStudentCreateRequest,
    ClassStudentResponse,
    ClassUpdateRequest,
    StudentClassResponse,
    StudentCreateRequest,
    StudentDetailResponse,
    StudentResponse,
    StudentUpdateRequest,
)
from presensi_api.db.models import ClassStudent, SchoolClass, Student, User
from presensi_api.db.session import get_db_session

router = APIRouter(tags=["students", "classes"])
DbSession = Annotated[Session, Depends(get_db_session)]
T = TypeVar("T")


def _timestamp(value: datetime) -> datetime:
    # SQLite drops tzinfo when materializing DateTime(timezone=True).
    # PostgreSQL preserves it.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _student_response(student: Student) -> StudentResponse:
    return StudentResponse(
        id=student.id,
        student_number=student.student_number,
        full_name=student.full_name,
        is_active=student.is_active,
        created_at=_timestamp(student.created_at),
        updated_at=_timestamp(student.updated_at),
    )


def _class_response(school_class: SchoolClass) -> ClassResponse:
    return ClassResponse(
        id=school_class.id,
        code=school_class.code,
        name=school_class.name,
        grade=school_class.grade,
        academic_year=school_class.academic_year,
        homeroom_teacher_id=school_class.homeroom_teacher_id,
        is_active=school_class.is_active,
        created_at=_timestamp(school_class.created_at),
        updated_at=_timestamp(school_class.updated_at),
    )


def _not_found(resource: str) -> ApiProblem:
    return ApiProblem(404, "not_found", f"{resource} was not found.")


def _commit(session: Session, *, duplicate_code: str, duplicate_message: str) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiProblem(409, duplicate_code, duplicate_message) from exc


def _page(items: list[T], total: int, limit: int, offset: int) -> PageResponse[T]:
    return PageResponse(
        items=items,
        pagination=Pagination(total=total, limit=limit, offset=offset),
    )


@router.get(
    "/students",
    response_model=PageResponse[StudentResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List students",
    dependencies=[Depends(require_permissions(Permission.ROSTER_READ))],
)
def list_students(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(max_length=200)] = None,
    is_active: bool | None = None,
) -> PageResponse[StudentResponse]:
    query = select(Student)
    count_query = select(func.count()).select_from(Student)
    filters = []
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        filters.append(
            or_(Student.student_number.ilike(pattern), Student.full_name.ilike(pattern))
        )
    if is_active is not None:
        filters.append(Student.is_active.is_(is_active))
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)
    total = session.scalar(count_query) or 0
    students = session.scalars(
        query.order_by(Student.student_number, Student.id).limit(limit).offset(offset)
    ).all()
    return _page(
        [_student_response(student) for student in students], total, limit, offset
    )


@router.post(
    "/students",
    response_model=StudentResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Create a student",
    dependencies=[Depends(require_permissions(Permission.MANAGE_MASTER_DATA))],
)
def create_student(
    request: StudentCreateRequest, session: DbSession
) -> StudentResponse:
    duplicate = session.scalar(
        select(Student.id).where(
            func.lower(Student.student_number) == request.student_number.lower()
        )
    )
    if duplicate:
        raise ApiProblem(
            409, "duplicate_student_number", "NIS/NISN siswa sudah digunakan."
        )
    student = Student(
        student_number=request.student_number, full_name=request.full_name
    )
    session.add(student)
    _commit(
        session,
        duplicate_code="duplicate_student_number",
        duplicate_message="NIS/NISN siswa sudah digunakan.",
    )
    session.refresh(student)
    return _student_response(student)


@router.get(
    "/students/{student_id}",
    response_model=StudentDetailResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Get student details",
    dependencies=[Depends(require_permissions(Permission.ROSTER_READ))],
)
def get_student(student_id: UUID, session: DbSession) -> StudentDetailResponse:
    student = session.get(Student, student_id)
    if student is None:
        raise _not_found("Student")
    memberships = session.execute(
        select(
            SchoolClass.id,
            SchoolClass.code,
            SchoolClass.name,
            SchoolClass.academic_year,
        )
        .join(ClassStudent, ClassStudent.class_id == SchoolClass.id)
        .where(ClassStudent.student_id == student_id)
        .order_by(SchoolClass.academic_year.desc(), SchoolClass.code)
    ).all()
    return StudentDetailResponse(
        **_student_response(student).model_dump(),
        classes=[
            StudentClassResponse(**membership._mapping) for membership in memberships
        ],
    )


@router.patch(
    "/students/{student_id}",
    response_model=StudentResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Update or deactivate a student",
    dependencies=[Depends(require_permissions(Permission.MANAGE_MASTER_DATA))],
)
def update_student(
    student_id: UUID, request: StudentUpdateRequest, session: DbSession
) -> StudentResponse:
    student = session.get(Student, student_id)
    if student is None:
        raise _not_found("Student")
    changes = request.model_dump(exclude_unset=True)
    if "student_number" in changes:
        duplicate = session.scalar(
            select(Student.id).where(
                func.lower(Student.student_number) == changes["student_number"].lower(),
                Student.id != student_id,
            )
        )
        if duplicate:
            raise ApiProblem(
                409, "duplicate_student_number", "NIS/NISN siswa sudah digunakan."
            )
    for key, value in changes.items():
        setattr(student, key, value)
    _commit(
        session,
        duplicate_code="duplicate_student_number",
        duplicate_message="NIS/NISN siswa sudah digunakan.",
    )
    session.refresh(student)
    return _student_response(student)


@router.get(
    "/classes",
    response_model=PageResponse[ClassResponse],
    responses=OPENAPI_ERROR_RESPONSES,
    summary="List classes",
    dependencies=[Depends(require_permissions(Permission.ROSTER_READ))],
)
def list_classes(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(max_length=200)] = None,
    is_active: bool | None = None,
) -> PageResponse[ClassResponse]:
    query = select(SchoolClass)
    count_query = select(func.count()).select_from(SchoolClass)
    filters = []
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        filters.append(
            or_(SchoolClass.code.ilike(pattern), SchoolClass.name.ilike(pattern))
        )
    if is_active is not None:
        filters.append(SchoolClass.is_active.is_(is_active))
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)
    total = session.scalar(count_query) or 0
    classes = session.scalars(
        query.order_by(SchoolClass.academic_year.desc(), SchoolClass.code)
        .limit(limit)
        .offset(offset)
    ).all()
    return _page([_class_response(row) for row in classes], total, limit, offset)


@router.post(
    "/classes",
    response_model=ClassResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Create a class",
    dependencies=[Depends(require_permissions(Permission.MANAGE_MASTER_DATA))],
)
def create_class(request: ClassCreateRequest, session: DbSession) -> ClassResponse:
    if (
        request.homeroom_teacher_id
        and session.get(User, request.homeroom_teacher_id) is None
    ):
        raise ApiProblem(422, "invalid_teacher", "Guru wali kelas tidak ditemukan.")
    school_class = SchoolClass(**request.model_dump())
    session.add(school_class)
    _commit(
        session,
        duplicate_code="duplicate_class_code",
        duplicate_message="Kode kelas sudah digunakan pada tahun ajaran tersebut.",
    )
    session.refresh(school_class)
    return _class_response(school_class)


@router.get(
    "/classes/{class_id}",
    response_model=ClassDetailResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Get class details and roster",
    dependencies=[Depends(require_permissions(Permission.ROSTER_READ))],
)
def get_class(class_id: UUID, session: DbSession) -> ClassDetailResponse:
    school_class = session.get(SchoolClass, class_id)
    if school_class is None:
        raise _not_found("Class")
    students = session.scalars(
        select(Student)
        .join(ClassStudent, ClassStudent.student_id == Student.id)
        .where(ClassStudent.class_id == class_id)
        .order_by(Student.student_number)
    ).all()
    return ClassDetailResponse(
        **_class_response(school_class).model_dump(),
        students=[
            ClassStudentResponse(
                id=row.id,
                student_number=row.student_number,
                full_name=row.full_name,
                is_active=row.is_active,
            )
            for row in students
        ],
    )


@router.patch(
    "/classes/{class_id}",
    response_model=ClassResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Update or deactivate a class",
    dependencies=[Depends(require_permissions(Permission.MANAGE_MASTER_DATA))],
)
def update_class(
    class_id: UUID, request: ClassUpdateRequest, session: DbSession
) -> ClassResponse:
    school_class = session.get(SchoolClass, class_id)
    if school_class is None:
        raise _not_found("Class")
    changes = request.model_dump(exclude_unset=True)
    teacher_id = changes.get("homeroom_teacher_id", school_class.homeroom_teacher_id)
    if teacher_id and session.get(User, teacher_id) is None:
        raise ApiProblem(422, "invalid_teacher", "Guru wali kelas tidak ditemukan.")
    for key, value in changes.items():
        setattr(school_class, key, value)
    _commit(
        session,
        duplicate_code="duplicate_class_code",
        duplicate_message="Kode kelas sudah digunakan pada tahun ajaran tersebut.",
    )
    session.refresh(school_class)
    return _class_response(school_class)


@router.post(
    "/classes/{class_id}/students",
    response_model=ClassStudentResponse,
    status_code=status.HTTP_201_CREATED,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Enroll a student in a class",
    dependencies=[Depends(require_permissions(Permission.MANAGE_MASTER_DATA))],
)
def add_student_to_class(
    class_id: UUID, request: ClassStudentCreateRequest, session: DbSession
) -> ClassStudentResponse:
    school_class = session.get(SchoolClass, class_id)
    student = session.get(Student, request.student_id)
    if school_class is None:
        raise _not_found("Class")
    if student is None:
        raise _not_found("Student")
    if not school_class.is_active or not student.is_active:
        raise ApiProblem(409, "inactive_roster_member", "Kelas dan siswa harus aktif.")
    link = ClassStudent(class_id=class_id, student_id=student.id)
    session.add(link)
    _commit(
        session,
        duplicate_code="duplicate_class_membership",
        duplicate_message="Siswa sudah terdaftar di kelas tersebut.",
    )
    return ClassStudentResponse(
        id=student.id,
        student_number=student.student_number,
        full_name=student.full_name,
        is_active=student.is_active,
    )


@router.delete(
    "/classes/{class_id}/students/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Remove a student from a class",
    dependencies=[Depends(require_permissions(Permission.MANAGE_MASTER_DATA))],
)
def remove_student_from_class(
    class_id: UUID, student_id: UUID, session: DbSession
) -> None:
    link = session.get(ClassStudent, (class_id, student_id))
    if link is None:
        raise _not_found("Class membership")
    session.delete(link)
    session.commit()
