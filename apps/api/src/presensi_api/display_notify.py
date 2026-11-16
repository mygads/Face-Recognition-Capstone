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


# ---------------------------------------------------------------------------
# True cross-process push: PostgreSQL LISTEN (tahap dua selesai).
#
# ``pg_notify_display_changed`` (di atas) disiarkan saat commit oleh write
# path. Fungsi di bawah memasang LISTENer per proses API: satu daemon thread
# dengan koneksi psycopg3 khusus yang mem-blokir maksimal 1 detik per
# putaran dan memajukan versi in-process setiap ada NOTIFY. Generator SSE
# yang sedang menunggu langsung bangun (< 100 ms antar proses), bukan
# menunggu safety tick 10 detik. Tanpa Postgres (sqlite/dev) atau bila
# koneksi gagal, thread mundur dengan backoff dan safety tick tetap
# menjamin delivery — tidak pernah crash.
# ---------------------------------------------------------------------------

import logging as _logging
import os as _os

_listener_log = _logging.getLogger("presensi_api.display_notify")
_listener_lock = threading.Lock()
_listener_state: dict[str, object] = {"thread": None, "stop": None}


def sqlalchemy_url_to_psycopg_dsn(url: str | None) -> str | None:
    """Ubah DATABASE_URL SQLAlchemy menjadi DSN psycopg3, atau None.

    Menerima ``postgresql://`` / ``postgres://`` /
    ``postgresql+psycopg://``. Selain itu (sqlite, dsb.) -> None agar
    listener tidak dipasang di lingkungan dev/test.
    """
    if not url:
        return None
    text = url.strip()
    for prefix in ("postgresql+psycopg://", "postgres://", "postgresql://"):
        if text.startswith(prefix):
            return "postgresql://" + text[len(prefix):]
    return None


def handle_pg_notification(payload: object) -> int:
    """Terima satu NOTIFY Postgres dan bangunkan generator SSE proses ini.

    Payload membawa laboratory_id (string); generator memfilter lewat
    query+diff sehingga payload hanya dipakai sebagai pemicu bangun.
    """
    _ = payload
    return notify_display_changed()


def _drain_pg_notifies(conn: object, *, timeout: float = 0.0) -> int:
    """Proses NOTIFY yang tersedia pada koneksi; kembalikan jumlahnya.

    ``timeout=0`` hanya poll sekali (dipakai test dengan koneksi stub).
    """
    notifies = getattr(conn, "notifies", None)
    if notifies is None:
        return 0
    handled = 0
    for notify in notifies(timeout=timeout):
        handle_pg_notification(getattr(notify, "payload", None))
        handled += 1
    return handled


def _pg_listener_loop(
    stop_event: threading.Event,
    dsn: str,
    *,
    poll_seconds: float = 1.0,
    reconnect_delay: float = 5.0,
) -> None:
    """Loop daemon: LISTEN lalu bangunkan versi setiap ada NOTIFY."""
    try:
        import psycopg as _psycopg
    except Exception as exc:  # pragma: no cover - driver selalu ada di prod
        _listener_log.warning("psycopg tidak tersedia; push lintas proses nonaktif (%s)", exc)
        return
    while not stop_event.is_set():
        try:
            with _psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(f'LISTEN "{_CHANNEL}"')
                while not stop_event.is_set():
                    _drain_pg_notifies(conn, timeout=poll_seconds)
        except Exception as exc:
            if not stop_event.is_set():
                _listener_log.warning(
                    "display LISTEN terputus; coba lagi %.0fs (%s)",
                    reconnect_delay,
                    exc,
                )
        stop_event.wait(reconnect_delay)


def start_pg_display_listener(
    dsn: str | None = None,
    *,
    poll_seconds: float = 1.0,
    reconnect_delay: float = 5.0,
) -> bool:
    """Pasang LISTENer Postgres sekali per proses; False bila dilewati.

    Idempoten. ``dsn=None`` membaca ``DATABASE_URL`` dari environment.
    """
    with _listener_lock:
        if _listener_state["thread"] is not None:
            return True
        resolved = dsn if dsn is not None else sqlalchemy_url_to_psycopg_dsn(
            _os.getenv("DATABASE_URL")
        )
        if resolved is None:
            return False
        stop_event = threading.Event()
        thread = threading.Thread(
            target=_pg_listener_loop,
            args=(stop_event, resolved),
            kwargs={
                "poll_seconds": poll_seconds,
                "reconnect_delay": reconnect_delay,
            },
            name="display-pg-listen",
            daemon=True,
        )
        _listener_state["thread"] = thread
        _listener_state["stop"] = stop_event
        thread.start()
        return True


def stop_pg_display_listener() -> None:
    """Hentikan LISTENer (dipakai shutdown/test); aman dipanggil kapan saja."""
    with _listener_lock:
        thread = _listener_state["thread"]
        stop_event = _listener_state["stop"]
        _listener_state["thread"] = None
        _listener_state["stop"] = None
    if isinstance(stop_event, threading.Event):
        stop_event.set()
    if isinstance(thread, threading.Thread) and thread.is_alive():
        thread.join(timeout=5.0)
