"""Unit tests for DB engine hardening: pool sizing, statement timeout, PgBouncer."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

import presensi_api.db.session as db_session


def _clear_cache() -> None:
    db_session.get_engine.cache_clear()
    db_session.get_session_factory.cache_clear()


def test_statement_timeout_default_and_clamping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PRESENSI_DB_STATEMENT_TIMEOUT_MS", raising=False)
    assert db_session._statement_timeout_ms() == 30_000
    monkeypatch.setenv("PRESENSI_DB_STATEMENT_TIMEOUT_MS", "not-a-number")
    assert db_session._statement_timeout_ms() == 30_000
    monkeypatch.setenv("PRESENSI_DB_STATEMENT_TIMEOUT_MS", "0")
    assert db_session._statement_timeout_ms() == 0
    monkeypatch.setenv("PRESENSI_DB_STATEMENT_TIMEOUT_MS", "-5")
    assert db_session._statement_timeout_ms() == 0
    monkeypatch.setenv("PRESENSI_DB_STATEMENT_TIMEOUT_MS", "99999999")
    assert db_session._statement_timeout_ms() == 600_000


def test_pg_connect_args_empty_when_disabled() -> None:
    assert db_session._pg_connect_args(0) == {}
    assert db_session._pg_connect_args(-1) == {}
    args = db_session._pg_connect_args(30_000)
    assert args == {"options": "-c statement_timeout=30000ms"}


def test_pool_disabled_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRESENSI_DB_POOL_DISABLED", raising=False)
    assert db_session._is_pool_disabled() is False
    for truthy in ("1", "true", "TRUE", "yes", "on", "  On  "):
        monkeypatch.setenv("PRESENSI_DB_POOL_DISABLED", truthy)
        assert db_session._is_pool_disabled() is True
    for falsy in ("0", "false", "", "off", "no"):
        monkeypatch.setenv("PRESENSI_DB_POOL_DISABLED", falsy)
        assert db_session._is_pool_disabled() is False


def test_get_engine_sqlite_ignores_timeout_and_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    for key in (
        "DATABASE_USER",
        "DATABASE_HOST",
        "DATABASE_PORT",
        "DATABASE_NAME",
        "DATABASE_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PRESENSI_DB_STATEMENT_TIMEOUT_MS", "12345")
    monkeypatch.setenv("PRESENSI_DB_POOL_DISABLED", "1")
    _clear_cache()
    try:
        engine = db_session.get_engine()
        # sqlite must not become NullPool even when disabled flag is set.
        assert type(engine.pool).__name__ != "NullPool"
        engine.dispose()
    finally:
        _clear_cache()


def test_get_engine_pg_uses_nullpool_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_engine(url: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        captured["url_backend"] = url.get_backend_name()

        class Dummy:
            pass

        return Dummy()

    monkeypatch.setattr(db_session, "create_engine", fake_create_engine)
    monkeypatch.setattr(
        db_session,
        "get_database_url",
        lambda: make_url("postgresql+psycopg://u:p@h:5432/d"),
    )
    monkeypatch.setenv("PRESENSI_DB_POOL_DISABLED", "1")
    monkeypatch.setenv("PRESENSI_DB_STATEMENT_TIMEOUT_MS", "5000")
    _clear_cache()
    try:
        db_session.get_engine()
    finally:
        _clear_cache()
    assert captured.get("poolclass") is NullPool
    assert captured.get("connect_args") == {"options": "-c statement_timeout=5000ms"}
    assert "pool_size" not in captured


def test_get_engine_pg_default_pool_carries_statement_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create_engine(url: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        captured["url_backend"] = url.get_backend_name()

        class Dummy:
            pass

        return Dummy()

    monkeypatch.setattr(db_session, "create_engine", fake_create_engine)
    monkeypatch.setattr(
        db_session,
        "get_database_url",
        lambda: make_url("postgresql+psycopg://u:p@h:5432/d"),
    )
    monkeypatch.delenv("PRESENSI_DB_POOL_DISABLED", raising=False)
    monkeypatch.delenv("PRESENSI_DB_STATEMENT_TIMEOUT_MS", raising=False)
    monkeypatch.delenv("PRESENSI_DB_POOL_SIZE", raising=False)
    _clear_cache()
    try:
        db_session.get_engine()
    finally:
        _clear_cache()
    assert captured.get("pool_size") == 5
    assert captured.get("connect_args") == {"options": "-c statement_timeout=30000ms"}


def test_session_factory_is_cached_on_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One factory per process: creating it per request wastes wiring per tick.

    Regression guard for KAI-scale polling (dashboard snapshot every ~2s per
    teacher + edge heartbeats): the factory must be the same object while the
    engine is cached.
    """
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    for key in (
        "DATABASE_USER",
        "DATABASE_HOST",
        "DATABASE_PORT",
        "DATABASE_NAME",
        "DATABASE_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)
    _clear_cache()
    try:
        first = db_session.get_session_factory()
        second = db_session.get_session_factory()
        assert first is second
        assert first.kw.get("bind") is db_session.get_engine()
    finally:
        _clear_cache()
