"""Regresi push SSE sejati: handler NOTIFY + skip-logic LISTENer Postgres."""

from __future__ import annotations

import threading
import time

import pytest

from presensi_api import display_notify
from presensi_api.display_notify import (
    _drain_pg_notifies,
    current_display_version,
    handle_pg_notification,
    sqlalchemy_url_to_psycopg_dsn,
    start_pg_display_listener,
    stop_pg_display_listener,
    wait_for_display_version,
)


@pytest.fixture(autouse=True)
def _stop_listener():
    yield
    stop_pg_display_listener()


def test_handle_pg_notification_wakes_waiter_immediately() -> None:
    seen = current_display_version()
    done: list[int] = []

    def waiter() -> None:
        done.append(wait_for_display_version(seen, 5.0))

    worker = threading.Thread(target=waiter)
    worker.start()
    time.sleep(0.1)
    handle_pg_notification("lab-xxx")
    worker.join(timeout=5.0)
    assert not worker.is_alive()
    assert done and done[0] != seen


def test_drain_stub_connection_handles_notifies() -> None:
    class Notify:
        def __init__(self, payload: str) -> None:
            self.payload = payload

    class StubConn:
        def __init__(self) -> None:
            self.calls = 0

        def notifies(self, timeout: float = 0.0):
            assert timeout == 0.0
            self.calls += 1
            if self.calls == 1:
                yield Notify("lab-a")
                yield Notify("lab-b")

    before = current_display_version()
    handled = _drain_pg_notifies(StubConn())
    assert handled == 2
    assert current_display_version() == before + 2


def test_drain_without_notifies_method_returns_zero() -> None:
    assert _drain_pg_notifies(object()) == 0


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql://u:p@host:5432/db", "postgresql://u:p@host:5432/db"),
        ("postgres://u:p@host/db", "postgresql://u:p@host/db"),
        (
            "postgresql+psycopg://u:p@host/db",
            "postgresql://u:p@host/db",
        ),
        ("sqlite://", None),
        ("mysql://u@host/db", None),
        ("", None),
        (None, None),
    ],
)
def test_dsn_conversion(url: str | None, expected: str | None) -> None:
    assert sqlalchemy_url_to_psycopg_dsn(url) == expected


def test_listener_skipped_without_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    assert start_pg_display_listener() is False
    monkeypatch.delenv("DATABASE_URL", raising=False)


def test_listener_start_stop_with_failing_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg

    def boom(*args: object, **kwargs: object):
        raise ConnectionError("no pg here")

    monkeypatch.setattr(psycopg, "connect", boom)
    assert (
        start_pg_display_listener(
            "postgresql://u@host/db", poll_seconds=0.01, reconnect_delay=0.01
        )
        is True
    )
    # Idempoten: panggilan kedua tidak membuat thread baru.
    assert start_pg_display_listener("postgresql://u@host/db") is True
    stop_pg_display_listener()
    # Setelah stop, bisa dipasang lagi.
    assert (
        start_pg_display_listener(
            "postgresql://u@host/db", poll_seconds=0.01, reconnect_delay=0.01
        )
        is True
    )
