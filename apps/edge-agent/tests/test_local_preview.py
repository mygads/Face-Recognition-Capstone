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
) -> HTTPResponse:
    headers = {"Origin": origin}
    if token is not None:
        headers["X-Presensi-Preview-Token"] = token
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", headers=headers, method=method
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
        preview.update_status(
            camera_open=True,
            session_active=True,
            recognition_state="waiting_for_calibration",
            display_name=None,
        )
        with pytest.raises(urllib.error.HTTPError) as unauthorized:
            _request(port, "/v1/status")
        assert unauthorized.value.code == 401

        response = _request(port, "/v1/status", token=token)
        status = json.loads(response.read())
        assert status["camera_open"] is True
        assert status["recognition_state"] == "waiting_for_calibration"
        assert status["display_name"] is None
        assert response.headers["Cache-Control"].startswith("no-store")
        assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
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


def test_preview_config_rejects_non_loopback_bind_host(tmp_path: Path) -> None:
    config_text = EXAMPLE_CONFIG.read_text(encoding="utf-8")
    config_text = config_text.replace("bind_host: 127.0.0.1", "bind_host: 0.0.0.0", 1)
    config_path = tmp_path / "edge-agent.yaml"
    config_path.write_text(config_text, encoding="utf-8")

    with pytest.raises(EdgeConfigError, match="loopback"):
        load_config(config_path)
