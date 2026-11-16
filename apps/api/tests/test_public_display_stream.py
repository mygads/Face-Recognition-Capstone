"""Regresi: stream SSE kiosk ringan (agregat + sorotan, tanpa roster).

Catatan: httpx ASGITransport mem-buffer seluruh body sehingga tidak dapat
dipakai untuk membaca stream tak berujung. Test memakai endpoint langsung
(validasi + StreamingResponse) dan generator event secara langsung.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Generator
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import Request
from fastapi.responses import StreamingResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import presensi_api.api.v1.routers.public_display as display_module
from presensi_api.api.errors import ApiProblem
from presensi_api.api.security.config import AuthSettings
from presensi_api.api.security.dependencies import (
    decode_display_token,
    get_auth_settings,
    issue_display_token,
)
from presensi_api.api.security.passwords import hash_password
from presensi_api.db.base import Base
from presensi_api.db.models import Device, KioskScreen, Laboratory
from presensi_api.db.session import get_db_session
from presensi_api.main import app

TEST_SETTINGS = AuthSettings(signing_secret="y" * 40)


@pytest.fixture
def stream_database(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_auth_settings] = lambda: TEST_SETTINGS
    # Generator SSE memakai factory proses; arahkan ke sqlite uji.
    monkeypatch.setattr(display_module, "get_session_factory", lambda: factory)
    with factory.begin() as session:
        lab = Laboratory(
            code="LAB-SSE", name="Lab SSE", display_pin_hash=hash_password("1234")
        )
        session.add(lab)
        session.flush()
        device = Device(
            laboratory_id=lab.id,
            name="edge-pc-sse-01",
            device_type="edge_pc",
            deployment_profile="AI_EDGE",
        )
        session.add(device)
        session.flush()
        session.add(
            KioskScreen(
                device_id=device.id,
                laboratory_id=lab.id,
                display_name="Kiosk SSE",
                pin_hash=hash_password("9999"),
            )
        )
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


def _ids(factory: sessionmaker[Session]) -> tuple[str, str]:
    with factory() as session:
        lab = session.query(Laboratory).one()
        dev = session.query(Device).one()
        return str(lab.id), str(dev.id)


def _collect_first_event(
    gen: AsyncGenerator[str, None],
) -> tuple[str, dict[str, Any] | None]:
    async def run() -> tuple[str, dict[str, Any] | None]:
        async for raw in gen:
            for block in raw.split("\n\n"):
                if block.startswith("event: snapshot"):
                    for line in block.splitlines():
                        if line.startswith("data: "):
                            return "snapshot", json.loads(line[6:])
                if block.startswith("event: error"):
                    for line in block.splitlines():
                        if line.startswith("data: "):
                            return "error", json.loads(line[6:])
                    return "error", None
        raise AssertionError("stream berakhir tanpa event")

    return asyncio.run(run())


def test_lab_stream_rejects_bad_token_over_http(
    stream_database: sessionmaker[Session],
) -> None:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get(
                "/api/v1/public/display/stream?token=salah-token-salah-token"
            )

    resp = asyncio.run(send())
    assert resp.status_code == 401, resp.text


def test_kiosk_stream_rejects_bad_token_over_http(
    stream_database: sessionmaker[Session],
) -> None:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get(
                "/api/v1/public/kiosk-display/stream?token=salah-token-salah-token"
            )

    resp = asyncio.run(send())
    assert resp.status_code == 401, resp.text


def test_lab_endpoint_returns_event_stream(
    stream_database: sessionmaker[Session],
) -> None:
    lab_id, _ = _ids(stream_database)
    with stream_database() as session:
        lab = session.query(Laboratory).one()
        real_token, _ = issue_display_token("lab", lab.id, lab.id, TEST_SETTINGS)
        assert decode_display_token(real_token, TEST_SETTINGS) is not None
        request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        response = display_module.stream_lab_display(
            request, session, TEST_SETTINGS, token=real_token
        )
    assert isinstance(response, StreamingResponse)
    assert response.media_type == "text/event-stream"


def test_lab_stream_emits_lightweight_snapshot(
    stream_database: sessionmaker[Session],
) -> None:
    lab_id, _ = _ids(stream_database)
    with stream_database() as session:
        lab = session.query(Laboratory).one()
        token, _ = issue_display_token("lab", lab.id, lab.id, TEST_SETTINGS)
        claims = decode_display_token(token, TEST_SETTINGS)
        assert claims is not None
        gen = display_module._live_event_generator(
            "lab", claims.subject_id, claims.laboratory_id
        )
        kind, snap = _collect_first_event(gen)
        asyncio.run(gen.aclose())
    assert lab_id == str(lab.id)
    assert kind == "snapshot"
    assert snap is not None
    assert snap["laboratory_id"] == lab_id
    assert "students" not in snap
    assert snap["total_roster"] == 0
    assert snap["waiting_count"] == 0
    assert snap["spotlight"] is None
    assert snap["server_time"]


def test_stream_emits_error_for_unknown_lab(
    stream_database: sessionmaker[Session],
) -> None:
    gen = display_module._live_event_generator("lab", UUID(int=1), UUID(int=2))
    kind, payload = _collect_first_event(gen)
    asyncio.run(gen.aclose())
    assert kind == "error"
    assert payload is not None
    assert payload.get("code") == "laboratory_not_found"


def test_stream_endpoints_reject_mismatched_kind(
    stream_database: sessionmaker[Session],
) -> None:
    with stream_database() as session:
        lab = session.query(Laboratory).one()
        device = session.query(Device).one()
        lab_token, _ = issue_display_token("lab", lab.id, lab.id, TEST_SETTINGS)
        kiosk_token, _ = issue_display_token("kiosk", device.id, lab.id, TEST_SETTINGS)
        request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        with pytest.raises(ApiProblem):
            display_module.stream_lab_display(
                request, session, TEST_SETTINGS, token=kiosk_token
            )
        with pytest.raises(ApiProblem):
            display_module.stream_kiosk_display(
                request, session, TEST_SETTINGS, token=lab_token
            )
        response = display_module.stream_kiosk_display(
            request, session, TEST_SETTINGS, token=kiosk_token
        )
        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/event-stream"


def test_snapshot_digest_ignores_server_time() -> None:
    base = {
        "laboratory_id": "lab-1",
        "present_count": 1,
        "waiting_count": 2,
        "spotlight": None,
    }
    tick_a = {**base, "server_time": "2026-11-10T00:00:00+00:00"}
    tick_b = {**base, "server_time": "2026-11-10T00:00:01+00:00"}
    assert display_module._snapshot_digest(tick_a) == display_module._snapshot_digest(
        tick_b
    )
    changed = {**base, "present_count": 2, "server_time": tick_a["server_time"]}
    assert display_module._snapshot_digest(changed) != display_module._snapshot_digest(
        tick_a
    )


def _seed_kiosk_spotlight_scenario(
    factory: sessionmaker[Session],
) -> tuple[Laboratory, list[Device]]:
    """Satu lab, dua perangkat, satu sesi aktif, record campur manual/kamera."""
    from datetime import UTC, datetime, timedelta
    from datetime import time as dtime
    from uuid import uuid4

    from presensi_api.db.models import (
        AttendanceRecord,
        AttendanceSession,
        Device,
        Laboratory,
        PracticumSchedule,
        RecognitionEvent,
        SchoolClass,
        SessionStudent,
        Student,
        User,
    )

    with factory.begin() as session:
        lab = session.query(Laboratory).one()
        dev_a = session.query(Device).one()
        dev_b = Device(
            laboratory_id=lab.id,
            name="edge-pc-sse-02",
            device_type="edge_pc",
            deployment_profile="AI_EDGE",
        )
        session.add(dev_b)
        session.flush()
        teacher = User(
            email="guru-kiosk@example.test",
            full_name="Guru Kiosk",
            password_hash="x",
        )
        session.add(teacher)
        session.flush()
        cls = SchoolClass(
            code="X-K", name="Kelas X K", grade=10, academic_year="2026-2027"
        )
        session.add(cls)
        session.flush()
        sched = PracticumSchedule(
            class_id=cls.id,
            laboratory_id=lab.id,
            teacher_user_id=teacher.id,
            subject="Kimia",
            weekday=0,
            start_time=dtime(9, 0),
            end_time=dtime(10, 0),
            timezone_name="Asia/Jakarta",
            effective_from=datetime.now(UTC).date(),
            is_active=True,
        )
        session.add(sched)
        session.flush()
        opened_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=30)
        att = AttendanceSession(
            practicum_schedule_id=sched.id,
            opened_by_user_id=teacher.id,
            status="active",
            opened_at=opened_at,
            grace_period_minutes=20,
        )
        session.add(att)
        session.flush()
        s_cam_a = Student(student_number="K-A", full_name="Kamera A")
        s_cam_b = Student(student_number="K-B", full_name="Kamera B")
        s_man = Student(student_number="K-M", full_name="Manual M")
        session.add_all([s_cam_a, s_cam_b, s_man])
        session.flush()
        for s in (s_cam_a, s_cam_b, s_man):
            session.add(
                SessionStudent(
                    session_id=att.id,
                    student_id=s.id,
                    student_number_snapshot=s.student_number,
                    full_name_snapshot=s.full_name,
                )
            )
        session.flush()
        base = opened_at
        ev_a = RecognitionEvent(
            event_uuid=uuid4(),
            session_id=att.id,
            device_id=dev_a.id,
            recognized_student_id=s_cam_a.id,
            occurred_at=base + timedelta(minutes=5),
            outcome="matched",
            model_name="SFace",
            model_version="2021dec",
        )
        ev_b = RecognitionEvent(
            event_uuid=uuid4(),
            session_id=att.id,
            device_id=dev_b.id,
            recognized_student_id=s_cam_b.id,
            occurred_at=base + timedelta(minutes=6),
            outcome="matched",
            model_name="SFace",
            model_version="2021dec",
        )
        session.add_all([ev_a, ev_b])
        session.flush()
        session.add(
            AttendanceRecord(
                session_id=att.id,
                student_id=s_cam_a.id,
                recognition_event_id=ev_a.id,
                status="present",
                source="face_recognition",
                recorded_at=base + timedelta(minutes=5),
                occurred_at=base + timedelta(minutes=5),
            )
        )
        session.add(
            AttendanceRecord(
                session_id=att.id,
                student_id=s_cam_b.id,
                recognition_event_id=ev_b.id,
                status="present",
                source="face_recognition",
                recorded_at=base + timedelta(minutes=6),
                occurred_at=base + timedelta(minutes=6),
            )
        )
        # Manual TERBARU: tidak boleh membajak sorotan kiosk per-perangkat.
        session.add(
            AttendanceRecord(
                session_id=att.id,
                student_id=s_man.id,
                recognition_event_id=None,
                status="present",
                source="manual",
                recorded_at=base + timedelta(minutes=10),
            )
        )
    with factory() as session:
        lab = session.query(Laboratory).one()
        devs = session.query(Device).order_by(Device.name).all()
        return lab, devs


def test_kiosk_spotlight_only_own_device_scan(
    stream_database: sessionmaker[Session],
) -> None:
    lab, devs = _seed_kiosk_spotlight_scenario(stream_database)
    dev_a, dev_b = devs[0], devs[1]
    with stream_database() as session:
        lab_db = session.get(Laboratory, lab.id)
        assert lab_db is not None
        only_a = display_module._build_live_update(lab_db, session, device_id=dev_a.id)
        assert only_a.spotlight is not None
        assert only_a.spotlight.full_name == "Kamera A"
        assert only_a.spotlight.source == "face_recognition"
        assert only_a.spotlight.recognition_event_id is not None
        only_b = display_module._build_live_update(lab_db, session, device_id=dev_b.id)
        assert only_b.spotlight is not None
        assert only_b.spotlight.full_name == "Kamera B"
        # Agregat tetap lab-wide meski sorotan per-perangkat.
        assert only_a.present_count == 3
        assert only_b.present_count == 3
        assert only_a.grace_period_minutes == 20


def test_lab_spotlight_keeps_manual_with_source_and_grace(
    stream_database: sessionmaker[Session],
) -> None:
    lab, _devs = _seed_kiosk_spotlight_scenario(stream_database)
    with stream_database() as session:
        lab_db = session.get(Laboratory, lab.id)
        assert lab_db is not None
        lab_wide = display_module._build_live_update(lab_db, session, device_id=None)
        assert lab_wide.spotlight is not None
        # Manual terbaru tetap tampil di layar lab, tetapi berlabel manual.
        assert lab_wide.spotlight.full_name == "Manual M"
        assert lab_wide.spotlight.source == "manual"
        assert lab_wide.grace_period_minutes == 20


def test_kiosk_generator_uses_per_device_spotlight(
    stream_database: sessionmaker[Session],
) -> None:
    lab, devs = _seed_kiosk_spotlight_scenario(stream_database)
    dev_a = devs[0]
    with stream_database() as session:
        kiosk = session.query(KioskScreen).one()
        # Pastikan kiosk terikat ke perangkat pertama agar generator lolos.
        kiosk.device_id = dev_a.id
        session.commit()
        gen = display_module._live_event_generator("kiosk", dev_a.id, lab.id)
        kind, snap = _collect_first_event(gen)
        asyncio.run(gen.aclose())
    assert kind == "snapshot"
    assert snap is not None
    assert snap["spotlight"] is not None
    assert snap["spotlight"]["full_name"] == "Kamera A"
    assert snap["spotlight"]["source"] == "face_recognition"
    assert snap["grace_period_minutes"] == 20


def _http_get(path: str, **kwargs):  # type: ignore[no-untyped-def]
    cookies = kwargs.pop("cookies", None)

    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            cookies=cookies,
        ) as client:
            return await client.get(path, **kwargs)

    return asyncio.run(send())


def test_lab_snapshot_accepts_bearer_header_without_query(
    stream_database: sessionmaker[Session],
) -> None:
    with stream_database() as session:
        lab = session.query(Laboratory).one()
        token, _ = issue_display_token("lab", lab.id, lab.id, TEST_SETTINGS)
    resp = _http_get(
        "/api/v1/public/display", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Default light=True: hitungan tetap ada, roster tidak keluar untuk kiosk.
    assert body["laboratory_id"] == str(lab.id)
    assert body["students"] == []
    assert body["total_roster"] == 0


def test_lab_snapshot_accepts_cookie_without_query(
    stream_database: sessionmaker[Session],
) -> None:
    with stream_database() as session:
        lab = session.query(Laboratory).one()
        token, _ = issue_display_token("lab", lab.id, lab.id, TEST_SETTINGS)
    resp = _http_get("/api/v1/public/display", cookies={"display_token": token})
    assert resp.status_code == 200, resp.text
    assert resp.json()["laboratory_id"] == str(lab.id)


def test_lab_snapshot_rejects_missing_token(
    stream_database: sessionmaker[Session],
) -> None:
    del stream_database
    resp = _http_get("/api/v1/public/display")
    assert resp.status_code == 401, resp.text


def test_lab_snapshot_light_false_includes_students_key(
    stream_database: sessionmaker[Session],
) -> None:
    with stream_database() as session:
        lab = session.query(Laboratory).one()
        token, _ = issue_display_token("lab", lab.id, lab.id, TEST_SETTINGS)
    resp = _http_get(
        "/api/v1/public/display?light=false",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert "students" in resp.json()


def test_stream_rejects_mismatched_kind_over_header(
    stream_database: sessionmaker[Session],
) -> None:
    with stream_database() as session:
        lab = session.query(Laboratory).one()
        kiosk_token, _ = issue_display_token(
            "kiosk", UUID(int=0), lab.id, TEST_SETTINGS
        )
    del lab
    resp = _http_get(
        "/api/v1/public/display/stream",
        headers={"Authorization": f"Bearer {kiosk_token}"},
    )
    assert resp.status_code == 401, resp.text


def test_notify_wakes_generator_without_waiting_safety_tick(
    stream_database: sessionmaker[Session],
) -> None:
    """Push in-process membangunkan generator (<5 dtk, bukan 10 dtk safety)."""
    import threading
    import time

    from presensi_api.display_notify import notify_display_changed

    with stream_database() as session:
        lab = session.query(Laboratory).one()
        lab_id = str(lab.id)
        token, _ = issue_display_token("lab", lab.id, lab.id, TEST_SETTINGS)
        claims = decode_display_token(token, TEST_SETTINGS)
        assert claims is not None
        subject_id, laboratory_id = claims.subject_id, claims.laboratory_id

    def deactivate_and_notify() -> None:
        time.sleep(0.3)
        with stream_database() as inner:
            target = inner.query(Laboratory).one()
            target.is_active = False
            inner.commit()
        notify_display_changed()

    async def scenario() -> tuple[tuple[str, Any], tuple[str, Any], float]:
        gen = display_module._live_event_generator(
            "lab", subject_id, laboratory_id
        )
        try:
            first = await _collect_awaited(gen)
            worker = threading.Thread(target=deactivate_and_notify)
            started = time.monotonic()
            worker.start()
            try:
                second = await asyncio.wait_for(_collect_awaited(gen), timeout=5)
            finally:
                worker.join()
            return first, second, time.monotonic() - started
        finally:
            await gen.aclose()

    async def _collect_awaited(
        gen: Any,
    ) -> tuple[str, dict[str, Any] | None]:
        async for raw in gen:
            for block in raw.split("\n\n"):
                if block.startswith("event: snapshot"):
                    for line in block.splitlines():
                        if line.startswith("data: "):
                            return "snapshot", json.loads(line[6:])
                    return "snapshot", None
                if block.startswith("event: error"):
                    for line in block.splitlines():
                        if line.startswith("data: "):
                            return "error", json.loads(line[6:])
                    return "error", None
        raise AssertionError("stream berakhir tanpa event")

    (kind, _), (kind2, payload), elapsed = asyncio.run(scenario())
    assert kind == "snapshot"
    assert kind2 == "error"
    assert payload is not None and payload.get("code") == "laboratory_not_found"
    assert elapsed < 5, "generator tidak dibangunkan push"
    assert lab_id


def test_two_lab_streams_are_isolated(
    stream_database: sessionmaker[Session],
) -> None:
    """Isolasi 2-lab: ubah lab A membangunkan kedua generator (versi global),
    tetapi hanya A yang emit snapshot baru; B tetap diam (digest tak berubah).

    Catatan: pembatalan `__anext__` diserap generator (except CancelledError
    -> break), jadi ketiadaan event B tidak boleh diassert via
    `wait_for(..., TimeoutError)`. Sebagai gantinya B dikoleksi task latar
    dan hitungannya dibandingkan sebelum/sesudah jeda.
    """
    from presensi_api.display_notify import notify_display_changed

    with stream_database.begin() as session:
        lab_b = Laboratory(
            code="LAB-SSE-B",
            name="Lab SSE B",
            display_pin_hash=hash_password("1234"),
        )
        session.add(lab_b)
        session.flush()
        session.add(
            Device(
                laboratory_id=lab_b.id,
                name="edge-pc-sse-B",
                device_type="edge_pc",
                deployment_profile="AI_EDGE",
            )
        )
    with stream_database() as session:
        lab_a = session.query(Laboratory).filter_by(code="LAB-SSE").one()
        lab_b = session.query(Laboratory).filter_by(code="LAB-SSE-B").one()
        lab_a_id, lab_b_id = lab_a.id, lab_b.id

    def parse_event(raw: str) -> tuple[str, dict[str, Any] | None] | None:
        for block in raw.split("\n\n"):
            if block.startswith("event: snapshot"):
                for line in block.splitlines():
                    if line.startswith("data: "):
                        return "snapshot", json.loads(line[6:])
                return "snapshot", None
            if block.startswith("event: error"):
                for line in block.splitlines():
                    if line.startswith("data: "):
                        return "error", json.loads(line[6:])
                return "error", None
        return None

    async def next_event(
        gen: Any,
    ) -> tuple[str, dict[str, Any] | None]:
        async for raw in gen:
            parsed = parse_event(raw)
            if parsed is not None:
                return parsed
        raise AssertionError("stream berakhir tanpa event")

    async def scenario() -> None:
        gen_a = display_module._live_event_generator("lab", lab_a_id, lab_a_id)
        gen_b = display_module._live_event_generator("lab", lab_b_id, lab_b_id)
        b_events: list[tuple[str, dict[str, Any] | None]] = []

        async def collect_b() -> None:
            async for raw in gen_b:
                parsed = parse_event(raw)
                if parsed is not None:
                    b_events.append(parsed)

        task_b = asyncio.create_task(collect_b())
        try:
            kind_a, snap_a = await asyncio.wait_for(next_event(gen_a), timeout=5)
            assert kind_a == "snapshot"
            assert snap_a is not None
            # Tunggu snapshot pertama B (generator emit langsung di tick 0).
            for _ in range(100):
                if b_events:
                    break
                await asyncio.sleep(0.05)
            assert b_events, "generator lab B tidak emit snapshot awal"
            assert b_events[0][0] == "snapshot"
            assert b_events[0][1] is not None
            assert (
                b_events[0][1]["laboratory_name"] != snap_a["laboratory_name"]
            )
            with stream_database() as inner:
                target = inner.get(Laboratory, lab_a_id)
                assert target is not None
                target.name = "Lab SSE A Renamed"
                inner.commit()
            notify_display_changed()
            kind_a2, snap_a2 = await asyncio.wait_for(
                next_event(gen_a), timeout=5
            )
            assert kind_a2 == "snapshot"
            assert snap_a2 is not None
            assert snap_a2["laboratory_name"] == "Lab SSE A Renamed"
            # B sudah bangun (versi global) tetapi digest-nya tak berubah:
            # diam selama 1,5 dtk (jauh di bawah safety re-query 10 dtk).
            seen = len(b_events)
            await asyncio.sleep(1.5)
            assert len(b_events) == seen, (
                f"kebocoran antar-lab: {b_events[seen:]}"
            )
        finally:
            task_b.cancel()
            try:
                await task_b
            except (asyncio.CancelledError, StopAsyncIteration):
                pass
            await gen_a.aclose()
            await gen_b.aclose()

    asyncio.run(scenario())
