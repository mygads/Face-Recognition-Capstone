from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID


class OutboxFullError(RuntimeError):
    """Raised when the configured limit for pending events has been reached."""


class OutboxEventConflict(ValueError):
    """Raised when an event id is reused for different content locally."""


@dataclass(frozen=True, slots=True)
class QueuedEvent:
    event_id: UUID
    payload: dict[str, object]
    attempts: int


_ALLOWED_PAYLOAD_FIELDS = {
    "event_id",
    "device_id",
    "session_id",
    "student_id",
    "outcome",
    "similarity",
    "confidence",
    "margin",
    "liveness_passed",
    "liveness_score",
    "occurred_at",
    "model_name",
    "model_version",
}


class EventOutbox:
    """SQLite idempotent event queue; the schema has no image/vector columns."""

    def __init__(self, path: str | Path, *, max_pending: int) -> None:
        self.path = Path(path)
        if max_pending < 1:
            raise ValueError("max_pending must be positive.")
        self.max_pending = max_pending
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS edge_event_outbox (
                event_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                last_error_status INTEGER,
                created_at TEXT NOT NULL
            )"""
        )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS ix_edge_event_outbox_due "
            "ON edge_event_outbox(status, next_attempt_at, created_at)"
        )
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @staticmethod
    def _payload_json(payload: dict[str, object]) -> tuple[str, str]:
        if set(payload) != _ALLOWED_PAYLOAD_FIELDS:
            raise ValueError("Outbox accepts only the recognition event contract.")
        try:
            event_id = UUID(str(payload["event_id"]))
            encoded = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Recognition event cannot be serialized safely.") from exc
        return str(event_id), encoded

    def enqueue(self, payload: dict[str, object]) -> UUID:
        event_id_text, encoded = self._payload_json(payload)
        now = datetime.now(UTC).isoformat()
        with self._lock, self._db:
            current = self._db.execute(
                "SELECT payload_json FROM edge_event_outbox WHERE event_id = ?",
                (event_id_text,),
            ).fetchone()
            if current is not None:
                if current["payload_json"] != encoded:
                    raise OutboxEventConflict(
                        "An event id has different queued content."
                    )
                return UUID(event_id_text)
            count = self._db.execute(
                "SELECT count(*) FROM edge_event_outbox WHERE status = 'pending'"
            ).fetchone()[0]
            if int(count) >= self.max_pending:
                raise OutboxFullError("Pending event queue is full.")
            self._db.execute(
                "INSERT INTO edge_event_outbox "
                "(event_id, payload_json, next_attempt_at, created_at) "
                "VALUES (?, ?, ?, ?)",
                (event_id_text, encoded, now, now),
            )
        return UUID(event_id_text)

    def due(self, *, now: datetime | None = None, limit: int = 50) -> list[QueuedEvent]:
        if limit < 1:
            raise ValueError("limit must be positive.")
        timestamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        with self._lock:
            rows = self._db.execute(
                "SELECT event_id, payload_json, attempts FROM edge_event_outbox "
                "WHERE status = 'pending' AND next_attempt_at <= ? "
                "ORDER BY created_at, event_id LIMIT ?",
                (timestamp, limit),
            ).fetchall()
        result: list[QueuedEvent] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            if not isinstance(payload, dict):
                continue
            result.append(
                QueuedEvent(
                    event_id=UUID(row["event_id"]),
                    payload=cast(dict[str, object], payload),
                    attempts=int(row["attempts"]),
                )
            )
        return result

    def acknowledge(self, event_id: UUID) -> None:
        with self._lock, self._db:
            self._db.execute(
                "DELETE FROM edge_event_outbox WHERE event_id = ?",
                (str(event_id),),
            )

    def retry(
        self,
        event_id: UUID,
        *,
        max_delay_seconds: float,
        status_code: int | None,
    ) -> None:
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT attempts FROM edge_event_outbox WHERE event_id = ?",
                (str(event_id),),
            ).fetchone()
            if row is None:
                return
            attempts = int(row["attempts"]) + 1
            delay = min(float(2 ** min(attempts - 1, 30)), max_delay_seconds)
            next_attempt = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()
            self._db.execute(
                "UPDATE edge_event_outbox SET attempts = ?, next_attempt_at = ?, "
                "last_error_status = ? WHERE event_id = ? AND status = 'pending'",
                (attempts, next_attempt, status_code, str(event_id)),
            )

    def dead_letter(self, event_id: UUID, *, status_code: int | None) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE edge_event_outbox SET status = 'dead_letter', "
                "last_error_status = ? WHERE event_id = ?",
                (status_code, str(event_id)),
            )

    def counts(self) -> tuple[int, int]:
        with self._lock:
            rows = self._db.execute(
                "SELECT status, count(*) AS row_count FROM edge_event_outbox "
                "GROUP BY status"
            ).fetchall()
        counts = {str(row["status"]): int(row["row_count"]) for row in rows}
        return counts.get("pending", 0), counts.get("dead_letter", 0)
