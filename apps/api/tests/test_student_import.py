from __future__ import annotations

import asyncio
from collections.abc import Generator
from io import BytesIO
from uuid import UUID

import httpx
import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from presensi_api.api.security.dependencies import get_current_user
from presensi_api.api.security.roles import AuthenticatedUser, RoleCode
from presensi_api.api.v1.routers.student_imports import MAX_FILE_BYTES
from presensi_api.db.base import Base
from presensi_api.db.models import ClassStudent, SchoolClass, Student
from presensi_api.db.session import get_db_session
from presensi_api.main import app


@pytest.fixture
def api_database() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    principal = AuthenticatedUser(
        id=UUID(int=84),
        email="admin@example.test",
        full_name="Import Test Admin",
        roles=frozenset({RoleCode.ADMIN}),
    )
    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_user] = lambda: principal
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


def add_class(factory: sessionmaker[Session], code: str = "XI-A") -> UUID:
    with factory.begin() as session:
        school_class = SchoolClass(
            code=code,
            name=f"Class {code}",
            grade=11,
            academic_year="2026-2027",
        )
        session.add(school_class)
        session.flush()
        return school_class.id


def upload_request(
    path: str,
    content: bytes,
    *,
    filename: str = "students.csv",
    content_type: str = "text/csv",
    student_number_column: str = "NIS",
    full_name_column: str = "Nama",
    class_code_column: str = "Kelas",
) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.post(
                path,
                files={"upload": (filename, content, content_type)},
                data={
                    "student_number_column": student_number_column,
                    "full_name_column": full_name_column,
                    "class_code_column": class_code_column,
                },
            )

    return asyncio.run(send())


def test_csv_preview_and_commit_create_students_and_class_links_atomically(
    api_database: sessionmaker[Session],
) -> None:
    class_id = add_class(api_database)
    content = (
        "NIS,Nama,Kelas\n"
        "  s-101 ,Synthetic Student One,XI-A\n"
        "s-102,Synthetic Student Two,xi-a\n"
    ).encode()

    preview = upload_request("/api/v1/students/import/preview", content)

    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["total_rows"] == 2
    assert preview_body["valid_rows"] == 2
    assert preview_body["invalid_rows"] == 0
    assert preview_body["can_commit"] is True
    assert preview_body["rows"][0]["student_number"] == "S-101"
    with api_database() as session:
        assert session.scalar(select(func.count()).select_from(Student)) == 0

    committed = upload_request("/api/v1/students/import/commit", content)

    assert committed.status_code == 201
    assert committed.json() == {"imported_count": 2, "class_memberships_created": 2}
    with api_database() as session:
        assert session.scalar(select(func.count()).select_from(Student)) == 2
        assert session.scalar(select(func.count()).select_from(ClassStudent)) == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(ClassStudent)
                .where(ClassStudent.class_id == class_id)
            )
            == 2
        )


def test_preview_reports_duplicate_empty_name_unknown_class_and_existing_id(
    api_database: sessionmaker[Session],
) -> None:
    add_class(api_database)
    with api_database.begin() as session:
        session.add(Student(student_number="EXISTING", full_name="Existing Synthetic"))
    content = (
        "NIS,Nama,Kelas\n"
        "EXISTING,Already Saved,XI-A\n"
        "NEW-1,,XI-A\n"
        "NEW-2,Unknown Room,NO-SUCH-CLASS\n"
        "DUP-1,First Duplicate,XI-A\n"
        "DUP-1,Second Duplicate,XI-A\n"
    ).encode()

    preview = upload_request("/api/v1/students/import/preview", content)

    assert preview.status_code == 200
    body = preview.json()
    assert body["total_rows"] == 5
    assert body["valid_rows"] == 1
    assert body["invalid_rows"] == 4
    assert body["can_commit"] is False
    row_errors = {row["row_number"]: row["errors"] for row in body["rows"]}
    assert "NIS/NISN sudah terdaftar." in row_errors[2]
    assert "Nama siswa wajib diisi." in row_errors[3]
    assert any("tidak ditemukan" in message for message in row_errors[4])
    assert "NIS/NISN duplikat di dalam file." in row_errors[6]

    refused = upload_request("/api/v1/students/import/commit", content)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "import_rows_invalid"
    assert len(refused.json()["error"]["details"]) >= 4
    with api_database() as session:
        assert session.scalar(select(func.count()).select_from(Student)) == 1


def test_xlsx_preview_uses_the_same_header_mapping_and_validation(
    api_database: sessionmaker[Session],
) -> None:
    add_class(api_database)
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["School ID", "Student Name", "Class Code"])
    sheet.append(["S-201", "Synthetic XLSX Student", "XI-A"])
    output = BytesIO()
    workbook.save(output)

    response = upload_request(
        "/api/v1/students/import/preview",
        output.getvalue(),
        filename="students.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        student_number_column="School ID",
        full_name_column="Student Name",
        class_code_column="Class Code",
    )

    assert response.status_code == 200
    assert response.json()["can_commit"] is True
    assert response.json()["rows"][0]["full_name"] == "Synthetic XLSX Student"


@pytest.mark.parametrize(
    ("filename", "content_type", "content", "expected_status"),
    [
        ("students.csv", "image/png", b"NIS,Nama,Kelas\n", 415),
        ("students.txt", "text/csv", b"NIS,Nama,Kelas\n", 415),
        ("students.csv", "text/csv", b"x" * (MAX_FILE_BYTES + 1), 413),
    ],
    ids=["mime-mismatch", "unsupported-extension", "oversized-file"],
)
def test_import_validates_extension_mime_and_size(
    api_database: sessionmaker[Session],
    filename: str,
    content_type: str,
    content: bytes,
    expected_status: int,
) -> None:
    response = upload_request(
        "/api/v1/students/import/preview",
        content,
        filename=filename,
        content_type=content_type,
    )
    assert response.status_code == expected_status


def test_import_requires_explicit_existing_column_mappings(
    api_database: sessionmaker[Session],
) -> None:
    response = upload_request(
        "/api/v1/students/import/preview",
        b"NIS,Nama,Kelas\nS-301,Student,XI-A\n",
        student_number_column="Student ID",
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_column_mapping"
