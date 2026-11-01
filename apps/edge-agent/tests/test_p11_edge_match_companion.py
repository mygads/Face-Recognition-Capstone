"""P1-1 companion: edge match records exactly one attendance event per decision.

Synthetic roster/templates only — no real student data.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from presensi_edge_agent.cache import parse_session_cache
from presensi_edge_agent.config import load_config
from presensi_edge_agent.outbox import EventOutbox
from presensi_edge_agent.service import EdgeService, require_attendance_recognizer
from recognition_core.domain import RecognitionDecision, TrackDecision

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_CONFIG = ROOT / "apps" / "edge-agent" / "config" / "edge-agent.example.yaml"
DEVICE_ID = UUID("33000000-0000-4000-8000-000000000001")
SESSION_ID = UUID("33000000-0000-4000-8000-000000000002")
STUDENT_ID = UUID("33000000-0000-4000-8000-000000000003")
MODEL_NAME = "opencv-zoo-sface"
MODEL_VERSION = "test-version"


def test_accepted_decision_enqueues_exactly_one_event(tmp_path: Path) -> None:
    config = load_config(
        EXAMPLE_CONFIG, environ={"PRESENSI_EDGE_DEVICE_ID": str(DEVICE_ID)}
    )
    config = replace(
        config,
        recognition=replace(
            config.recognition,
            min_top1_similarity=0.7,
            min_top1_top2_margin=0.1,
        ),
    )
    bundle = parse_session_cache(
        {
            "device_id": str(DEVICE_ID),
            "session_id": str(SESSION_ID),
            "session_status": "active",
            "generated_at": datetime.now(UTC).isoformat(),
            "session_ends_at": "2099-01-01T00:00:00+00:00",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "roster": [
                {
                    "student_id": str(STUDENT_ID),
                    "student_number": "SYN-01",
                    "full_name": "Synthetic Student",
                    "templates": [
                        {
                            "model_name": MODEL_NAME,
                            "model_version": MODEL_VERSION,
                            "normalized": True,
                            "values": [1.0, 0.0, 0.0],
                        }
                    ],
                }
            ],
        },
        device_id=DEVICE_ID,
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
    )

    class FakeCamera:
        def open(self) -> None: ...

        def read(self) -> tuple[bool, object | None]:
            return False, None

        def close(self) -> None: ...

    class FakeApi:
        def close(self) -> None: ...

    class AcceptingRecognizer:
        processed = 0

        def process(self, _frame, _gallery, _captured_at) -> TrackDecision:
            self.processed += 1
            return TrackDecision(
                track_id="p11-camera",
                state="accepted",
                decision=RecognitionDecision(
                    outcome="matched",
                    student_id=STUDENT_ID,
                    confidence=0.95,
                    margin=0.4,
                ),
                observation_count=3,
            )

        def reset(self) -> None: ...

    outbox = EventOutbox(tmp_path / "p11-match.sqlite3", max_pending=10)
    recognizer = AcceptingRecognizer()
    try:
        service = EdgeService(
            config,
            FakeCamera(),
            FakeApi(),  # type: ignore[arg-type]
            outbox,
            recognizer,  # type: ignore[arg-type]
            lambda: {},
        )
        require_attendance_recognizer(service.recognizer)
        service.cache.replace(bundle)
        service._process_frame(object())
        service._process_frame(object())
        assert recognizer.processed == 2
        assert outbox.counts() == (1, 0)
        queued = outbox.due()[0]
        assert queued.payload["student_id"] == str(STUDENT_ID)
        assert queued.payload["outcome"] == "matched"
        assert queued.payload["model_name"] == MODEL_NAME
        assert queued.payload["model_version"] == service.config.models.version
        assert "image" not in queued.payload
        assert "embedding" not in queued.payload
    finally:
        outbox.close()
