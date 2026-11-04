"""Deployment env parity: documented/production env must reach the containers.

Regression guard: several PRESENSI_* settings were read by the API/AI service
with code defaults while the production compose overlays and env examples did
not forward them, so operator-provided values were silently ignored.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# API settings consumed via os.getenv with a default; every production path
# (local .env example, root compose, AI_EDGE compose, AI_CENTRAL env example)
# must expose them.
API_VARS = (
    "PRESENSI_RECOGNITION_EVENT_RETENTION_DAYS",
    "PRESENSI_RETENTION_SWEEP_HOURS",
    "PRESENSI_EVENT_FUTURE_SKEW_SECONDS",
    "PRESENSI_DEVICE_QUEUE_WARNING_DEPTH",
)

# DB pool/timeout guards (R18 pool + R19 statement-timeout/NullPool): operator
# values must reach the API container or they are silently ignored.
DB_VARS = (
    "PRESENSI_DB_POOL_SIZE",
    "PRESENSI_DB_MAX_OVERFLOW",
    "PRESENSI_DB_POOL_TIMEOUT",
    "PRESENSI_DB_POOL_RECYCLE",
    "PRESENSI_DB_STATEMENT_TIMEOUT_MS",
    "PRESENSI_DB_POOL_DISABLED",
)

# WS/dashboard tick tunable (R19b): operator value must reach the container.
WS_VARS = ("PRESENSI_SESSION_DASHBOARD_POLL_SECONDS",)

# Login brute-force guards: per-email + per-IP attempts per minute.
AUTH_VARS = (
    "PRESENSI_AUTH_LOGIN_EMAIL_ATTEMPTS_PER_MINUTE",
    "PRESENSI_AUTH_LOGIN_IP_ATTEMPTS_PER_MINUTE",
)

# Central-AI detector operating point; the env example documents them so the
# overlay must forward them into the ai-service container.
AI_VARS = (
    "PRESENSI_AI_YUNET_SCORE_THRESHOLD",
    "PRESENSI_AI_YUNET_NMS_THRESHOLD",
)


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_api_retention_and_queue_vars_reach_production_compose() -> None:
    edge_compose = _read("infra/deployment/compose.ai-edge.yml")
    root_compose = _read("docker-compose.yml")
    for name in API_VARS + DB_VARS + WS_VARS + AUTH_VARS:
        assert name in edge_compose, f"{name} missing from compose.ai-edge.yml"
        assert name in root_compose, f"{name} missing from docker-compose.yml"


def test_api_retention_and_queue_vars_documented_in_env_examples() -> None:
    for example in (
        ".env.example",
        "infra/deployment/ai-edge.env.example",
        "infra/deployment/ai-central.env.example",
    ):
        content = _read(example)
        for name in API_VARS + DB_VARS + WS_VARS + AUTH_VARS:
            assert name in content, f"{name} missing from {example}"


def test_central_ai_detector_thresholds_forwarded_to_container() -> None:
    overlay = _read("infra/deployment/compose.ai-central.yml")
    central_example = _read("infra/deployment/ai-central.env.example")
    root_compose = _read("docker-compose.yml")
    for name in AI_VARS:
        assert name in overlay, f"{name} missing from compose.ai-central.yml"
        assert name in central_example, f"{name} missing from ai-central.env.example"
        assert name in root_compose, f"{name} missing from docker-compose.yml"


# Enrollment face-quality gates (R33): the API reads these with code
# defaults, so unfriendly captures were accepted/rejected by invisible values.
ENROLLMENT_QUALITY_VARS = (
    "PRESENSI_ENROLLMENT_MIN_FACE_PIXELS",
    "PRESENSI_ENROLLMENT_MIN_SHARPNESS",
    "PRESENSI_ENROLLMENT_MIN_BRIGHTNESS",
    "PRESENSI_ENROLLMENT_MAX_BRIGHTNESS",
)

# AI service payload/quality guards (R33): oversized frames and weak faces
# were governed by invisible code defaults in every container.
AI_QUALITY_VARS = (
    "PRESENSI_AI_MAX_REQUEST_BYTES",
    "PRESENSI_AI_MAX_FRAME_BYTES",
    "PRESENSI_AI_MAX_IMAGE_WIDTH",
    "PRESENSI_AI_MAX_IMAGE_HEIGHT",
    "PRESENSI_AI_MAX_IMAGE_PIXELS",
    "PRESENSI_AI_MIN_FACE_PIXELS",
    "PRESENSI_AI_MIN_LAPLACIAN_VARIANCE",
    "PRESENSI_AI_MIN_BRIGHTNESS",
    "PRESENSI_AI_MAX_BRIGHTNESS",
)


def test_enrollment_quality_vars_reach_production_compose_and_examples() -> None:
    edge_compose = _read("infra/deployment/compose.ai-edge.yml")
    root_compose = _read("docker-compose.yml")
    for name in ENROLLMENT_QUALITY_VARS:
        assert name in edge_compose, f"{name} missing from compose.ai-edge.yml"
        assert name in root_compose, f"{name} missing from docker-compose.yml"
    for example in (
        ".env.example",
        "infra/deployment/ai-edge.env.example",
        "infra/deployment/ai-central.env.example",
    ):
        content = _read(example)
        for name in ENROLLMENT_QUALITY_VARS:
            assert name in content, f"{name} missing from {example}"


def test_ai_quality_guards_forwarded_to_container_and_documented() -> None:
    overlay = _read("infra/deployment/compose.ai-central.yml")
    central_example = _read("infra/deployment/ai-central.env.example")
    root_compose = _read("docker-compose.yml")
    local_example = _read(".env.example")
    for name in AI_QUALITY_VARS:
        assert name in overlay, f"{name} missing from compose.ai-central.yml"
        assert name in central_example, f"{name} missing from ai-central.env.example"
        assert name in root_compose, f"{name} missing from docker-compose.yml"
        assert name in local_example, f"{name} missing from .env.example"


# Central-AI burst-consensus profile (R24): without forwarding, operator
# tuning of the consensus knobs is silently ignored and code defaults win.
AI_CONSENSUS_VARS = (
    "PRESENSI_AI_MAX_FRAMES",
    "PRESENSI_AI_MINIMUM_AGREEING_FRAMES",
    "PRESENSI_AI_SAMPLE_EVERY_N_FRAMES",
    "PRESENSI_AI_BEST_FRAME_COUNT",
    "PRESENSI_AI_MAX_HISTORY_FRAMES",
)


def test_central_ai_consensus_profile_forwarded_to_container() -> None:
    overlay = _read("infra/deployment/compose.ai-central.yml")
    central_example = _read("infra/deployment/ai-central.env.example")
    root_compose = _read("docker-compose.yml")
    for name in AI_CONSENSUS_VARS:
        assert name in overlay, f"{name} missing from compose.ai-central.yml"
        assert name in central_example, f"{name} missing from ai-central.env.example"
        assert name in root_compose, f"{name} missing from docker-compose.yml"
