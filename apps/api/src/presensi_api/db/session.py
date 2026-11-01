from __future__ import annotations

import os
from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from presensi_api.db.config import get_database_url


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


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create the process engine on demand; importing the API does not connect."""
    url = get_database_url()
    if url.get_backend_name() == "sqlite":
        return create_engine(url, pool_pre_ping=True)
    return create_engine(url, pool_pre_ping=True, **_pool_kwargs())


def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db_session() -> Generator[Session, None, None]:
    with get_session_factory()() as session:
        yield session
