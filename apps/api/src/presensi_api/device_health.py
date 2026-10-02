from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from presensi_api.db.models import Device


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
    return "online" if device.camera_status == "online" else "warning"
