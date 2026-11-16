"""In-process display-change notifications for kiosk SSE streams.

Same-process push: write paths (manual marks, recognition decisions,
session open/close) bump a monotonic version so `_live_event_generator`
re-queries immediately instead of waiting for the next 1 s tick. The
generator keeps a periodic safety re-query (multi-worker fallback: an
event in another uvicorn worker still surfaces at the next safety tick).

Cross-process channel name (reserved, documented): PostgreSQL
``NOTIFY presensi_display_changed, '<laboratory_id>'``. Emitted
best-effort by the same write paths; no LISTENer is attached yet. A
future multi-worker deployment can attach one without touching writers.
"""

from __future__ import annotations

import threading
import time

_CHANNEL = "presensi_display_changed"
_lock = threading.Condition()
_version = 0


def display_notify_channel() -> str:
    """Reserved Postgres NOTIFY channel for display changes."""
    return _CHANNEL


def current_display_version() -> int:
    with _lock:
        return _version


def notify_display_changed() -> int:
    """Bump the version and wake SSE generators in this process."""
    global _version
    with _lock:
        _version += 1
        _lock.notify_all()
        return _version


def wait_for_display_version(last_seen: int, timeout_seconds: float) -> int:
    """Block until the version changes or the timeout elapses."""
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    with _lock:
        while _version == last_seen:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            _lock.wait(timeout=remaining)
        return _version


def pg_notify_display_changed(session: object, laboratory_id: object) -> None:
    """Best-effort cross-process NOTIFY (fires on commit, ignored if unavailable)."""
    try:
        execute = getattr(session, "execute", None)
        if execute is None:
            return
        from sqlalchemy import text as _text

        execute(
            _text("SELECT pg_notify(:channel, :payload)"),
            {"channel": _CHANNEL, "payload": str(laboratory_id)},
        )
    except Exception:
        return
