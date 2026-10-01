from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from presensi_api.db.config import get_database_url


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create the process engine on demand; importing the API does not connect."""
    return create_engine(get_database_url(), pool_pre_ping=True)


def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db_session() -> Generator[Session, None, None]:
    with get_session_factory()() as session:
        yield session
