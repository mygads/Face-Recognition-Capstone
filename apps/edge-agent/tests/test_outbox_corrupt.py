"""Corrupt stored rows must not poison the edge outbox.

Regression guard: EventOutbox.due() parsed every due row's payload_json
without protection. One undecodable row (disk corruption, manual tampering
of the edge sqlite file, legacy junk) raised out of due(), so every sync
cycle aborted and all healthy events behind the bad row stalled forever.
Corrupt rows are now quarantined as dead letters (status_code None) and the
rest of the queue keeps draining.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

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


def _inject_raw_row(outbox: EventOutbox, event_id: str, payload_json: str) -> None:
    now = datetime.now(UTC).isoformat()
    with outbox._lock, outbox._db:
        outbox._db.execute(
            "INSERT INTO edge_event_outbox "
            "(event_id, payload_json, next_attempt_at, created_at) "
            "VALUES (?, ?, ?, ?)",
            (event_id, payload_json, now, now),
        )


def test_corrupt_payload_row_is_quarantined_and_queue_drains(
    tmp_path: Path,
) -> None:
    outbox = EventOutbox(tmp_path / "corrupt.sqlite3", max_pending=50)
    try:
        _inject_raw_row(outbox, str(uuid4()), "{not valid json{{{")
        healthy_id = outbox.enqueue(_payload())

        due = outbox.due()
        assert [event.event_id for event in due] == [healthy_id]

        pending, dead = outbox.counts()
        assert (pending, dead) == (1, 1)
        statuses = {
            str(row["event_id"]): str(row["status"])
            for row in outbox._db.execute(
                "SELECT event_id, status FROM edge_event_outbox"
            ).fetchall()
        }
        assert statuses[str(healthy_id)] == "pending"
        assert sum(1 for status in statuses.values() if status == "dead_letter") == 1

        # The quarantine sticks: the next cycle drains the healthy row again
        # instead of raising on the same bad row.
        assert [event.event_id for event in outbox.due()] == [healthy_id]
    finally:
        outbox.close()


def test_non_object_payload_row_is_quarantined(tmp_path: Path) -> None:
    outbox = EventOutbox(tmp_path / "nonobject.sqlite3", max_pending=50)
    try:
        _inject_raw_row(outbox, str(uuid4()), "[1, 2, 3]")
        assert outbox.due() == []
        pending, dead = outbox.counts()
        assert (pending, dead) == (0, 1)
    finally:
        outbox.close()


def test_garbage_event_id_row_is_quarantined_without_raising(
    tmp_path: Path,
) -> None:
    outbox = EventOutbox(tmp_path / "badeid.sqlite3", max_pending=50)
    try:
        _inject_raw_row(
            outbox,
            "not-a-uuid",
            '{"event_id": "not-a-uuid", "outcome": "no_match"}',
        )
        assert outbox.due() == []
        pending, dead = outbox.counts()
        assert (pending, dead) == (0, 1)
    finally:
        outbox.close()
