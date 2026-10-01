from __future__ import annotations

import asyncio
import hashlib
import json
import math
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

import psutil
from fastapi import FastAPI, Header, Request, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from presensi_ai_service.config import AISettings
from presensi_ai_service.gallery_cache import (
    SessionGallery,
    SessionGalleryCache,
    SessionGalleryProvider,
)
from presensi_ai_service.gallery_provider import (
    CoreApiGalleryProvider,
    GalleryProviderError,
)
from presensi_ai_service.image_decode import ImageDecodeError, decode_image
from presensi_ai_service.inference import (
    CapturedFrame,
    InferenceBusyError,
    RecognitionRunner,
    build_model_runner,
)
from recognition_core.opencv_models import SFaceModel


class ErrorPayload(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorPayload


class CaptureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    captured_at: AwareDatetime
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    image_base64: str = Field(min_length=1, max_length=4_194_304, repr=False)


class BurstInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_id: str = Field(min_length=1, max_length=128)
    frames: list[CaptureInput] = Field(min_length=1, max_length=5)

    @field_validator("frames")
    @classmethod
    def frames_must_be_time_ordered(
        cls, frames: list[CaptureInput]
    ) -> list[CaptureInput]:
        timestamps = [frame.captured_at for frame in frames]
        if any(
            current <= previous for previous, current in zip(timestamps, timestamps[1:])
        ):
            raise ValueError("Frame timestamps must be strictly increasing.")
        return frames


class CandidateMetadata(BaseModel):
    student_id: UUID
    confidence: float | None
    margin: float | None


class BurstDecisionResponse(BaseModel):
    session_id: UUID
    track_id: str
    status: str
    outcome: str
    candidate: CandidateMetadata | None
    reason_code: str | None
    liveness_score: float | None
    observations: int
    frames_processed: int
    model_version: str


class Metrics(BaseModel):
    recognition_requests: int
    completed: int
    failed: int
    timed_out: int
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    stage_latency_ms: dict[str, dict[str, float | int]]
    process_cpu_seconds: float
    process_rss_bytes: int
    host_cpu_percent: float
    host_memory_used_bytes: int
    host_memory_total_bytes: int


class ServiceError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


class DeviceAuthenticator:
    def __init__(self, tokens: Mapping[UUID, str]) -> None:
        self._tokens = dict(tokens)

    def authenticate(
        self, device_id_value: str | None, authorization: str | None
    ) -> UUID:
        device_id: UUID | None = None
        try:
            if device_id_value is not None:
                device_id = UUID(device_id_value)
        except ValueError:
            device_id = None
        token = ""
        if authorization is not None:
            scheme, separator, credentials = authorization.partition(" ")
            if separator and scheme.lower() == "bearer":
                token = credentials.strip()
        expected = self._tokens.get(device_id) if device_id is not None else None
        if device_id is None or not token:
            raise ServiceError(
                401, "invalid_device_credentials", "Device authentication failed."
            )
        if expected is not None:
            matches = secrets.compare_digest(
                token.encode("utf-8"), expected.encode("utf-8")
            )
            if not matches:
                raise ServiceError(
                    401,
                    "invalid_device_credentials",
                    "Device authentication failed.",
                )
        elif self._tokens or len(token) < 32 or not token.isascii():
            raise ServiceError(
                401, "invalid_device_credentials", "Device authentication failed."
            )
        return device_id


class DeviceRateLimiter:
    def __init__(self, *, rate: float, capacity: int) -> None:
        self._rate = rate
        self._capacity = float(capacity)
        self._buckets: dict[UUID, tuple[float, float]] = {}
        self._lock = asyncio.Lock()

    async def allow(self, device_id: UUID) -> float | None:
        now = time.monotonic()
        async with self._lock:
            tokens, updated_at = self._buckets.get(device_id, (self._capacity, now))
            tokens = min(self._capacity, tokens + (now - updated_at) * self._rate)
            if tokens < 1:
                self._buckets[device_id] = (tokens, now)
                return (1 - tokens) / self._rate
            self._buckets[device_id] = (tokens - 1, now)
            return None


class BasicMetrics:
    def __init__(self) -> None:
        self._durations: deque[float] = deque(maxlen=1024)
        self._stage_durations: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=1024)
        )
        self.recognition_requests = 0
        self.completed = 0
        self.failed = 0
        self.timed_out = 0
        self._lock = asyncio.Lock()

    async def observe(
        self,
        duration_ms: float,
        outcome: str,
        stage_durations_ms: Mapping[str, float] | None = None,
    ) -> None:
        async with self._lock:
            self.recognition_requests += 1
            self._durations.append(duration_ms)
            for stage, stage_duration in (stage_durations_ms or {}).items():
                self._stage_durations[stage].append(stage_duration)
            if outcome == "completed":
                self.completed += 1
            elif outcome == "timed_out":
                self.timed_out += 1
            else:
                self.failed += 1

    async def snapshot(self) -> Metrics:
        async with self._lock:
            values = sorted(self._durations)
            process = psutil.Process()
            process_times = process.cpu_times()
            host_memory = psutil.virtual_memory()
            return Metrics(
                recognition_requests=self.recognition_requests,
                completed=self.completed,
                failed=self.failed,
                timed_out=self.timed_out,
                p50_latency_ms=_percentile(values, 0.50),
                p95_latency_ms=_percentile(values, 0.95),
                stage_latency_ms={
                    stage: {
                        "sample_count": len(samples),
                        "p50_ms": _percentile(sorted(samples), 0.50) or 0.0,
                        "p95_ms": _percentile(sorted(samples), 0.95) or 0.0,
                    }
                    for stage, samples in self._stage_durations.items()
                    if samples
                },
                process_cpu_seconds=process_times.user + process_times.system,
                process_rss_bytes=process.memory_info().rss,
                host_cpu_percent=psutil.cpu_percent(interval=None),
                host_memory_used_bytes=host_memory.used,
                host_memory_total_bytes=host_memory.total,
            )


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    index = max(0, math.ceil(percentile * len(values)) - 1)
    return round(values[index], 3)


class RequestSizeLimitMiddleware:
    """Bound request bodies, including chunked uploads, before JSON parsing."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        content_length = _header(scope, b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    await _send_error(
                        scope,
                        receive,
                        send,
                        413,
                        "request_too_large",
                        "Request body exceeds the configured limit.",
                    )
                    return
            except ValueError:
                await _send_error(
                    scope,
                    receive,
                    send,
                    400,
                    "invalid_content_length",
                    "Request content length is invalid.",
                )
                return

        body = bytearray()
        body_size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] == "http.request":
                body_size += len(message.get("body", b""))
                if body_size > self.max_bytes:
                    await _send_error(
                        scope,
                        receive,
                        send,
                        413,
                        "request_too_large",
                        "Request body exceeds the configured limit.",
                    )
                    return
                body.extend(message.get("body", b""))
                if not message.get("more_body", False):
                    break

        request_body = bytes(body)
        del body
        body_delivered = False

        async def replay_receive() -> Message:
            nonlocal body_delivered
            if not body_delivered:
                body_delivered = True
                return {
                    "type": "http.request",
                    "body": request_body,
                    "more_body": False,
                }
            return await receive()

        await self.app(scope, replay_receive, send)


async def _send_error(
    scope: Scope,
    receive: Receive,
    send: Send,
    status: int,
    code: str,
    message: str,
) -> None:
    response = JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
    )
    await response(scope, receive, send)


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return cast(bytes, value).decode("latin-1")
    return None


def create_app(
    *,
    settings: AISettings | None = None,
    runner: RecognitionRunner | None = None,
    gallery_cache: SessionGalleryCache | None = None,
    gallery_provider: SessionGalleryProvider | None = None,
) -> FastAPI:
    configured = settings or AISettings.from_env()
    psutil.cpu_percent(interval=None)
    app = FastAPI(
        title="Presensi Central AI Service",
        version="0.2.0",
        description="Transient central inference for trusted edge devices.",
    )
    app.state.settings = configured
    app.state.authenticator = DeviceAuthenticator(configured.device_tokens)
    app.state.rate_limiter = DeviceRateLimiter(
        rate=configured.rate_limit_per_second,
        capacity=configured.rate_limit_burst,
    )
    app.state.gallery_cache = gallery_cache or SessionGalleryCache(
        max_age_seconds=configured.gallery_max_age_seconds
    )
    configured_provider = gallery_provider
    if (
        configured_provider is None
        and configured.core_api_base_url is not None
        and configured.model_version is not None
    ):
        configured_provider = CoreApiGalleryProvider(
            configured.core_api_base_url,
            model_name=SFaceModel.model_name,
            model_version=configured.model_version,
            timeout_seconds=configured.inference_timeout_seconds,
        )
    app.state.gallery_provider = configured_provider
    app.state.runner = runner if runner is not None else build_model_runner(configured)
    app.state.metrics = BasicMetrics()
    device_session_grants: dict[tuple[UUID, UUID], tuple[bytes, datetime]] = {}

    def has_cached_device_session_grant(
        device_id: UUID,
        session_id: UUID,
        token: str | None,
        gallery: SessionGallery | None,
    ) -> bool:
        if not token or gallery is None:
            return False
        grant = device_session_grants.get((device_id, session_id))
        if grant is None or grant[1] <= datetime.now(UTC):
            device_session_grants.pop((device_id, session_id), None)
            return False
        return secrets.compare_digest(
            grant[0], hashlib.sha256(token.encode("ascii")).digest()
        )

    def cache_device_session_grant(
        device_id: UUID,
        session_id: UUID,
        token: str | None,
        gallery: SessionGallery | None,
    ) -> None:
        if token and gallery is not None:
            device_session_grants[(device_id, session_id)] = (
                hashlib.sha256(token.encode("ascii")).digest(),
                gallery.expires_at,
            )

    async def reset_session_tracks(device_id: UUID, session_id: UUID) -> None:
        active_runner = cast(RecognitionRunner | None, app.state.runner)
        if active_runner is not None:
            await asyncio.to_thread(
                active_runner.invalidate_session,
                device_id,
                session_id,
            )

    async def invalidate_session_state(device_id: UUID, session_id: UUID) -> None:
        app.state.gallery_cache.invalidate(device_id, session_id)
        await reset_session_tracks(device_id, session_id)

    async def install_gallery_snapshot(gallery: SessionGallery) -> None:
        app.state.gallery_cache.install(gallery)
        await reset_session_tracks(gallery.device_id, gallery.session_id)

    app.state.install_gallery_snapshot = install_gallery_snapshot
    app.add_middleware(
        RequestSizeLimitMiddleware, max_bytes=configured.max_request_bytes
    )
    bearer_scheme = HTTPBearer(auto_error=False)

    @app.exception_handler(ServiceError)
    async def handle_service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return _error(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Omit rejected input values so base64 frames never echo back into responses.
        safe_errors = [
            {
                "loc": [str(part) for part in item.get("loc", ())],
                "type": str(item.get("type", "validation_error")),
                "message": str(item.get("msg", "Invalid request.")),
            }
            for item in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request data did not pass validation.",
                    "fields": safe_errors,
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        del exc
        return _error(500, "internal_error", "The request could not be completed.")

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics", response_model=Metrics, tags=["system"])
    async def metrics() -> Metrics:
        active_metrics = cast(BasicMetrics, app.state.metrics)
        return await active_metrics.snapshot()

    @app.post(
        "/api/v1/recognition/sessions/{session_id}/bursts",
        response_model=BurstDecisionResponse,
        responses={
            401: {"model": ErrorResponse},
            413: {"model": ErrorResponse},
            429: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
            504: {"model": ErrorResponse},
        },
        tags=["recognition"],
    )
    async def recognize_burst(
        session_id: UUID,
        payload: BurstInput,
        response: Response,
        x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
        x_benchmark_timing: bool = Header(default=False, alias="X-Benchmark-Timing"),
        credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    ) -> BurstDecisionResponse:
        started = time.perf_counter()
        outcome = "failed"
        stage_durations_ms: dict[str, float] = defaultdict(float)

        def observe_stage(stage: str, duration_ms: float) -> None:
            stage_durations_ms[stage] += duration_ms

        try:
            device_id = app.state.authenticator.authenticate(
                x_device_id,
                (
                    f"{credentials.scheme} {credentials.credentials}"
                    if credentials is not None
                    else None
                ),
            )
            device_token = credentials.credentials if credentials is not None else None
            retry_after = await app.state.rate_limiter.allow(device_id)
            if retry_after is not None:
                response = _error(
                    429,
                    "rate_limited",
                    "Device request rate is above the configured limit.",
                )
                response.headers["Retry-After"] = str(max(1, math.ceil(retry_after)))
                return response  # type: ignore[return-value]

            settings_at_request: AISettings = app.state.settings
            if len(payload.frames) > settings_at_request.max_frames_per_burst:
                raise ServiceError(
                    422,
                    "too_many_frames",
                    "Burst contains more frames than the configured limit.",
                )
            gallery = app.state.gallery_cache.get(device_id, session_id)
            provider: SessionGalleryProvider | None = app.state.gallery_provider
            if provider is not None:
                validate_session = getattr(provider, "validate_device_session", None)
                cached_device_session_grant = has_cached_device_session_grant(
                    device_id, session_id, device_token, gallery
                )
                if callable(validate_session) and not cached_device_session_grant:
                    try:
                        valid_session = await asyncio.wait_for(
                            validate_session(
                                device_id,
                                session_id,
                                device_token=device_token,
                            ),
                            timeout=settings_at_request.inference_timeout_seconds,
                        )
                    except GalleryProviderError as exc:
                        if exc.status_code == 401:
                            raise ServiceError(
                                401,
                                "invalid_device_credentials",
                                "Device authentication failed.",
                            ) from exc
                        outcome = "failed"
                        raise ServiceError(
                            503,
                            "core_api_unavailable",
                            "The Core API could not validate the device session.",
                        ) from exc
                    except TimeoutError as exc:
                        outcome = "timed_out"
                        raise ServiceError(
                            504,
                            "session_validation_timeout",
                            "Device session validation timed out.",
                        ) from exc
                    if not valid_session:
                        device_session_grants.pop((device_id, session_id), None)
                        await reset_session_tracks(device_id, session_id)
                        raise ServiceError(
                            409,
                            "session_inactive",
                            "The attendance session is not active for this device.",
                        )
            if gallery is None and provider is not None:
                try:
                    fetched_gallery = await asyncio.wait_for(
                        provider.fetch_active_session_gallery(
                            device_id,
                            session_id,
                            device_token=device_token,
                        ),
                        timeout=settings_at_request.inference_timeout_seconds,
                    )
                except TimeoutError as exc:
                    outcome = "timed_out"
                    raise ServiceError(
                        504,
                        "gallery_provider_timeout",
                        "Loading the session gallery exceeded the time limit.",
                    ) from exc
                except GalleryProviderError as exc:
                    if exc.status_code == 401:
                        raise ServiceError(
                            401,
                            "invalid_device_credentials",
                            "Device authentication failed.",
                        ) from exc
                    raise ServiceError(
                        503,
                        "session_gallery_unavailable",
                        "The active session gallery could not be loaded.",
                    ) from exc
                except Exception as exc:
                    raise ServiceError(
                        503,
                        "session_gallery_unavailable",
                        "The active session gallery could not be loaded.",
                    ) from exc
                if fetched_gallery is not None:
                    if (
                        fetched_gallery.device_id != device_id
                        or fetched_gallery.session_id != session_id
                    ):
                        raise ServiceError(
                            502,
                            "invalid_session_gallery",
                            "Gallery provider returned a different device or session.",
                        )
                    try:
                        await app.state.install_gallery_snapshot(fetched_gallery)
                    except ValueError as exc:
                        raise ServiceError(
                            502,
                            "invalid_session_gallery",
                            "Gallery provider returned an invalid active snapshot.",
                        ) from exc
                    gallery = app.state.gallery_cache.get(device_id, session_id)
                if not cached_device_session_grant:
                    cache_device_session_grant(
                        device_id, session_id, device_token, gallery
                    )
            if gallery is None:
                await reset_session_tracks(device_id, session_id)
                raise ServiceError(
                    503,
                    "session_gallery_unavailable",
                    "No current active-session gallery is available for this device.",
                )
            if (
                settings_at_request.model_version is not None
                and gallery.model_version != settings_at_request.model_version
            ):
                await invalidate_session_state(device_id, session_id)
                raise ServiceError(
                    409,
                    "model_version_mismatch",
                    "Session gallery model version does not match this service.",
                )
            if gallery.model_name != SFaceModel.model_name:
                await invalidate_session_state(device_id, session_id)
                raise ServiceError(
                    409,
                    "template_model_mismatch",
                    "Session gallery templates use an unsupported recognition model.",
                )
            active_runner: RecognitionRunner | None = app.state.runner
            if active_runner is None:
                raise ServiceError(
                    503,
                    "model_not_configured",
                    "Local recognition models and calibrated thresholds are required.",
                )
            decoded = await asyncio.to_thread(
                _decode_frames,
                payload,
                settings_at_request,
            )
            try:
                decision = await active_runner.process_burst(
                    device_id=device_id,
                    session_id=session_id,
                    track_id=payload.track_id,
                    frames=decoded,
                    gallery=gallery,
                    timeout_seconds=settings_at_request.inference_timeout_seconds,
                    timing_observer=(
                        observe_stage
                        if settings_at_request.benchmark_timing_enabled
                        else None
                    ),
                )
            except InferenceBusyError as exc:
                raise ServiceError(
                    503,
                    "inference_busy",
                    "The inference worker is still processing another burst.",
                ) from exc
            except TimeoutError as exc:
                outcome = "timed_out"
                raise ServiceError(
                    504,
                    "inference_timeout",
                    "Recognition exceeded the configured time limit.",
                ) from exc
            outcome = "completed"
            if settings_at_request.benchmark_timing_enabled and x_benchmark_timing:
                response.headers["X-Recognition-Stage-Timings-Ms"] = json.dumps(
                    stage_durations_ms,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                response.headers["X-Recognition-Gallery-Template-Count"] = str(
                    len(gallery.entries)
                )
            candidate = None
            if decision.decision.student_id is not None:
                candidate = CandidateMetadata(
                    student_id=decision.decision.student_id,
                    confidence=decision.decision.confidence,
                    margin=decision.decision.margin,
                )
            return BurstDecisionResponse(
                session_id=session_id,
                track_id=payload.track_id,
                status=decision.status,
                outcome=decision.decision.outcome,
                candidate=candidate,
                reason_code=decision.decision.reason_code,
                liveness_score=decision.decision.liveness_score,
                observations=decision.observation_count,
                frames_processed=len(decoded),
                model_version=gallery.model_version,
            )
        except ImageDecodeError as exc:
            raise ServiceError(422, "invalid_image", str(exc)) from exc
        finally:
            await app.state.metrics.observe(
                (time.perf_counter() - started) * 1000,
                outcome,
                stage_durations_ms
                if app.state.settings.benchmark_timing_enabled
                else None,
            )

    @app.delete(
        "/api/v1/recognition/sessions/{session_id}/cache",
        status_code=204,
        tags=["recognition"],
    )
    async def invalidate_session_cache(
        session_id: UUID,
        x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
        credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    ) -> Response:
        device_id = app.state.authenticator.authenticate(
            x_device_id,
            (
                f"{credentials.scheme} {credentials.credentials}"
                if credentials is not None
                else None
            ),
        )
        device_token = credentials.credentials if credentials is not None else None
        provider = app.state.gallery_provider
        validate_device = getattr(provider, "validate_device", None)
        if callable(validate_device):
            try:
                valid_device = await asyncio.wait_for(
                    validate_device(device_id, device_token=device_token),
                    timeout=app.state.settings.inference_timeout_seconds,
                )
            except GalleryProviderError as exc:
                if exc.status_code == 401:
                    raise ServiceError(
                        401,
                        "invalid_device_credentials",
                        "Device authentication failed.",
                    ) from exc
                raise ServiceError(
                    503,
                    "core_api_unavailable",
                    "The Core API could not validate the device.",
                ) from exc
            if not valid_device:
                raise ServiceError(
                    401, "invalid_device_credentials", "Device authentication failed."
                )
        await invalidate_session_state(device_id, session_id)
        device_session_grants.pop((device_id, session_id), None)
        return Response(status_code=204)

    return app


def _decode_frames(
    payload: BurstInput,
    settings: AISettings,
) -> tuple[CapturedFrame, ...]:
    decoded: list[CapturedFrame] = []
    for frame in payload.frames:
        # Check encoded length before allocating the decoded byte buffer.
        if len(frame.image_base64) > 4 * math.ceil(settings.max_frame_bytes / 3):
            raise ImageDecodeError("Image payload exceeds the frame limit.")
        image = decode_image(
            frame.image_base64,
            frame.content_type,
            max_encoded_bytes=settings.max_frame_bytes,
            max_width=settings.max_image_width,
            max_height=settings.max_image_height,
            max_pixels=settings.max_image_pixels,
        )
        decoded.append(CapturedFrame(image=image, captured_at=frame.captured_at))
    return tuple(decoded)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
    )


app = create_app()
