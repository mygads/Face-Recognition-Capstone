from __future__ import annotations

import os

from sqlalchemy.engine import URL, make_url


class DatabaseConfigurationError(RuntimeError):
    """Raised when the database connection is not configured."""


def get_database_url() -> URL:
    configured_url = os.getenv("DATABASE_URL")
    if configured_url:
        return make_url(configured_url)

    required = {
        "username": os.getenv("DATABASE_USER"),
        "password": os.getenv("DATABASE_PASSWORD"),
        "host": os.getenv("DATABASE_HOST"),
        "port": os.getenv("DATABASE_PORT"),
        "database": os.getenv("DATABASE_NAME"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        names = ", ".join(missing)
        raise DatabaseConfigurationError(f"Database configuration is missing: {names}")

    return URL.create(
        drivername="postgresql+psycopg",
        username=required["username"],
        password=required["password"],
        host=required["host"],
        port=int(required["port"] or "5432"),
        database=required["database"],
    )
