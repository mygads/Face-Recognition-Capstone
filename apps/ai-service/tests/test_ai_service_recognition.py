from __future__ import annotations

import asyncio
import base64
import io
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI
from PIL import Image, ImageDraw

from presensi_ai_service.config import AISettings
from presensi_ai_service.gallery_cache import SessionGallery, SessionGalleryCache
from presensi_ai_service.gallery_provider import GalleryProviderError
from presensi_ai_service.inference import RecognitionRunner
from presensi_ai_service.main import create_app
from recognition_core.domain import (
    BoundingBox,
    CandidateMatch,
    FaceDetection,
    FaceEmbedding,
    FaceQuality,
    RecognitionDecision,
    TrackDecision,
)
from recognition_core.liveness import LivenessConfig
from recognition_core.pipeline import RecognitionPipeline
from recognition_core.temporal import MultiFrameDecisionEngine, TemporalDecisionConfig
from recognition_core.testing import (
    FakeFaceAligner,
    FakeFaceDetector,
    FakeFaceEmbedder,
    FakeFaceQualityAssessor,
    FakeMatcher,
    FakePreprocessor,
)

DEVICE_ID = UUID("84f5ad7d-d294-4e10-9a3a-4079f19d0925")
SESSION_ID = UUID("70f7ff5b-3700-4b1c-b99b-d2a731cf2b2e")
STUDENT_ID = UUID("bf278579-d605-4c65-8e7c-01d2df579815")
DEVICE_TOKEN = "test-device-token-that-is-not-a-production-secret"
MODEL_NAME = "opencv-zoo-sface"
MODEL_VERSION = "fixture-v1"


def _image_bytes() -> bytes:
    image = Image.new("RGB", (64, 64), color=(80, 100, 120))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 55, 55), outline=(230, 40, 70), width=3)
    draw.line((8, 32, 55, 32), fill=(10, 240, 80), width=2)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _gallery(*, now: datetime | None = None) -> SessionGallery:
    current = now or datetime.now(UTC)
    embedding = FaceEmbedding(
        values=(1.0, 0.0),
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
        normalized=True,
    )
    from recognition_core.domain import GalleryEntry

    return SessionGallery(
        device_id=DEVICE_ID,
        session_id=SESSION_ID,
        status="active",
        generated_at=current - timedelta(seconds=2),
        session_ends_at=current + timedelta(hours=1),
        expires_at=current + timedelta(minutes=5),
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
        entries=(GalleryEntry(student_id=STUDENT_ID, embedding=embedding),),
    )


def _pipeline() -> RecognitionPipeline:
    calls: list[str] = []
    detected = FaceDetection(
        box=BoundingBox(2, 2, 40, 40),
        confidence=0.99,
    )
    embedding = FaceEmbedding(
        values=(1.0, 0.0),
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
        normalized=True,
    )
    return RecognitionPipeline(
        preprocessor=FakePreprocessor(calls),
        detector=FakeFaceDetector(calls, (detected,)),
        quality_assessor=FakeFaceQualityAssessor(
            calls,
            FaceQuality(score=0.95, acceptable=True),
        ),
        aligner=FakeFaceAligner(calls),
        liveness_config=LivenessConfig(enabled=False, required=False),
        liveness_model=None,
        embedder=FakeFaceEmbedder(calls, embedding),
        matcher=FakeMatcher(
            calls,
            (CandidateMatch(student_id=STUDENT_ID, similarity=0.92),),
        ),
        temporal_decision=MultiFrameDecisionEngine(
            TemporalDecisionConfig(
                min_top1_similarity=0.8,
                min_top1_top2_margin=0.1,
                minimum_agreeing_frames=3,
                sample_every_n_frames=1,
                best_frame_count=3,
                max_history_frames=3,
            )
        ),
    )


def _settings(**overrides: object) -> AISettings:
    values: dict[str, object] = {
        "device_tokens": {DEVICE_ID: DEVICE_TOKEN},
        "model_version": MODEL_VERSION,
        "min_top1_similarity": 0.8,
        "min_top1_top2_margin": 0.1,
    }
    values.update(overrides)
    return AISettings(**values)  # type: ignore[arg-type]


def _app(
    *, settings: AISettings | None = None, runner: RecognitionRunner | None = None
) -> FastAPI:
    cache = SessionGalleryCache(max_age_seconds=300)
    cache.install(_gallery())
    return create_app(
        settings=settings or _settings(),
        runner=runner or RecognitionRunner(_pipeline()),
        gallery_cache=cache,
    )


def _body(frame_bytes: bytes | None = None, *, count: int = 3) -> dict[str, object]:
    content = frame_bytes if frame_bytes is not None else _image_bytes()
    first_time = datetime.now(UTC)
    return {
        "track_id": "camera-track-7",
        "frames": [
            {
                "captured_at": (
                    first_time + timedelta(milliseconds=index * 50)
                ).isoformat(),
                "content_type": "image/png",
                "image_base64": base64.b64encode(content).decode("ascii"),
            }
            for index in range(count)
        ],
    }


def _headers(device_id: UUID = DEVICE_ID, token: str = DEVICE_TOKEN) -> dict[str, str]:
    return {
        "X-Device-ID": str(device_id),
        "Authorization": f"Bearer {token}",
    }


def test_valid_burst_runs_shared_pipeline_and_returns_only_decision_metadata() -> None:
    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.post(
                f"/api/v1/recognition/sessions/{SESSION_ID}/bursts",
                headers=_headers(),
                json=_body(),
            )

    response = asyncio.run(exercise())

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "ACCEPTED"
    assert result["outcome"] == "matched"
    assert result["candidate"]["student_id"] == str(STUDENT_ID)
    assert result["frames_processed"] == 3
    assert result["model_version"] == MODEL_VERSION
    assert "image_base64" not in response.text
    assert "embedding" not in response.text


def test_opt_in_benchmark_timings_and_process_metrics_are_available() -> None:
    app = _app(settings=_settings(benchmark_timing_enabled=True))

    async def exercise() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.post(
                f"/api/v1/recognition/sessions/{SESSION_ID}/bursts",
                headers={**_headers(), "X-Benchmark-Timing": "true"},
                json=_body(),
            )
            metrics = await client.get("/metrics")
            return response, metrics

    response, metrics = asyncio.run(exercise())

    assert response.status_code == 200
    stage_timings = response.headers["X-Recognition-Stage-Timings-Ms"]
    assert '"detect"' in stage_timings
    assert '"embed"' in stage_timings
    assert response.headers["X-Recognition-Gallery-Template-Count"] == "1"
    metrics_json = metrics.json()
    assert metrics_json["stage_latency_ms"]["detect"]["sample_count"] == 1
    assert metrics_json["process_cpu_seconds"] >= 0
    assert metrics_json["process_rss_bytes"] > 0
    assert metrics_json["host_memory_total_bytes"] > 0


def test_benchmark_timing_header_is_not_returned_by_default() -> None:
    app = _app()

    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.post(
                f"/api/v1/recognition/sessions/{SESSION_ID}/bursts",
                headers={**_headers(), "X-Benchmark-Timing": "true"},
                json=_body(),
            )

    response = asyncio.run(exercise())

    assert response.status_code == 200
    assert "X-Recognition-Stage-Timings-Ms" not in response.headers
    assert "X-Recognition-Gallery-Template-Count" not in response.headers


def test_benchmark_timing_configuration_defaults_off_and_is_opt_in() -> None:
    assert AISettings.from_env({}).benchmark_timing_enabled is False
    assert (
        AISettings.from_env(
            {"PRESENSI_AI_BENCHMARK_TIMING_ENABLED": "true"}
        ).benchmark_timing_enabled
        is True
    )


def test_oversized_request_is_rejected_before_json_or_image_decode() -> None:
    app = _app(settings=_settings(max_request_bytes=512, max_frame_bytes=128))

    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:

            async def chunks() -> AsyncIterator[bytes]:
                yield b"{" + b"x" * 400
                yield b"x" * 400

            return await client.post(
                f"/api/v1/recognition/sessions/{SESSION_ID}/bursts",
                headers=_headers(),
                content=chunks(),
            )

    response = asyncio.run(exercise())

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_corrupt_image_is_rejected_without_echoing_payload() -> None:
    corrupt = b"this is not an image"

    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.post(
                f"/api/v1/recognition/sessions/{SESSION_ID}/bursts",
                headers=_headers(),
                json=_body(corrupt, count=1),
            )

    response = asyncio.run(exercise())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_image"
    assert base64.b64encode(corrupt).decode("ascii") not in response.text


def test_invalid_device_credentials_are_rejected() -> None:
    unknown_device = uuid4()

    async def exercise() -> httpx.Response:
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.post(
                f"/api/v1/recognition/sessions/{SESSION_ID}/bursts",
                headers=_headers(device_id=unknown_device),
                json=_body(count=1),
            )

    response = asyncio.run(exercise())

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_device_credentials"


def test_per_device_burst_rate_limit_returns_retry_after() -> None:
    app = _app(settings=_settings(rate_limit_burst=1, rate_limit_per_second=0.1))

    async def exercise() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            url = f"/api/v1/recognition/sessions/{SESSION_ID}/bursts"
            first = await client.post(url, headers=_headers(), json=_body(count=1))
            second = await client.post(url, headers=_headers(), json=_body(count=1))
            return first, second

    first, second = asyncio.run(exercise())

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "10"


def test_inference_timeout_returns_gateway_timeout_and_updates_metrics() -> None:
    class SlowPipeline:
        max_candidates = 2
        temporal_decision = object()

        def process(self, *_: object) -> TrackDecision:
            time.sleep(0.15)
            return TrackDecision(
                track_id="slow-track",
                state="accepted",
                decision=RecognitionDecision(
                    outcome="matched",
                    student_id=STUDENT_ID,
                    confidence=0.96,
                    margin=0.5,
                ),
                observation_count=3,
            )

    app = _app(
        settings=_settings(inference_timeout_seconds=0.02),
        runner=RecognitionRunner(cast(RecognitionPipeline, SlowPipeline())),
    )

    async def exercise() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.post(
                f"/api/v1/recognition/sessions/{SESSION_ID}/bursts",
                headers=_headers(),
                json=_body(count=1),
            )
            metrics = await client.get("/metrics")
            return response, metrics

    response, metrics = asyncio.run(exercise())

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "inference_timeout"
    assert metrics.json()["timed_out"] == 1
    assert metrics.json()["p50_latency_ms"] is not None


def test_health_and_cache_invalidation_are_available() -> None:
    app = _app()

    async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            health = await client.get("/health")
            invalidated = await client.delete(
                f"/api/v1/recognition/sessions/{SESSION_ID}/cache",
                headers=_headers(),
            )
            request = await client.post(
                f"/api/v1/recognition/sessions/{SESSION_ID}/bursts",
                headers=_headers(),
                json=_body(count=1),
            )
            return health, invalidated, request

    health, invalidated, request = asyncio.run(exercise())

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert invalidated.status_code == 204
    assert request.status_code == 503
    assert request.json()["error"]["code"] == "session_gallery_unavailable"


def test_provider_populates_memory_cache_and_invalidation_forces_refresh() -> None:
    class Provider:
        calls = 0

        async def fetch_active_session_gallery(
            self,
            device_id: UUID,
            session_id: UUID,
            *,
            device_token: str | None = None,
        ) -> SessionGallery | None:
            assert device_token == DEVICE_TOKEN
            self.calls += 1
            snapshot = _gallery()
            assert snapshot.device_id == device_id
            assert snapshot.session_id == session_id
            return snapshot

    provider = Provider()
    cache = SessionGalleryCache(max_age_seconds=300)
    app = create_app(
        settings=_settings(),
        runner=RecognitionRunner(_pipeline()),
        gallery_cache=cache,
        gallery_provider=provider,
    )

    async def exercise() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            url = f"/api/v1/recognition/sessions/{SESSION_ID}/bursts"
            first = await client.post(url, headers=_headers(), json=_body(count=1))
            second = await client.post(url, headers=_headers(), json=_body(count=1))
            await client.delete(
                f"/api/v1/recognition/sessions/{SESSION_ID}/cache",
                headers=_headers(),
            )
            third = await client.post(url, headers=_headers(), json=_body(count=1))
            return first, second, third

    first, second, third = asyncio.run(exercise())

    assert [first.status_code, second.status_code, third.status_code] == [200, 200, 200]
    assert provider.calls == 2


def test_validated_gallery_continues_during_bounded_core_api_outage() -> None:
    class Provider:
        online = True
        validation_calls = 0
        fetch_calls = 0

        async def validate_device_session(
            self,
            device_id: UUID,
            session_id: UUID,
            *,
            device_token: str | None = None,
        ) -> bool:
            assert device_id == DEVICE_ID
            assert session_id == SESSION_ID
            assert device_token == DEVICE_TOKEN
            self.validation_calls += 1
            if not self.online:
                raise GalleryProviderError(None)
            return True

        async def fetch_active_session_gallery(
            self,
            device_id: UUID,
            session_id: UUID,
            *,
            device_token: str | None = None,
        ) -> SessionGallery | None:
            assert device_token == DEVICE_TOKEN
            self.fetch_calls += 1
            snapshot = _gallery()
            assert snapshot.device_id == device_id
            assert snapshot.session_id == session_id
            return snapshot

    provider = Provider()
    app = create_app(
        settings=_settings(),
        runner=RecognitionRunner(_pipeline()),
        gallery_provider=provider,
    )

    async def exercise() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            url = f"/api/v1/recognition/sessions/{SESSION_ID}/bursts"
            first = await client.post(url, headers=_headers(), json=_body(count=1))
            provider.online = False
            second = await client.post(url, headers=_headers(), json=_body(count=1))
            return first, second

    first, second = asyncio.run(exercise())
    assert first.status_code == second.status_code == 200
    assert provider.validation_calls == 1
    assert provider.fetch_calls == 1
