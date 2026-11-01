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
    for name in API_VARS:
        assert name in edge_compose, f"{name} missing from compose.ai-edge.yml"
        assert name in root_compose, f"{name} missing from docker-compose.yml"


def test_api_retention_and_queue_vars_documented_in_env_examples() -> None:
    for example in (
        ".env.example",
        "infra/deployment/ai-edge.env.example",
        "infra/deployment/ai-central.env.example",
    ):
        content = _read(example)
        for name in API_VARS:
            assert name in content, f"{name} missing from {example}"


def test_central_ai_detector_thresholds_forwarded_to_container() -> None:
    overlay = _read("infra/deployment/compose.ai-central.yml")
    central_example = _read("infra/deployment/ai-central.env.example")
    root_compose = _read("docker-compose.yml")
    for name in AI_VARS:
        assert name in overlay, f"{name} missing from compose.ai-central.yml"
        assert name in central_example, f"{name} missing from ai-central.env.example"
        assert name in root_compose, f"{name} missing from docker-compose.yml"
