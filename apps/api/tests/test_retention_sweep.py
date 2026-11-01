"""Retention auto-sweep scheduling (Fix A audit): the API background worker
must enforce the recognition-event retention policy on its own instead of
relying on an operator-run CLI."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from presensi_api import main as api_main
from presensi_api.db.base import Base
from presensi_api.db.models import RecognitionEvent
from presensi_api.retention import RetentionSummary


@pytest.fixture
def sweep_database(
    monkeypatch: pytest.MonkeyPatch,
) -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr("presensi_api.main.get_session_factory", lambda: factory)
    return factory


def test_retention_interval_defaults_to_daily() -> None:
    import os

    os.environ.pop("PRESENSI_RETENTION_SWEEP_HOURS", None)
    assert api_main.retention_sweep_interval_seconds() == 24 * 3600.0


def test_retention_interval_supports_fractions_and_disabling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRESENSI_RETENTION_SWEEP_HOURS", "0.5")
    assert api_main.retention_sweep_interval_seconds() == 1800.0
    monkeypatch.setenv("PRESENSI_RETENTION_SWEEP_HOURS", "0")
    assert api_main.retention_sweep_interval_seconds() == 0.0
    monkeypatch.setenv("PRESENSI_RETENTION_SWEEP_HOURS", "not-a-number")
    assert api_main.retention_sweep_interval_seconds() == 24 * 3600.0


def test_run_retention_sweep_deletes_expired_events(
    sweep_database: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRESENSI_RECOGNITION_EVENT_RETENTION_DAYS", "90")
    now = datetime.now(UTC)
    old_id = uuid4()
    with sweep_database.begin() as session:
        session.add(
            RecognitionEvent(
                id=old_id,
                event_uuid=uuid4(),
                session_id=uuid4(),
                device_id=uuid4(),
                recognized_student_id=None,
                created_at=now - timedelta(days=100),
                occurred_at=now - timedelta(days=100),
                outcome="ambiguous",
                model_name="synthetic-sface",
                model_version="test-1",
                quality_metadata={},
            )
        )

    summary = api_main._run_retention_sweep()

    assert isinstance(summary, RetentionSummary)
    assert summary.deleted_events == 1
    with sweep_database() as session:
        assert session.get(RecognitionEvent, old_id) is None


def test_run_retention_sweep_skips_invalid_configuration(
    sweep_database: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRESENSI_RECOGNITION_EVENT_RETENTION_DAYS", "banana")
    assert api_main._run_retention_sweep() is None
