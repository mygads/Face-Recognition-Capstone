from __future__ import annotations

import json
import socket
import sys
import urllib.error
import urllib.request
from dataclasses import replace
from http.client import HTTPResponse
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import httpx
import pytest

from presensi_edge_agent.config import EdgeConfigError, load_config
from presensi_edge_agent.local_preview import LocalCameraPreview

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_CONFIG = ROOT / "apps" / "edge-agent" / "config" / "edge-agent.example.yaml"
ORIGIN = "http://127.0.0.1:5173"


class FakeOperatorResponse:
    def __init__(self, roles: list[str] | None = None) -> None:
        self.is_success = roles is not None
        self._roles = roles or []

    def json(self) -> dict[str, object]:
        return {
            "roles": self._roles,
            "must_change_password": False,
        }


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(
    port: int,
    path: str,
    *,
    method: str = "GET",
    token: str | None = None,
    origin: str = ORIGIN,
    payload: dict[str, object] | None = None,
) -> HTTPResponse:
    headers = {"Origin": origin}
    if token is not None:
        headers["X-Presensi-Preview-Token"] = token
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers=headers,
        data=data,
        method=method,
    )
    return cast(HTTPResponse, urllib.request.urlopen(request, timeout=2))


def _start_preview(
    monkeypatch: pytest.MonkeyPatch, roles: list[str] | None = None
) -> tuple[LocalCameraPreview, int, str]:
    config = load_config(EXAMPLE_CONFIG)
    config = replace(config, preview=replace(config.preview, port=_free_port()))
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *_args, **_kwargs: FakeOperatorResponse(roles),
    )
    preview = LocalCameraPreview(config)
    preview.start()
    request = urllib.request.Request(
        f"http://127.0.0.1:{config.preview.port}/v1/session",
        headers={"Origin": ORIGIN, "Authorization": "Bearer synthetic-operator-token"},
        method="POST",
    )
    response = urllib.request.urlopen(request, timeout=2)
    token = json.loads(response.read())["preview_token"]
    return preview, config.preview.port, token


def test_preview_requires_operator_session_and_serves_no_store_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview, port, token = _start_preview(monkeypatch, ["ADMIN"])
    try:
        assert preview.has_active_viewer() is True
        preview.update_status(
            camera_open=True,
            session_active=True,
            recognition_state="waiting_for_calibration",
            display_name=None,
        )
        preview.update_camera_observation(
            {
                "state": "ready",
                "message": "Frame siap diperiksa.",
                "frame_width": 1280,
                "frame_height": 720,
                "face_count": 1,
                "faces": [
                    {
                        "x": 0.5,
                        "y": 0.25,
                        "width": 0.15,
                        "height": 0.3,
                        "acceptable": True,
                        "quality_score": 0.9,
                        "embedding": [1.0, 2.0],
                        "student_name": "Should not be exposed",
                    }
                ],
            }
        )
        preview.update_diagnostic_candidate(" Candidate Adult\n", 0.902)
        with pytest.raises(urllib.error.HTTPError) as unauthorized:
            _request(port, "/v1/status")
        assert unauthorized.value.code == 401

        response = _request(port, "/v1/status", token=token)
        status = json.loads(response.read())
        assert status["camera_open"] is True
        assert status["recognition_state"] == "waiting_for_calibration"
        assert status["display_name"] is None
        assert status["camera_observation"]["state"] == "ready"
        candidate = status["diagnostic_candidate"]
        assert isinstance(candidate, dict)
        assert candidate["display_name"] == "Candidate Adult"
        assert candidate["similarity"] == pytest.approx(0.902)
        serialized_status = json.dumps(status)
        assert "embedding" not in serialized_status.lower()
        assert "student_id" not in candidate
        assert "should not be exposed" not in serialized_status.lower()
        _request(port, "/v1/session", method="DELETE", token=token)
        assert preview.has_active_viewer() is False
        assert response.headers["Cache-Control"].startswith("no-store")
        assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
    finally:
        preview.stop()


def test_preview_exposes_name_only_for_confirmed_attendance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview, port, token = _start_preview(monkeypatch, ["ADMIN"])
    try:
        preview.update_attendance_result(
            "pending", attendance_status=None, display_name="Must stay hidden"
        )
        pending = json.loads(_request(port, "/v1/status", token=token).read())
        assert "display_name" not in pending["attendance_result"]

        preview.update_attendance_result(
            "recorded",
            attendance_status="present",
            display_name=" Synthetic Adult Volunteer\n",
            class_name=" Synthetic Biology Class\n",
        )
        recorded = json.loads(_request(port, "/v1/status", token=token).read())
        assert (
            recorded["attendance_result"]["display_name"] == "Synthetic Adult Volunteer"
        )
        assert recorded["attendance_result"]["class_name"] == "Synthetic Biology Class"

        preview.update_attendance_result(
            "recorded", attendance_status="present", display_name="X" * 150
        )
        bounded = json.loads(_request(port, "/v1/status", token=token).read())
        assert len(bounded["attendance_result"]["display_name"]) == 120
    finally:
        preview.stop()


def test_preview_rejects_non_local_origins_and_unauthorized_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(EXAMPLE_CONFIG)
    config = replace(config, preview=replace(config.preview, port=_free_port()))
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *_args, **_kwargs: FakeOperatorResponse(["TEACHER"]),
    )
    preview = LocalCameraPreview(config)
    preview.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as bad_origin:
            _request(config.preview.port, "/v1/status", origin="https://attacker.test")
        assert bad_origin.value.code == 403

        request = urllib.request.Request(
            f"http://127.0.0.1:{config.preview.port}/v1/session",
            headers={"Origin": ORIGIN, "Authorization": "Bearer synthetic-token"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as forbidden_role:
            urllib.request.urlopen(request, timeout=2)
        assert forbidden_role.value.code == 403
    finally:
        preview.stop()


def test_preview_encodes_only_an_in_memory_downscaled_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Frame:
        shape = (360, 800, 3)

        def copy(self) -> Frame:
            return self

    class Encoded:
        def tobytes(self) -> bytes:
            return b"\xff\xd8synthetic-jpeg\xff\xd9"

    resized: list[tuple[int, int]] = []

    def resize(_frame: object, size: tuple[int, int], **_kwargs: object) -> Frame:
        resized.append(size)
        return Frame()

    fake_cv2: Any = SimpleNamespace(
        INTER_AREA=1,
        IMWRITE_JPEG_QUALITY=2,
        resize=resize,
        imencode=lambda *_args, **_kwargs: (True, Encoded()),
    )
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    preview, port, token = _start_preview(monkeypatch, ["LABORANT"])
    try:
        preview.update_frame(Frame())
        response = _request(port, "/v1/frame.jpg", token=token)
        assert response.headers["Content-Type"] == "image/jpeg"
        assert response.read().startswith(b"\xff\xd8")
        assert resized == [(640, 288)]

        preview.clear_frame()
        with pytest.raises(urllib.error.HTTPError) as unavailable:
            _request(port, "/v1/frame.jpg", token=token)
        assert unavailable.value.code == 503
    finally:
        preview.stop()


def _read_stream_until(
    sock: socket.socket,
    marker: bytes,
    count: int,
    buf: bytearray,
    deadline_s: float = 10.0,
) -> bytes:
    # Stream MJPEG tak-berujung: kumpulkan sampai marker terlihat beberapa
    # kali. http.client tak cocok di sini (read(n) pada body tanpa
    # Content-Length menunggu EOF, bukan n byte). Sisa byte setelah marker
    # dipertahankan di buf untuk pembacaan berikutnya.
    import time as _time

    sock.settimeout(deadline_s)
    deadline = _time.monotonic() + deadline_s
    while buf.count(marker) < count:
        if _time.monotonic() > deadline:
            break
        try:
            piece = sock.recv(4096)
        except TimeoutError:
            break
        if not piece:
            break
        buf += piece
    out = bytes(buf)
    del buf[:]
    return out


def _open_stream(port: int, path: str) -> socket.socket:
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    sock.sendall(
        f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
        "Connection: close\r\n\r\n".encode()
    )
    return sock


def test_preview_stream_serves_multipart_frames_with_query_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Frame:
        shape = (360, 800, 3)

        def copy(self) -> "Frame":
            return self

    class Encoded:
        def tobytes(self) -> bytes:
            return b"\xff\xd8synthetic-jpeg\xff\xd9"

    fake_cv2: Any = SimpleNamespace(
        INTER_AREA=1,
        IMWRITE_JPEG_QUALITY=2,
        resize=lambda _frame, _size, **_kwargs: Frame(),
        imencode=lambda *_args, **_kwargs: (True, Encoded()),
    )
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    preview, port, token = _start_preview(monkeypatch, ["LABORANT"])
    try:
        preview.update_frame(Frame())

        sock = _open_stream(port, f"/v1/stream?token={token}")
        try:
            buf = bytearray()
            head = _read_stream_until(sock, b"\r\n\r\n", 1, buf)
            assert b"200 OK" in head
            assert b"multipart/x-mixed-replace; boundary=presensi-frame" in head
            first = _read_stream_until(sock, b"--presensi-frame", 1, buf)
            assert b"--presensi-frame" in first
            assert b"\xff\xd8synthetic-jpeg\xff\xd9" in first
            # Frame kedua hanya dikirim setelah ada frame baru (tanpa
            # handshake ulang): simulasikan frame berikutnya dari kamera.
            import time as _time2

            _time2.sleep(0.2)
            assert preview.update_frame(Frame()) is True
            second = _read_stream_until(sock, b"--presensi-frame", 1, buf)
            assert b"--presensi-frame" in second
        finally:
            sock.close()

        # Token query wajib: tanpa token atau token salah ditolak.
        for bad_path in ("/v1/stream", "/v1/stream?token=salah"):
            bad = _open_stream(port, bad_path)
            try:
                head = _read_stream_until(bad, b"\r\n\r\n", 1, bytearray())
                assert b"401" in head.split(b"\r\n")[0]
            finally:
                bad.close()

        # Stream berhenti setelah sesi dicabut (tidak menggantung thread).
        sock = _open_stream(port, f"/v1/stream?token={token}")
        try:
            buf2 = bytearray()
            assert _read_stream_until(sock, b"--presensi-frame", 1, buf2)
            _request(port, "/v1/session", method="DELETE", token=token)
            rest = _read_stream_until(sock, b"__never__", 1, buf2, deadline_s=10.0)
            assert b"--presensi-frame" not in rest
        finally:
            sock.close()
    finally:
        preview.stop()


def test_local_diagnostics_keep_only_aggregate_scores_and_hide_unusable_margin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview, port, token = _start_preview(monkeypatch, ["ADMIN"])
    student_id = UUID("33000000-0000-4000-8000-000000000003")
    try:
        preview.update_status(camera_open=True, session_active=True)
        preview.update_calibration_students(
            ((student_id, "Synthetic Adult Volunteer"),),
            gallery_identity_count=1,
        )
        response = _request(
            port,
            "/v1/calibration-sample",
            method="POST",
            token=token,
            payload={"phase": "genuine", "student_id": str(student_id)},
        )
        assert response.status == 202
        preview.complete_calibration_sample(
            top1_similarity=0.81,
            top1_top2_margin=1.81,
            expected_identity_match=True,
        )

        response = _request(port, "/v1/status", token=token)
        status = json.loads(response.read())
        calibration = status["calibration"]
        assert calibration["gallery_identity_count"] == 1
        assert calibration["margin_interpretable"] is False
        assert calibration["genuine"] == {
            "sample_count": 1,
            "top1_min": 0.81,
            "top1_mean": 0.81,
            "top1_max": 0.81,
            "identity_match_count": 1,
        }
        serialized = json.dumps(calibration)
        assert "embedding" not in serialized.lower()
        assert "values" not in calibration["genuine"]
        assert "photo" not in serialized.lower()
    finally:
        preview.stop()


def test_local_diagnostic_sample_requires_active_session_and_operator_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview, port, token = _start_preview(monkeypatch, ["LABORANT"])
    student_id = UUID("33000000-0000-4000-8000-000000000003")
    try:
        with pytest.raises(urllib.error.HTTPError) as unauthorized:
            _request(
                port,
                "/v1/calibration-sample",
                method="POST",
                payload={"phase": "impostor"},
            )
        assert unauthorized.value.code == 401

        preview.update_calibration_students(
            ((student_id, "Synthetic Adult Volunteer"),),
            gallery_identity_count=1,
        )
        with pytest.raises(urllib.error.HTTPError) as inactive:
            _request(
                port,
                "/v1/calibration-sample",
                method="POST",
                token=token,
                payload={"phase": "impostor"},
            )
        assert inactive.value.code == 400
        assert json.loads(inactive.value.read()) == {"error": "session_unavailable"}
    finally:
        preview.stop()


def test_local_diagnostics_show_margin_only_for_multiple_template_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview, port, token = _start_preview(monkeypatch, ["ADMIN"])
    first_student = UUID("33000000-0000-4000-8000-000000000003")
    second_student = UUID("33000000-0000-4000-8000-000000000004")
    try:
        preview.update_status(camera_open=True, session_active=True)
        preview.update_calibration_students(
            ((first_student, "Synthetic Adult Volunteer"),),
            gallery_identity_count=1,
        )
        assert preview.request_calibration_sample("genuine", str(first_student)) is None
        preview.complete_calibration_sample(
            top1_similarity=0.81,
            top1_top2_margin=1.81,
            expected_identity_match=True,
        )

        preview.update_calibration_students(
            (
                (first_student, "Synthetic Adult Volunteer"),
                (second_student, "Another Synthetic Adult Volunteer"),
            ),
            gallery_identity_count=2,
        )
        assert preview.request_calibration_sample("impostor", None) is None
        preview.complete_calibration_sample(
            top1_similarity=0.54,
            top1_top2_margin=0.08,
            expected_identity_match=None,
        )

        status = json.loads(_request(port, "/v1/status", token=token).read())
        calibration = status["calibration"]
        assert calibration["margin_interpretable"] is True
        assert calibration["genuine"]["sample_count"] == 0
        assert calibration["impostor"] == {
            "sample_count": 1,
            "top1_min": 0.54,
            "top1_mean": 0.54,
            "top1_max": 0.54,
            "margin_min": 0.08,
            "margin_mean": 0.08,
            "margin_max": 0.08,
        }
    finally:
        preview.stop()


def test_preview_config_rejects_non_loopback_bind_host(tmp_path: Path) -> None:
    config_text = EXAMPLE_CONFIG.read_text(encoding="utf-8")
    config_text = config_text.replace("bind_host: 127.0.0.1", "bind_host: 0.0.0.0", 1)
    config_path = tmp_path / "edge-agent.yaml"
    config_path.write_text(config_text, encoding="utf-8")

    with pytest.raises(EdgeConfigError, match="loopback"):
        load_config(config_path)


def test_preview_session_slides_expiry_while_watched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview, port, token = _start_preview(monkeypatch, ["ADMIN"])
    try:
        first_expiry = preview._sessions[token]
        _request(port, "/v1/status", token=token).read()
        second_expiry = preview._sessions[token]
        # Activity extends the session instead of forcing a re-authenticate
        # round-trip in the middle of an operator watch.
        assert second_expiry > first_expiry
        assert preview.has_active_viewer() is True
    finally:
        preview.stop()


def test_kiosk_hint_serves_generic_state_without_token_or_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview, port, token = _start_preview(monkeypatch, ["ADMIN"])
    try:
        preview.update_status(
            camera_open=True,
            session_active=True,
            recognition_state="collecting",
            display_name="Siswa Rahasia",
        )
        preview.update_diagnostic_candidate("Siswa Rahasia", 0.95)
        preview.update_camera_observation(
            {
                "state": "ready",
                "message": "Frame siap diperiksa.",
                "frame_width": 640,
                "frame_height": 480,
                "face_count": 1,
                "faces": [
                    {
                        "x": 0.5,
                        "y": 0.25,
                        "width": 0.15,
                        "height": 0.3,
                        "acceptable": True,
                        "quality_score": 0.9,
                        "embedding": [9.0, 9.0],
                        "student_name": "Siswa Rahasia",
                    }
                ],
            }
        )
        # Tanpa token dan tanpa Origin allowlist: tetap 200 via loopback.
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/kiosk-hint", method="GET"
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            assert response.status == 200
            assert response.headers.get("Access-Control-Allow-Private-Network") == (
                "true"
            )
            hint = json.loads(response.read())
        assert hint["session_active"] is True
        assert hint["camera_open"] is True
        assert hint["recognition_state"] == "collecting"
        assert hint["face_present"] is True
        assert hint["face_count"] == 1
        assert hint["attendance_result"] is None
        serialized = json.dumps(hint)
        assert "Siswa Rahasia" not in serialized
        assert "display_name" not in hint
        assert "faces" not in hint
        assert "embedding" not in serialized.lower()
        assert "diagnostic_candidate" not in hint
        # Poll kiosk-hint menandai konsumen agar diagnostik wajah tetap jalan.
        assert preview.has_kiosk_hint_consumer() is True
    finally:
        preview.stop()


def test_kiosk_hint_hides_stale_face_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview, port, _token = _start_preview(monkeypatch, ["ADMIN"])
    try:
        preview.update_status(camera_open=True, session_active=True)
        preview.update_camera_observation(
            {
                "state": "ready",
                "message": "Frame siap diperiksa.",
                "frame_width": 640,
                "frame_height": 480,
                "face_count": 2,
                "faces": [],
            }
        )
        assert preview.kiosk_hint()["face_present"] is True
        import time as _time

        with preview._lock:
            preview._status["updated_at"] = _time.time() - 10.0
        assert preview.kiosk_hint()["face_present"] is False
        assert preview.kiosk_hint()["face_count"] == 2
    finally:
        preview.stop()


def test_kiosk_hint_rejects_non_loopback_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview, port, _token = _start_preview(monkeypatch, ["ADMIN"])
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/kiosk-hint",
            headers={"Host": "kiosk.sekolah.example"},
            method="GET",
        )
        with pytest.raises(urllib.error.HTTPError) as forbidden:
            urllib.request.urlopen(request, timeout=2)
        assert forbidden.value.code == 403

        preflight = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/kiosk-hint",
            headers={
                "Host": "kiosk.sekolah.example",
                "Origin": "http://127.0.0.1:5173",
            },
            method="OPTIONS",
        )
        with pytest.raises(urllib.error.HTTPError) as preflight_forbidden:
            urllib.request.urlopen(preflight, timeout=2)
        assert preflight_forbidden.value.code == 403
    finally:
        preview.stop()


def test_kiosk_hint_preflight_allows_private_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview, port, _token = _start_preview(monkeypatch, ["ADMIN"])
    try:
        preflight = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/kiosk-hint",
            headers={"Origin": ORIGIN},
            method="OPTIONS",
        )
        with urllib.request.urlopen(preflight, timeout=2) as response:
            assert response.status == 204
            assert response.headers.get("Access-Control-Allow-Private-Network") == (
                "true"
            )
            assert response.headers.get("Access-Control-Allow-Origin") == ORIGIN
    finally:
        preview.stop()
