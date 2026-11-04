from __future__ import annotations

import os
from collections.abc import Generator
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from presensi_api.db.config import get_database_url

_STATEMENT_TIMEOUT_DEFAULT_MS = 30_000
_STATEMENT_TIMEOUT_MAX_MS = 600_000


def _pool_kwargs() -> dict[str, int]:
    """Pool sizing for KAI-style bursts: many devices + polling teachers.

    Defaults stay small for single-PC labs; raise via environment on the
    central server (e.g. POOL_SIZE=20 for dozens of labs).
    """
    try:
        size = int(os.getenv("PRESENSI_DB_POOL_SIZE", "5"))
        overflow = int(os.getenv("PRESENSI_DB_MAX_OVERFLOW", "10"))
        timeout = int(os.getenv("PRESENSI_DB_POOL_TIMEOUT", "30"))
        recycle = int(os.getenv("PRESENSI_DB_POOL_RECYCLE", "1800"))
    except ValueError:
        size, overflow, timeout, recycle = 5, 10, 30, 1800
    return {
        "pool_size": min(max(size, 1), 100),
        "max_overflow": min(max(overflow, 0), 200),
        "pool_timeout": min(max(timeout, 1), 300),
        "pool_recycle": min(max(recycle, 60), 86400),
    }


def _statement_timeout_ms() -> int:
    """Per-query guard so one slow report never pins an API worker.

    Default 30 dtk; 0 = nonaktif (mis. migrasi lama manual). Nilai dijepit
    ke [0, 600000] agar typo operator tidak melumpuhkan DB.
    """
    try:
        raw = int(
            os.getenv(
                "PRESENSI_DB_STATEMENT_TIMEOUT_MS", str(_STATEMENT_TIMEOUT_DEFAULT_MS)
            )
        )
    except ValueError:
        return _STATEMENT_TIMEOUT_DEFAULT_MS
    return min(max(raw, 0), _STATEMENT_TIMEOUT_MAX_MS)


def _is_pool_disabled() -> bool:
    """True saat API berjalan di belakang PgBouncer (transaction pooling).

    PgBouncer sudah mengatur antrean/pooling sendiri; app wajib NullPool agar
    tidak double-pooling (checkout macet + prepared-statement error).
    """
    return os.getenv("PRESENSI_DB_POOL_DISABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _pg_connect_args(timeout_ms: int) -> dict[str, Any]:
    """statement_timeout via connect options (PG saja; sqlite diabaikan)."""
    if timeout_ms <= 0:
        return {}
    return {"options": f"-c statement_timeout={timeout_ms}ms"}


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create the process engine on demand; importing the API does not connect."""
    url = get_database_url()
    if url.get_backend_name() == "sqlite":
        return create_engine(url, pool_pre_ping=True)
    connect_args = _pg_connect_args(_statement_timeout_ms())
    if _is_pool_disabled():
        return create_engine(
            url, poolclass=NullPool, pool_pre_ping=True, connect_args=connect_args
        )
    return create_engine(
        url, pool_pre_ping=True, connect_args=connect_args, **_pool_kwargs()
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Reuse one factory per process; creating it per request wastes ~µs×QPS.

    The factory is cheap but not free (event wiring per instance); with
    dozens of polling teachers + edge heartbeats every few seconds, one
    cached factory bound to the cached engine is the KAI-scale default.
    Tests clearing ``get_engine`` cache should also clear this cache.
    """
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db_session() -> Generator[Session, None, None]:
    with get_session_factory()() as session:
        yield session
