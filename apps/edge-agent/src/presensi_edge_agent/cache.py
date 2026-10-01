from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from uuid import UUID

from recognition_core.domain import FaceEmbedding, GalleryEntry


class CacheSchemaError(ValueError):
    """Raised when a session cache response is unsafe or malformed."""


DEFAULT_MAX_OFFLINE_SECONDS = 300.0


@dataclass(frozen=True, slots=True)
class CachedStudent:
    student_id: UUID
    student_number: str
    full_name: str
    templates: tuple[FaceEmbedding, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class SessionCacheBundle:
    device_id: UUID
    session_id: UUID
    session_status: str
    generated_at: datetime
    session_ends_at: datetime
    expires_at: datetime
    model_name: str
    model_version: str
    students: tuple[CachedStudent, ...] = field(repr=False)

    def __repr__(self) -> str:
        return (
            "SessionCacheBundle("
            f"device_id={self.device_id!r}, session_id={self.session_id!r}, "
            f"session_status={self.session_status!r}, "
            f"student_count={len(self.students)}, "
            "template_count="
            f"{sum(len(student.templates) for student in self.students)})"
        )

    def gallery(self) -> tuple[GalleryEntry, ...]:
        return tuple(
            GalleryEntry(student_id=student.student_id, embedding=template)
            for student in self.students
            for template in student.templates
            if template.model_name == self.model_name
            and template.model_version == self.model_version
        )


class SessionCacheProvider(Protocol):
    def fetch_active_session_cache(self) -> SessionCacheBundle: ...


def _object(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise CacheSchemaError(f"Invalid cache field: {field_name}.")
    return cast(dict[str, object], value)


def _required_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CacheSchemaError(f"Invalid cache field: {key}.")
    return value


def _uuid(data: dict[str, object], key: str) -> UUID:
    try:
        return UUID(_required_string(data, key))
    except ValueError as exc:
        raise CacheSchemaError(f"Invalid cache field: {key}.") from exc


def _timestamp(data: dict[str, object], key: str) -> datetime:
    value = _required_string(data, key)
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CacheSchemaError(f"Invalid cache field: {key}.") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise CacheSchemaError(f"Invalid cache field: {key}.")
    return timestamp.astimezone(UTC)


def _template(value: object, model_name: str, model_version: str) -> FaceEmbedding:
    data = _object(value, "roster.templates[]")
    candidate_model = _required_string(data, "model_name")
    candidate_version = _required_string(data, "model_version")
    vector = data.get("values")
    if not isinstance(vector, list) or not vector:
        raise CacheSchemaError("Invalid cache field: roster.templates[].values.")
    try:
        values = tuple(float(item) for item in vector)
    except (TypeError, ValueError) as exc:
        raise CacheSchemaError("Invalid cache template values.") from exc
    if not all(math.isfinite(item) for item in values):
        raise CacheSchemaError("Invalid cache template values.")
    normalized = data.get("normalized") is True
    if not normalized:
        raise CacheSchemaError("Cache templates must be L2 normalized.")
    if candidate_model != model_name or candidate_version != model_version:
        raise CacheSchemaError("Cache template model version does not match the agent.")
    return FaceEmbedding(
        values=values,
        model_name=candidate_model,
        model_version=candidate_version,
        normalized=normalized,
    )


def parse_session_cache(
    payload: object,
    *,
    device_id: UUID,
    model_name: str,
    model_version: str,
    max_offline_seconds: float = DEFAULT_MAX_OFFLINE_SECONDS,
    now: datetime | None = None,
) -> SessionCacheBundle:
    data = _object(payload, "root")
    returned_device_id = _uuid(data, "device_id")
    if returned_device_id != device_id:
        raise CacheSchemaError("Cache belongs to a different device.")
    if _required_string(data, "session_status") != "active":
        raise CacheSchemaError("Cache session is not active.")
    generated_at = _timestamp(data, "generated_at")
    session_ends_at = _timestamp(data, "session_ends_at")
    expires_at = _timestamp(data, "expires_at")
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    if (
        not math.isfinite(max_offline_seconds)
        or max_offline_seconds <= 0
        or max_offline_seconds > 86400
    ):
        raise ValueError("max_offline_seconds must be between 0 and 86400.")
    # Server expiry is authoritative; the local freshness policy can only
    # shorten it. An old bundle can never be made valid by a distant expiry.
    expires_at = min(
        expires_at,
        session_ends_at,
        generated_at + timedelta(seconds=max_offline_seconds),
    )
    if (
        expires_at <= current_time
        or generated_at > current_time
        or session_ends_at <= current_time
    ):
        raise CacheSchemaError("Cache is expired or has an invalid timestamp.")
    returned_model_name = _required_string(data, "model_name")
    returned_model_version = _required_string(data, "model_version")
    if returned_model_name != model_name or returned_model_version != model_version:
        raise CacheSchemaError("Cache model version does not match the agent.")
    raw_roster = data.get("roster")
    if not isinstance(raw_roster, list):
        raise CacheSchemaError("Invalid cache field: roster.")
    students: list[CachedStudent] = []
    for raw_student in raw_roster:
        student = _object(raw_student, "roster[]")
        raw_templates = student.get("templates")
        if not isinstance(raw_templates, list):
            raise CacheSchemaError("Invalid cache field: roster[].templates.")
        templates = tuple(
            _template(item, returned_model_name, returned_model_version)
            for item in raw_templates
        )
        students.append(
            CachedStudent(
                student_id=_uuid(student, "student_id"),
                student_number=_required_string(student, "student_number"),
                full_name=_required_string(student, "full_name"),
                templates=templates,
            )
        )
    return SessionCacheBundle(
        device_id=returned_device_id,
        session_id=_uuid(data, "session_id"),
        session_status="active",
        generated_at=generated_at,
        session_ends_at=session_ends_at,
        expires_at=expires_at,
        model_name=returned_model_name,
        model_version=returned_model_version,
        students=tuple(students),
    )


class ActiveSessionCache:
    """Thread-safe, memory-only snapshot; face vectors are never written to disk."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._bundle: SessionCacheBundle | None = None

    def replace(self, bundle: SessionCacheBundle) -> None:
        with self._lock:
            self._bundle = bundle

    def current(self, *, now: datetime | None = None) -> SessionCacheBundle | None:
        with self._lock:
            bundle = self._bundle
            if bundle is None:
                return None
            current_time = (now or datetime.now(UTC)).astimezone(UTC)
            if bundle.expires_at <= current_time:
                self._bundle = None
                return None
            return bundle

    def clear(self) -> None:
        with self._lock:
            self._bundle = None
