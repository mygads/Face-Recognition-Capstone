"""Dead-letter retention: poison pills must not fill the edge disk.

Regression guard: dead_letter rows are terminal (never retried), so without a
bound a flapping device accumulates them for months on a lab PC until SQLite
hits disk-full and *pending* events can no longer be queued.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from presensi_edge_agent.outbox import EventOutbox


def _payload() -> dict[str, object]:
    return {
        "event_id": str(uuid4()),
        "device_id": "device-1",
        "session_id": str(uuid4()),
        "student_id": str(uuid4()),
        "outcome": "no_match",
        "similarity": 0.1,
        "confidence": 0.2,
        "margin": 0.05,
        "liveness_passed": None,
        "liveness_score": None,
        "occurred_at": datetime.now(UTC).isoformat(),
        "model_name": "SFace",
        "model_version": "test",
    }


def _enqueue_and_kill(outbox: EventOutbox) -> None:
    payload = _payload()
    event_id = outbox.enqueue(payload)
    outbox.dead_letter(event_id, status_code=400)


def test_dead_letter_auto_trims_oldest_beyond_cap(tmp_path: Path) -> None:
    outbox = EventOutbox(tmp_path / "dl.sqlite3", max_pending=50, max_dead_letter=5)
    try:
        for _ in range(8):
            _enqueue_and_kill(outbox)
        pending, dead = outbox.counts()
        assert pending == 0
        assert dead == 5
        # Newest evidence survives: newest 5 rows kept, oldest 3 dropped.
        rows = outbox._db.execute(
            "SELECT event_id FROM edge_event_outbox WHERE status='dead_letter'"
        ).fetchall()
        assert len(rows) == 5
    finally:
        outbox.close()


def test_purge_dead_letter_keeps_newest_and_reports_count(tmp_path: Path) -> None:
    outbox = EventOutbox(tmp_path / "purge.sqlite3", max_pending=50)
    try:
        for _ in range(4):
            _enqueue_and_kill(outbox)
        removed = outbox.purge_dead_letter(keep_latest=1)
        assert removed == 3
        assert outbox.counts() == (0, 1)
        assert outbox.purge_dead_letter(keep_latest=0) == 1
        assert outbox.counts() == (0, 0)
        with pytest.raises(ValueError, match="keep_latest"):
            outbox.purge_dead_letter(keep_latest=-1)
    finally:
        outbox.close()


def test_max_dead_letter_validation() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ValueError, match="max_dead_letter"):
            EventOutbox(Path(tmp) / "x.sqlite3", max_pending=10, max_dead_letter=0)


def test_runtime_config_dead_letter_cap_yaml_and_env() -> None:
    """YAML `runtime.max_dead_letter_events` + env override reach RuntimeSettings."""
    from pathlib import Path as _Path

    from presensi_edge_agent.config import EdgeConfigError, load_config

    root = _Path(__file__).resolve().parents[3]
    example = root / "apps" / "edge-agent" / "config" / "edge-agent.example.yaml"
    base = load_config(
        example,
        environ={"PRESENSI_EDGE_DEVICE_ID": "33000000-0000-4000-8000-000000000001"},
    )
    assert base.runtime.max_outbox_events >= 1
    assert base.runtime.max_dead_letter_events >= 1

    overridden = load_config(
        example,
        environ={
            "PRESENSI_EDGE_DEVICE_ID": "33000000-0000-4000-8000-000000000001",
            "PRESENSI_EDGE_MAX_DEAD_LETTER_EVENTS": "7",
            "PRESENSI_EDGE_MAX_OUTBOX_EVENTS": "11",
        },
    )
    assert overridden.runtime.max_dead_letter_events == 7
    assert overridden.runtime.max_outbox_events == 11

    with pytest.raises(EdgeConfigError):
        load_config(
            example,
            environ={
                "PRESENSI_EDGE_DEVICE_ID": "33000000-0000-4000-8000-000000000001",
                "PRESENSI_EDGE_MAX_DEAD_LETTER_EVENTS": "0",
            },
        )
