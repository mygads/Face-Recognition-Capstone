from __future__ import annotations

import json
import math
import secrets
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Literal, cast
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from presensi_edge_agent.config import EdgeConfig, PreviewSettings


@dataclass(slots=True)
class _CalibrationAggregate:
    sample_count: int = 0
    top1_min: float | None = None
    top1_sum: float = 0.0
    top1_max: float | None = None
    margin_min: float | None = None
    margin_sum: float = 0.0
    margin_max: float | None = None
    identity_match_count: int = 0

    def add(
        self,
        *,
        top1_similarity: float,
        top1_top2_margin: float,
        expected_identity_match: bool | None,
    ) -> None:
        self.sample_count += 1
        self.top1_min = (
            top1_similarity
            if self.top1_min is None
            else min(self.top1_min, top1_similarity)
        )
        self.top1_sum += top1_similarity
        self.top1_max = (
            top1_similarity
            if self.top1_max is None
            else max(self.top1_max, top1_similarity)
        )
        self.margin_min = (
            top1_top2_margin
            if self.margin_min is None
            else min(self.margin_min, top1_top2_margin)
        )
        self.margin_sum += top1_top2_margin
        self.margin_max = (
            top1_top2_margin
            if self.margin_max is None
            else max(self.margin_max, top1_top2_margin)
        )
        if expected_identity_match is True:
            self.identity_match_count += 1


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
            "attendance_result": None,
            "camera_observation": {
                "state": "pending",
                "message": "Menunggu pemeriksaan frame kamera.",
                "frame_width": 0,
                "frame_height": 0,
                "face_count": 0,
                "faces": [],
            },
            "updated_at": None,
        }
        self._sessions: dict[str, float] = {}
        self._calibration_students: tuple[tuple[str, str], ...] = ()
        self._calibration_gallery_identity_count = 0
        self._calibration_request: dict[str, str | None] | None = None
        self._calibration_samples = {
            "genuine": _CalibrationAggregate(),
            "impostor": _CalibrationAggregate(),
        }
        self._calibration_last_result: dict[str, object] | None = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def status(self) -> dict[str, object]:
        with self._lock:
            payload = dict(self._status)
            payload["calibration"] = self._calibration_status_locked()
            return payload

    def has_active_viewer(self) -> bool:
        now = time.monotonic()
        with self._lock:
            self._sessions = {
                token: expiry
                for token, expiry in self._sessions.items()
                if expiry > now
            }
            return bool(self._sessions)

    def update_calibration_students(
        self,
        students: tuple[tuple[UUID, str], ...],
        *,
        gallery_identity_count: int,
    ) -> None:
        with self._lock:
            gallery_changed = (
                gallery_identity_count != self._calibration_gallery_identity_count
            )
            samples_exist = any(
                aggregate.sample_count > 0
                for aggregate in self._calibration_samples.values()
            )
            self._calibration_students = tuple(
                (str(student_id), name) for student_id, name in students
            )
            self._calibration_gallery_identity_count = gallery_identity_count
            if gallery_changed and self._calibration_request is not None:
                self._calibration_request = None
                self._calibration_last_result = {
                    "phase": "calibration",
                    "result": "cancelled",
                    "message": (
                        "Roster template berubah; mulai ulang pengambilan sampel."
                    ),
                }
            elif gallery_changed and samples_exist:
                self._calibration_samples = {
                    "genuine": _CalibrationAggregate(),
                    "impostor": _CalibrationAggregate(),
                }
                self._calibration_last_result = {
                    "phase": "calibration",
                    "result": "reset",
                    "message": (
                        "Jumlah identitas bertemplate berubah; ringkasan direset "
                        "agar perbandingan tetap konsisten."
                    ),
                }
            if self._calibration_request is not None and self._calibration_request[
                "student_id"
            ] not in {student_id for student_id, _name in self._calibration_students}:
                self._calibration_request = None
                self._calibration_last_result = {
                    "phase": "genuine",
                    "result": "cancelled",
                    "message": "Siswa tidak lagi ada pada roster sesi aktif.",
                }

    def clear_calibration_session(self) -> None:
        """Discard in-memory diagnostics when the active session is lost or changes."""
        with self._lock:
            self._calibration_request = None
            self._calibration_samples = {
                "genuine": _CalibrationAggregate(),
                "impostor": _CalibrationAggregate(),
            }
            self._calibration_last_result = None
            self._calibration_students = ()
            self._calibration_gallery_identity_count = 0

    def request_calibration_sample(
        self, phase: str, student_id: str | None
    ) -> str | None:
        with self._lock:
            if self._calibration_request is not None:
                return "sample_in_progress"
            if not self._status["camera_open"] or not self._status["session_active"]:
                return "session_unavailable"
            if phase not in {"genuine", "impostor"}:
                return "invalid_phase"
            if phase == "genuine":
                if student_id is None:
                    return "student_required"
                try:
                    normalized_student_id = str(UUID(student_id))
                except ValueError:
                    return "invalid_student"
                if normalized_student_id not in {
                    item_id for item_id, _name in self._calibration_students
                }:
                    return "student_not_in_session"
                student_id = normalized_student_id
            elif student_id is not None:
                return "unexpected_student"
            if self._calibration_samples[phase].sample_count >= 100:
                return "sample_limit"
            self._calibration_request = {
                "phase": phase,
                "student_id": student_id,
            }
            self._calibration_last_result = {
                "phase": phase,
                "result": "pending",
                "message": "Menunggu satu frame berkualitas untuk dinilai.",
            }
            return None

    def calibration_request(self) -> dict[str, str | None] | None:
        with self._lock:
            return (
                dict(self._calibration_request)
                if self._calibration_request is not None
                else None
            )

    def complete_calibration_sample(
        self,
        *,
        top1_similarity: float,
        top1_top2_margin: float,
        expected_identity_match: bool | None,
    ) -> None:
        if (
            not math.isfinite(top1_similarity)
            or not -1 <= top1_similarity <= 1
            or not math.isfinite(top1_top2_margin)
            or not 0 <= top1_top2_margin <= 2
        ):
            self.fail_calibration_sample("invalid_score")
            return
        with self._lock:
            request = self._calibration_request
            if request is None:
                return
            phase = cast(Literal["genuine", "impostor"], request["phase"])
            if (phase == "genuine") != (expected_identity_match is not None):
                self._calibration_request = None
                self._calibration_last_result = {
                    "phase": phase,
                    "result": "retry",
                    "message": "Sampel tidak siap; atur posisi lalu coba lagi.",
                }
                return
            self._calibration_samples[phase].add(
                top1_similarity=top1_similarity,
                top1_top2_margin=top1_top2_margin,
                expected_identity_match=expected_identity_match,
            )
            self._calibration_request = None
            self._calibration_last_result = {
                "phase": phase,
                "result": "sampled",
                "message": (
                    "Sampel siswa cocok dengan identitas yang dipilih."
                    if expected_identity_match is True
                    else "Sampel siswa tidak cocok dengan identitas yang dipilih."
                    if expected_identity_match is False
                    else "Skor relawan non-terdaftar tercatat untuk evaluasi lokal."
                ),
            }

    def fail_calibration_sample(self, reason_code: str) -> None:
        safe_reasons = {
            "no_face",
            "multiple_faces",
            "face_too_small",
            "blurred_face",
            "face_too_dark",
            "face_too_bright",
            "liveness_inconclusive",
            "spoof",
            "face_crop_empty",
            "frame_blurry",
            "lighting_out_of_range",
            "no_candidate",
            "session_unavailable",
            "invalid_score",
            "calibration_error",
        }
        reason = reason_code if reason_code in safe_reasons else "try_again"
        with self._lock:
            request = self._calibration_request
            if request is None:
                return
            phase = request["phase"]
            self._calibration_request = None
            self._calibration_last_result = {
                "phase": phase,
                "result": "retry",
                "message": self._calibration_message(reason),
            }

    def reset_calibration(self) -> bool:
        with self._lock:
            if self._calibration_request is not None:
                return False
            self._calibration_samples = {
                "genuine": _CalibrationAggregate(),
                "impostor": _CalibrationAggregate(),
            }
            self._calibration_last_result = None
            return True

    def _calibration_status_locked(self) -> dict[str, object]:
        return {
            "students": [
                {"student_id": student_id, "full_name": name}
                for student_id, name in self._calibration_students
            ],
            "sample_pending": self._calibration_request is not None,
            "gallery_identity_count": self._calibration_gallery_identity_count,
            "margin_interpretable": self._calibration_gallery_identity_count >= 2,
            "last_result": self._calibration_last_result,
            "genuine": self._calibration_group_summary("genuine"),
            "impostor": self._calibration_group_summary("impostor"),
        }

    def _calibration_group_summary(self, phase: str) -> dict[str, object]:
        aggregate = self._calibration_samples[phase]
        summary: dict[str, object] = {"sample_count": aggregate.sample_count}
        if aggregate.sample_count == 0:
            return summary
        summary.update(
            {
                "top1_min": aggregate.top1_min,
                "top1_mean": aggregate.top1_sum / aggregate.sample_count,
                "top1_max": aggregate.top1_max,
            }
        )
        if self._calibration_gallery_identity_count >= 2:
            summary.update(
                {
                    "margin_min": aggregate.margin_min,
                    "margin_mean": aggregate.margin_sum / aggregate.sample_count,
                    "margin_max": aggregate.margin_max,
                }
            )
        if phase == "genuine":
            summary["identity_match_count"] = aggregate.identity_match_count
        return summary

    @staticmethod
    def _calibration_message(reason: str) -> str:
        messages = {
            "no_face": (
                "Model belum menemukan satu wajah; hadapkan wajah ke lensa "
                "dan posisikan utuh di tengah."
            ),
            "multiple_faces": "Pastikan hanya satu orang berada di frame.",
            "face_too_small": "Dekatkan wajah ke kamera.",
            "blurred_face": "Tahan posisi agar gambar lebih tajam.",
            "face_too_dark": "Tambah pencahayaan pada wajah.",
            "face_too_bright": "Kurangi cahaya langsung ke wajah.",
            "spoof": "Sampel ditolak oleh pemeriksaan liveness.",
            "liveness_inconclusive": "Pemeriksaan liveness belum meyakinkan.",
            "face_crop_empty": "Wajah tidak terbaca dengan utuh; atur posisi kamera.",
            "frame_blurry": "Tahan posisi agar gambar lebih tajam.",
            "lighting_out_of_range": "Sesuaikan pencahayaan pada wajah.",
            "no_candidate": "Tidak ada template yang dapat dibandingkan.",
            "session_unavailable": "Sesi praktikum sudah tidak aktif.",
            "invalid_score": "Sampel tidak menghasilkan skor yang valid.",
            "calibration_error": "Uji diagnostik gagal; coba lagi.",
        }
        return messages.get(reason, "Sampel tidak siap; atur posisi lalu coba lagi.")

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

            def _read_json_body(self) -> dict[str, object] | int | None:
                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    return None
                if content_length < 0 or content_length > 2048:
                    return 413
                try:
                    payload = json.loads(self.rfile.read(content_length))
                except ValueError:
                    return None
                if not isinstance(payload, dict) or not all(
                    isinstance(key, str) for key in payload
                ):
                    return None
                return cast(dict[str, object], payload)

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
                    if self.path != "/v1/calibration-sample":
                        self._send_json(404, {"error": "not_found"}, origin)
                        return
                    if not self._authorized():
                        self._send_json(401, {"error": "unauthorized"}, origin)
                        return
                    payload = self._read_json_body()
                    if isinstance(payload, int):
                        self._send_json(payload, {"error": "request_too_large"}, origin)
                        return
                    if payload is None:
                        self._send_json(400, {"error": "invalid_request"}, origin)
                        return
                    phase = payload.get("phase")
                    raw_student_id = payload.get("student_id")
                    student_id = (
                        raw_student_id if isinstance(raw_student_id, str) else None
                    )
                    if raw_student_id is not None and student_id is None:
                        self._send_json(400, {"error": "invalid_student"}, origin)
                        return
                    error = preview.request_calibration_sample(
                        phase if isinstance(phase, str) else "", student_id
                    )
                    if error is not None:
                        status = (
                            409
                            if error in {"sample_in_progress", "sample_limit"}
                            else 400
                        )
                        self._send_json(status, {"error": error}, origin)
                        return
                    self._send_json(202, {"queued": True}, origin)
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
                if not self._authorized():
                    self._send_json(401, {"error": "unauthorized"}, origin)
                    return
                if self.path == "/v1/session":
                    supplied = self.headers.get("X-Presensi-Preview-Token", "")
                    with preview._lock:
                        preview._sessions.pop(supplied, None)
                    self._send_json(200, {"closed": True}, origin)
                    return
                if self.path != "/v1/calibration":
                    self._send_json(404, {"error": "not_found"}, origin)
                    return
                if not preview.reset_calibration():
                    self._send_json(409, {"error": "sample_in_progress"}, origin)
                    return
                self._send_json(200, {"cleared": True}, origin)

            def do_GET(self) -> None:
                origin = self._origin()
                if origin is None:
                    return
                if not self._authorized():
                    self._send_json(401, {"error": "unauthorized"}, origin)
                    return
                if self.path == "/v1/status":
                    payload = preview.status()
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
            self._status["camera_observation"] = {
                "state": "unavailable",
                "message": "Frame kamera terputus.",
                "frame_width": 0,
                "frame_height": 0,
                "face_count": 0,
                "faces": [],
            }

    def update_status(self, **values: object) -> None:
        with self._lock:
            self._status.update(values)
            self._status["updated_at"] = time.time()

    def update_camera_observation(self, payload: dict[str, object]) -> None:
        """Publish only bounded face boxes and quality signals to the local preview."""
        allowed_states = {
            "pending",
            "ready",
            "adjust",
            "no_face",
            "multiple_faces",
            "unavailable",
        }
        state = payload.get("state")
        if not isinstance(state, str) or state not in allowed_states:
            state = "unavailable"
        message = payload.get("message")
        if not isinstance(message, str) or len(message) > 240:
            message = "Pemeriksaan kamera tidak tersedia."
        frame_width = payload.get("frame_width")
        frame_height = payload.get("frame_height")
        face_count = payload.get("face_count")
        safe_faces: list[dict[str, object]] = []
        faces = payload.get("faces")
        if isinstance(faces, list):
            for face in faces[:10]:
                if not isinstance(face, dict):
                    continue
                box = {key: face.get(key) for key in ("x", "y", "width", "height")}
                if not all(
                    isinstance(value, (int, float)) and 0 <= value <= 1
                    for value in box.values()
                ):
                    continue
                safe_face: dict[str, object] = box
                acceptable = face.get("acceptable")
                safe_face["acceptable"] = acceptable is True
                score = face.get("quality_score")
                if isinstance(score, (int, float)) and 0 <= score <= 1:
                    safe_face["quality_score"] = float(score)
                reason_codes = face.get("reason_codes")
                safe_face["reason_codes"] = (
                    [code[:40] for code in reason_codes[:6] if isinstance(code, str)]
                    if isinstance(reason_codes, list)
                    else []
                )
                for key in ("face_pixels", "sharpness", "brightness"):
                    value = face.get(key)
                    if isinstance(value, (int, float)) and math.isfinite(value):
                        safe_face[key] = float(value)
                safe_faces.append(safe_face)
        observation = {
            "state": state,
            "message": message,
            "frame_width": frame_width if type(frame_width) is int else 0,
            "frame_height": frame_height if type(frame_height) is int else 0,
            "face_count": face_count if type(face_count) is int else len(safe_faces),
            "faces": safe_faces,
        }
        with self._lock:
            self._status["camera_observation"] = observation
            self._status["updated_at"] = time.time()

    def update_attendance_result(
        self,
        decision: str | None,
        attendance_status: str | None = None,
        display_name: str | None = None,
    ) -> None:
        result: dict[str, str | float | None] | None
        if decision is None:
            result = None
        elif decision == "pending":
            result = {"decision": decision, "attendance_status": None}
        elif decision == "recorded" and attendance_status in {"present", "late"}:
            result = {"decision": decision, "attendance_status": attendance_status}
            if isinstance(display_name, str):
                safe_name = "".join(char for char in display_name if char.isprintable())
                safe_name = safe_name.strip()[:120]
                if safe_name:
                    result["display_name"] = safe_name
        elif decision == "not_recorded":
            result = {"decision": decision, "attendance_status": None}
        else:
            result = None
        if result is not None:
            result["updated_at"] = time.time()
        with self._lock:
            self._status["attendance_result"] = result
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
