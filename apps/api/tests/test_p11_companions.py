"""P1-1 companion tests: camera-health matrix + matching performance budget.

Synthetic fixtures only — no real student/minor data, no images committed.
"""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

from presensi_api.db.models import Device
from presensi_api.device_health import (
    device_health_status,
    has_recent_heartbeat,
    heartbeat_timeout_seconds,
)
from recognition_core.domain import FaceEmbedding, GalleryEntry
from recognition_core.matching import CosineSimilarityMatcher


def _device(**overrides: object) -> Device:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "is_active": True,
        "last_seen_at": now,
        "camera_enabled": True,
        "camera_status": "online",
    }
    values.update(overrides)
    return Device(**values)


def test_camera_health_matrix_online_warning_offline() -> None:
    now = datetime.now(UTC)
    assert device_health_status(_device(last_seen_at=now)) == "online"
    assert (
        device_health_status(_device(last_seen_at=now, camera_status="offline"))
        == "warning"
    )
    assert (
        device_health_status(_device(last_seen_at=now, camera_enabled=False))
        == "warning"
    )
    assert device_health_status(_device(is_active=False)) == "offline"
    assert device_health_status(_device(last_seen_at=None)) == "offline"
    stale = now - timedelta(seconds=heartbeat_timeout_seconds() + 5)
    assert device_health_status(_device(last_seen_at=stale)) == "offline"
    assert has_recent_heartbeat(_device(last_seen_at=stale)) is False


def test_heartbeat_timeout_is_clamped(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PRESENSI_DEVICE_HEARTBEAT_TIMEOUT_SECONDS", "1")
    assert heartbeat_timeout_seconds() == 5
    monkeypatch.setenv("PRESENSI_DEVICE_HEARTBEAT_TIMEOUT_SECONDS", "99999")
    assert heartbeat_timeout_seconds() == 3600
    monkeypatch.setenv("PRESENSI_DEVICE_HEARTBEAT_TIMEOUT_SECONDS", "not-a-number")
    assert heartbeat_timeout_seconds() == 60
    monkeypatch.delenv("PRESENSI_DEVICE_HEARTBEAT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("DEVICE_ONLINE_THRESHOLD_SECONDS", "120")
    assert heartbeat_timeout_seconds() == 120


def _unit_vector(seed: int, dim: int = 64) -> tuple[float, ...]:
    raw = [math.sin(seed * 12.9898 + i * 78.233) for i in range(dim)]
    norm = math.sqrt(sum(value * value for value in raw))
    return tuple(value / norm for value in raw)


def test_matching_accuracy_and_time_budget_on_large_synthetic_gallery() -> None:
    students = [UUID(int=1000 + index) for index in range(300)]
    gallery: list[GalleryEntry] = []
    for index, student_id in enumerate(students):
        base = _unit_vector(index)
        gallery.append(
            GalleryEntry(
                student_id=student_id,
                embedding=FaceEmbedding(
                    values=base,
                    model_name="synthetic",
                    model_version="p11",
                    normalized=True,
                ),
            )
        )
        gallery.append(
            GalleryEntry(
                student_id=student_id,
                embedding=FaceEmbedding(
                    values=_unit_vector(index + 10_000),
                    model_name="synthetic",
                    model_version="p11",
                    normalized=True,
                ),
            )
        )
    target = students[150]
    probe = FaceEmbedding(
        values=_unit_vector(150),
        model_name="synthetic",
        model_version="p11",
        normalized=True,
    )
    matcher = CosineSimilarityMatcher()
    started = time.perf_counter()
    matches = matcher.match(probe, gallery, limit=5)
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert matches[0].student_id == target
    assert matches[0].similarity > 0.99
    assert elapsed_ms < 2000, f"matching took {elapsed_ms:.1f}ms"
