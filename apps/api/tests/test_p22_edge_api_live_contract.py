"""P2-2: live in-process contract — real edge payload shape into the real API.

Builds the event with the production ``presensi_edge_agent.events.event_payload``
helper (the same code AI_EDGE uses) and posts it to the real Core API decision
endpoint. This proves the edge->API contract stays in sync; full hardware and
Postgres runs remain MANUAL HARDWARE TEST REQUIRED (see docs/pengujian.md).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from test_attendance_decisions import (  # noqa: F401
    attendance_database,
    frozen_now_utc,
    post_event,
)

from presensi_api.db.models import AttendanceRecord, RecognitionEvent
from presensi_edge_agent.events import event_payload
from recognition_core.domain import RecognitionDecision, TrackDecision


def test_real_edge_payload_records_attendance(
    attendance_database: tuple[sessionmaker[Session], dict[str, UUID]],  # noqa: F811
) -> None:
    factory, ids = attendance_database
    decision = TrackDecision(
        track_id="camera-live-contract",
        state="accepted",
        decision=RecognitionDecision(
            outcome="matched",
            student_id=ids["student"],
            confidence=0.95,
            margin=0.4,
        ),
        observation_count=3,
    )
    # Stamp on the fixture clock, not wall time: the R27 noon fixture
    # freezes the skew cutoff, so a wall-clock stamp fails with
    # event_occurred_at_in_future on any run after 12:05 WIB.
    occurred_at = frozen_now_utc()
    payload = event_payload(
        decision,
        device_id=ids["device"],
        session_id=ids["session"],
        occurred_at=occurred_at,
        model_name="opencv-zoo-sface",
        model_version="contract-p22",
        liveness_required=False,
        liveness_enabled=False,
        min_live_score=None,
    )
    # The edge helper must never leak raw frames or embeddings.
    assert "image" not in payload
    assert "embedding" not in payload

    response = post_event(payload)
    assert response.status_code == 200, response.text
    assert response.json()["decision"] == "attendance_recorded"

    with factory() as session:
        record = session.scalar(
            select(AttendanceRecord).where(
                AttendanceRecord.session_id == ids["session"],
                AttendanceRecord.student_id == ids["student"],
            )
        )
        assert record is not None
        assert record.source == "face_recognition"
        event = session.scalar(
            select(RecognitionEvent).where(
                RecognitionEvent.id == record.recognition_event_id
            )
        )
        assert event is not None
        assert event.model_name == "opencv-zoo-sface"
        assert event.model_version == "contract-p22"
