"""Unit tests for SQL LIKE search helpers."""

from presensi_api.db.search import like_contains


def test_like_contains_escapes_wildcards_and_backslash() -> None:
    assert like_contains("100%") == "%100\\%%"
    assert like_contains("a_b") == "%a\\_b%"
    assert like_contains("  spaced  ") == "%spaced%"
    assert like_contains("back\\slash") == "%back\\\\slash%"
    assert like_contains("plain") == "%plain%"
