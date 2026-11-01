"""Helpers for user-supplied text search over SQL LIKE patterns."""

from __future__ import annotations


def like_contains(value: str) -> str:
    """Build a case-insensitive ``%value%`` LIKE pattern with wildcards escaped.

    User search input may legitimately contain ``%``, ``_``, or backslashes
    (NIS codes, room names). Without escaping, those characters act as LIKE
    wildcards and a search for ``"100%"`` would match ``"100A"``. Use with
    ``column.ilike(pattern, escape="\\")`` on both SQLite and PostgreSQL.
    """
    escaped = (
        value.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return f"%{escaped}%"
