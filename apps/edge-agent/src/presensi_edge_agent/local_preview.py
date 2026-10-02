from __future__ import annotations

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import urlsplit

import httpx

from presensi_edge_agent.config import EdgeConfig, PreviewSettings


class LocalCameraPreview:
    """Loopback-only, operator-authorized view of the agent's existing camera feed."""

    def __init__(
        self, config: EdgeConfig, settings: PreviewSettings | None = None
    ) -> None:
        self.config = config
        self.settings = settings or config.preview
        self._lock = threading.RLock()
        self._frame: Any | None = None
        self._last_frame_at = 0.0
        self._status: dict[str, object] = {
            "camera_open": False,
            "session_active": False,
            "recognition_state": "starting",
            "display_name": None,
            "updated_at": None,
        }
        self._sessions: dict[str, float] = {}
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.settings.enabled or self._server is not None:
            return
        preview = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "PresensiLocalPreview"
            sys_version = ""

            def log_message(self, _format: str, *_args: object) -> None:
                # Keep image, identity and authorization details out of logs.
                return

            def _origin(self) -> str | None:
                origin = self.headers.get("Origin")
                if origin not in preview.settings.allowed_origins:
                    self.send_error(403)
                    return None
                host_header = self.headers.get("Host", "")
                hostname = urlsplit(f"//{host_header}").hostname
                if hostname not in {"localhost", "127.0.0.1", "::1"}:
                    self.send_error(403)
                    return None
                return origin

            def _cors(self, origin: str) -> None:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header(
                    "Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS"
                )
                self.send_header(
                    "Access-Control-Allow-Headers",
                    "Authorization, Content-Type, X-Presensi-Preview-Token",
                )
                self.send_header("Access-Control-Max-Age", "600")
                self.send_header("Cache-Control", "no-store, max-age=0")
                self.send_header("X-Content-Type-Options", "nosniff")

            def _send(
                self, status: int, body: bytes, content_type: str, origin: str
            ) -> None:
                self.send_response(status)
                self._cors(origin)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_json(
                self, status: int, payload: dict[str, object], origin: str
            ) -> None:
                self._send(
                    status,
                    json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                    "application/json; charset=utf-8",
                    origin,
                )

            def _authorized(self) -> bool:
                supplied = self.headers.get("X-Presensi-Preview-Token", "")
                now = time.monotonic()
                with preview._lock:
                    preview._sessions = {
                        token: expiry
                        for token, expiry in preview._sessions.items()
                        if expiry > now
                    }
                    expiry = preview._sessions.get(supplied)
                return bool(supplied) and expiry is not None

            def do_OPTIONS(self) -> None:
                origin = self._origin()
                if origin is None:
                    return
                self.send_response(204)
                self._cors(origin)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self) -> None:
                origin = self._origin()
                if origin is None:
                    return
                if self.path != "/v1/session":
                    self._send_json(404, {"error": "not_found"}, origin)
                    return
                authorization = self.headers.get("Authorization", "")
                scheme, separator, operator_token = authorization.partition(" ")
                if (
                    scheme.lower() != "bearer"
                    or not separator
                    or not operator_token.strip()
                ):
                    self._send_json(
                        401, {"error": "operator_authentication_required"}, origin
                    )
                    return
                operator_token = operator_token.strip()
                try:
                    response = httpx.get(
                        f"{preview.config.api.base_url}/api/v1/auth/me",
                        headers={"Authorization": f"Bearer {operator_token}"},
                        timeout=preview.config.api.timeout_seconds,
                        trust_env=False,
                    )
                    account = response.json() if response.is_success else None
                except (httpx.HTTPError, ValueError):
                    account = None
                if not isinstance(account, dict):
                    self._send_json(403, {"error": "operator_not_authorized"}, origin)
                    return
                roles = account.get("roles")
                if (
                    not isinstance(roles, list)
                    or not all(isinstance(role, str) for role in roles)
                    or not {"ADMIN", "LABORANT"}.intersection(roles)
                    or account.get("must_change_password")
                ):
                    self._send_json(403, {"error": "operator_not_authorized"}, origin)
                    return
                preview_token = secrets.token_urlsafe(32)
                with preview._lock:
                    preview._sessions[preview_token] = time.monotonic() + 300
                self._send_json(
                    201,
                    {"preview_token": preview_token, "expires_in_seconds": 300},
                    origin,
                )

            def do_DELETE(self) -> None:
                origin = self._origin()
                if origin is None:
                    return
                if self.path != "/v1/session" or not self._authorized():
                    self._send_json(401, {"error": "unauthorized"}, origin)
                    return
                supplied = self.headers.get("X-Presensi-Preview-Token", "")
                with preview._lock:
                    preview._sessions.pop(supplied, None)
                self._send_json(200, {"closed": True}, origin)

            def do_GET(self) -> None:
                origin = self._origin()
                if origin is None:
                    return
                if not self._authorized():
                    self._send_json(401, {"error": "unauthorized"}, origin)
                    return
                if self.path == "/v1/status":
                    with preview._lock:
                        payload = dict(preview._status)
                    self._send_json(200, payload, origin)
                    return
                if self.path == "/v1/frame.jpg":
                    with preview._lock:
                        frame = (
                            preview._frame.copy()
                            if preview._frame is not None
                            else None
                        )
                    if frame is None:
                        self._send_json(
                            503, {"error": "camera_frame_unavailable"}, origin
                        )
                        return
                    try:
                        import cv2

                        height, width = frame.shape[:2]
                        if width > preview.settings.max_width:
                            target_height = max(
                                1, round(height * preview.settings.max_width / width)
                            )
                            frame = cv2.resize(
                                frame,
                                (preview.settings.max_width, target_height),
                                interpolation=cv2.INTER_AREA,
                            )
                        ok, encoded = cv2.imencode(
                            ".jpg",
                            frame,
                            [cv2.IMWRITE_JPEG_QUALITY, preview.settings.jpeg_quality],
                        )
                        if not ok:
                            raise ValueError("jpeg encoding failed")
                        jpeg = encoded.tobytes()
                    except (ImportError, AttributeError, ValueError):
                        self._send_json(
                            503, {"error": "frame_encoding_unavailable"}, origin
                        )
                        return
                    self._send(200, jpeg, "image/jpeg", origin)
                    return
                self._send_json(404, {"error": "not_found"}, origin)

        try:
            server = ThreadingHTTPServer(
                (self.settings.bind_host, self.settings.port), Handler
            )
        except OSError:
            raise
        server.daemon_threads = True
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever,
            name="edge-local-camera-preview",
            daemon=True,
        )
        self._thread.start()

    def update_frame(self, frame: object) -> None:
        updated_at = time.monotonic()
        with self._lock:
            if updated_at - self._last_frame_at < 0.25:
                return
        try:
            copied = cast(Any, frame).copy()
        except AttributeError:
            return
        with self._lock:
            self._frame = copied
            self._last_frame_at = updated_at

    def clear_frame(self) -> None:
        with self._lock:
            self._frame = None
            self._last_frame_at = 0.0

    def update_status(self, **values: object) -> None:
        with self._lock:
            self._status.update(values)
            self._status["updated_at"] = time.time()

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        with self._lock:
            self._sessions.clear()
            self._frame = None
            self._last_frame_at = 0.0


__all__ = ["LocalCameraPreview"]
