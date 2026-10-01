from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from presensi_api.db.base import Base

JSON_OBJECT = JSON().with_variant(JSONB(), "postgresql")


class UUIDPrimaryKey:
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class User(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


class Role(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("code", name="uq_roles_code"),)

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))


class UserRole(TimestampMixin, Base):
    __tablename__ = "user_roles"

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    granted_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (Index("ix_user_roles_role_id", "role_id"),)


class Student(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("student_number", name="uq_students_student_number"),
    )

    student_number: Mapped[str] = mapped_column(String(32), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


class SchoolClass(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "classes"
    __table_args__ = (
        UniqueConstraint("code", "academic_year", name="uq_classes_code_academic_year"),
        CheckConstraint("grade BETWEEN 1 AND 12", name="grade_range"),
        Index("ix_classes_homeroom_teacher_id", "homeroom_teacher_id"),
    )

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    grade: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    academic_year: Mapped[str] = mapped_column(String(9), nullable=False)
    homeroom_teacher_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


class ClassStudent(TimestampMixin, Base):
    __tablename__ = "class_students"

    class_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("classes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    student_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("students.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_class_students_student_id", "student_id"),)


class Laboratory(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "laboratories"
    __table_args__ = (UniqueConstraint("code", name="uq_laboratories_code"),)

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


class Device(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint(
            "device_type IN ('edge_pc', 'camera_gateway')", name="device_type"
        ),
        Index("ix_devices_laboratory_id", "laboratory_id"),
    )

    laboratory_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("laboratories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    device_type: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PracticumSchedule(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "practicum_schedules"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("start_time < end_time", name="schedule_time_order"),
        CheckConstraint(
            "effective_through IS NULL OR effective_through >= effective_from",
            name="schedule_date_order",
        ),
        Index("ix_practicum_schedules_class_weekday", "class_id", "weekday"),
        Index("ix_practicum_schedules_laboratory_weekday", "laboratory_id", "weekday"),
        Index("ix_practicum_schedules_teacher_user_id", "teacher_user_id"),
    )

    class_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("classes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    laboratory_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("laboratories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    teacher_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    subject: Mapped[str] = mapped_column(String(120), nullable=False)
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    end_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_through: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


class AttendanceSession(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "attendance_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'closed', 'cancelled')", name="session_status"
        ),
        CheckConstraint("grace_period_minutes >= 0", name="grace_period_nonnegative"),
        CheckConstraint(
            "closed_at IS NULL OR closed_at >= opened_at",
            name="session_close_after_open",
        ),
        Index(
            "uq_attendance_sessions_active_schedule",
            "practicum_schedule_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index("ix_attendance_sessions_opened_by_user_id", "opened_by_user_id"),
    )

    practicum_schedule_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("practicum_schedules.id", ondelete="RESTRICT"),
        nullable=False,
    )
    opened_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default=text("'active'")
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grace_period_minutes: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=15, server_default=text("15")
    )


class SessionStudent(TimestampMixin, Base):
    __tablename__ = "session_students"

    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    student_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("students.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    student_number_snapshot: Mapped[str] = mapped_column(String(32), nullable=False)
    full_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    snapshot_taken_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_session_students_student_id", "student_id"),)


class FaceTemplate(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "face_templates"
    __table_args__ = (
        Index(
            "uq_face_templates_active_student_model_version",
            "student_id",
            "model_name",
            "model_version",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
            sqlite_where=text("revoked_at IS NULL"),
        ),
        Index("ix_face_templates_created_by_user_id", "created_by_user_id"),
        Index("ix_face_templates_revoked_by_user_id", "revoked_by_user_id"),
    )

    student_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("students.id", ondelete="RESTRICT"),
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    quality_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON_OBJECT, nullable=False, default=dict
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class RecognitionEvent(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "recognition_events"
    __table_args__ = (
        UniqueConstraint("event_uuid", name="uq_recognition_events_event_uuid"),
        CheckConstraint(
            "outcome IN ('matched', 'ambiguous', 'no_match', 'error')",
            name="event_outcome",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        CheckConstraint(
            "margin IS NULL OR (margin >= 0 AND margin <= 1)", name="margin_range"
        ),
        CheckConstraint(
            "outcome != 'matched' OR recognized_student_id IS NOT NULL",
            name="matched_event_has_student",
        ),
        Index("ix_recognition_events_session_occurred_at", "session_id", "occurred_at"),
        Index("ix_recognition_events_device_occurred_at", "device_id", "occurred_at"),
        Index(
            "ix_recognition_events_student_occurred_at",
            "recognized_student_id",
            "occurred_at",
        ),
    )

    event_uuid: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("attendance_sessions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    device_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("devices.id", ondelete="RESTRICT"),
        nullable=False,
    )
    recognized_student_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("students.id", ondelete="SET NULL")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    margin: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    quality_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON_OBJECT, nullable=False, default=dict
    )


class AttendanceRecord(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "student_id", name="uq_attendance_records_session_student"
        ),
        UniqueConstraint(
            "recognition_event_id", name="uq_attendance_records_recognition_event"
        ),
        CheckConstraint(
            "status IN ('present', 'late', 'absent', 'excused')",
            name="attendance_status",
        ),
        CheckConstraint(
            "source IN ('face_recognition', 'manual', 'system')",
            name="attendance_source",
        ),
        CheckConstraint(
            "(source = 'face_recognition' AND recognition_event_id IS NOT NULL) OR "
            "(source IN ('manual', 'system') AND recognition_event_id IS NULL)",
            name="attendance_source_event_consistency",
        ),
        Index("ix_attendance_records_student_id", "student_id"),
        Index("ix_attendance_records_recorded_by_user_id", "recorded_by_user_id"),
    )

    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("attendance_sessions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    student_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("students.id", ondelete="RESTRICT"),
        nullable=False,
    )
    recognition_event_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("recognition_events.id", ondelete="RESTRICT")
    )
    recorded_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AttendanceCorrection(UUIDPrimaryKey, TimestampMixin, Base):
    __tablename__ = "attendance_corrections"
    __table_args__ = (
        CheckConstraint(
            "previous_status IN ('present', 'late', 'absent', 'excused')",
            name="correction_previous_status",
        ),
        CheckConstraint(
            "corrected_status IN ('present', 'late', 'absent', 'excused')",
            name="correction_corrected_status",
        ),
        CheckConstraint(
            "decision_status IN ('pending', 'approved', 'rejected')",
            name="correction_decision",
        ),
        CheckConstraint("length(trim(reason)) > 0", name="correction_reason_required"),
        CheckConstraint(
            "(decision_status = 'pending' AND decided_at IS NULL AND "
            "decided_by_user_id IS NULL) OR "
            "(decision_status IN ('approved', 'rejected') AND "
            "decided_at IS NOT NULL AND "
            "decided_by_user_id IS NOT NULL)",
            name="correction_decision_consistency",
        ),
        Index("ix_attendance_corrections_attendance_record_id", "attendance_record_id"),
        Index("ix_attendance_corrections_requested_by_user_id", "requested_by_user_id"),
    )

    attendance_record_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("attendance_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    requested_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decided_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    previous_status: Mapped[str] = mapped_column(String(16), nullable=False)
    corrected_status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decision_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default=text("'pending'")
    )
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(UUIDPrimaryKey, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_actor_created_at", "actor_user_id", "created_at"),
        Index(
            "ix_audit_logs_entity_created_at", "entity_type", "entity_id", "created_at"
        ),
    )

    actor_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    request_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    before_state: Mapped[dict[str, object] | None] = mapped_column(JSON_OBJECT)
    after_state: Mapped[dict[str, object] | None] = mapped_column(JSON_OBJECT)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
