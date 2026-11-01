from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from presensi_api.db.models import Device

DEFAULT_QUEUE_WARNING_DEPTH = 50
MAX_QUEUE_WARNING_DEPTH = 100_000


def queue_warning_depth() -> int:
    raw = os.getenv("PRESENSI_DEVICE_QUEUE_WARNING_DEPTH", "50")
    try:
        configured = int(raw)
    except ValueError:
        return DEFAULT_QUEUE_WARNING_DEPTH
    return min(max(configured, 1), MAX_QUEUE_WARNING_DEPTH)


def heartbeat_timeout_seconds() -> int:
    raw = os.getenv(
        "PRESENSI_DEVICE_HEARTBEAT_TIMEOUT_SECONDS",
        os.getenv("DEVICE_ONLINE_THRESHOLD_SECONDS", "60"),
    )
    try:
        configured = int(raw)
    except ValueError:
        return 60
    return min(max(configured, 5), 3600)


def has_recent_heartbeat(device: Device, *, now: datetime | None = None) -> bool:
    if not device.is_active or device.last_seen_at is None:
        return False
    current = now or datetime.now(UTC)
    last_seen = device.last_seen_at
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    return current - last_seen <= timedelta(seconds=heartbeat_timeout_seconds())


def device_health_status(device: Device, *, now: datetime | None = None) -> str:
    if not has_recent_heartbeat(device, now=now):
        return "offline"
    if not device.camera_enabled:
        return "warning"
    pending = getattr(device, "pending_events", None)
    dead_letter = getattr(device, "dead_letter_events", None)
    if isinstance(dead_letter, int) and dead_letter > 0:
        return "warning"
    if isinstance(pending, int) and pending >= queue_warning_depth():
        return "warning"
    return "online" if device.camera_status == "online" else "warning"
