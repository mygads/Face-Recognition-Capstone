from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

BENCHMARK = Path(__file__).with_name("benchmark.py")


def _load_benchmark_module() -> Any:
    spec = importlib.util.spec_from_file_location("deployment_benchmark", BENCHMARK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


benchmark = _load_benchmark_module()


def test_missing_hardware_writes_pending_csv_json_and_markdown(
    tmp_path: Path,
) -> None:
    output = tmp_path / "report"
    result = subprocess.run(
        [
            sys.executable,
            str(BENCHMARK),
            "--output-dir",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert report["overall_status"] == "PENDING HARDWARE"
    assert set(report["profiles"]) == {"AI_EDGE", "AI_CENTRAL"}
    for profile in report["profiles"].values():
        for scenario in profile["scenarios"].values():
            assert scenario["status"] == "PENDING HARDWARE"
            assert scenario["decision_latency_p50_ms"] is None
            assert scenario["decision_latency_p95_ms"] is None
            assert scenario["terminal_decisions"] is None
            assert scenario["network_application_bytes_per_event"] is None
            assert scenario["inference_stage_latency_ms"] == {}

    summary_csv = (output / "summary.csv").read_text(encoding="utf-8")
    summary_md = (output / "summary.md").read_text(encoding="utf-8")
    assert "PENDING HARDWARE" in summary_csv
    assert "PENDING HARDWARE" in summary_md
    assert "No performance values are synthesized" in summary_md
    assert (output / "samples.csv").is_file()


def test_central_runner_measures_http_bytes_and_retry_rate() -> None:
    calls = 0

    def respond(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"error": {"code": "inference_busy"}})
        status = "COLLECTING" if calls == 2 else "ACCEPTED"
        detect_time = 1.25 if calls == 2 else 2.75
        return httpx.Response(
            200,
            json={"status": status},
            headers={
                "X-Recognition-Stage-Timings-Ms": json.dumps(
                    {"detect": detect_time, "embed": 0.5}
                ),
                "X-Recognition-Gallery-Template-Count": "25",
            },
        )

    worker = benchmark.CentralWorker(
        "http://central.test",
        benchmark.CentralLab(
            str(UUID(int=1)),
            str(UUID(int=2)),
            "synthetic-test-token",
        ),
        b"synthetic-jpeg-bytes",
        "image/jpeg",
        timeout_seconds=1,
        retry_attempts=1,
        retry_backoff_ms=0,
        transport=httpx.MockTransport(respond),
    )
    try:
        sample = worker.run("sequential", 1, 1)
    finally:
        worker.close()

    assert sample.success is True
    assert sample.decision_terminal is True
    assert sample.attempt_count == 3
    assert sample.retry_count == 1
    assert sample.burst_count == 2
    assert sample.gallery_size == 25
    assert sample.model_version is None
    assert sample.request_bytes is not None and sample.request_bytes > 0
    assert sample.response_bytes is not None and sample.response_bytes > 0
    assert sample.stage_latency_ms == {"detect": 4.0, "embed": 1.0}
    summary = benchmark._summarize_scenario(
        [sample],
        elapsed_seconds=1.0,
        edge_stats=None,
        server_stats=None,
    )
    assert summary["network_application_bytes_per_event"] == (
        sample.request_bytes + sample.response_bytes
    )


def test_terminal_latency_excludes_tracks_left_collecting() -> None:
    terminal = benchmark.RequestSample(
        profile="AI_EDGE",
        scenario="sequential",
        request_number=1,
        lab_number=1,
        success=True,
        latency_ms=100.0,
        decision_status="ACCEPTED",
        decision_terminal=True,
        attempt_count=1,
        retry_count=0,
        burst_count=1,
        stage_latency_ms={"detect": 10.0},
    )
    incomplete = benchmark.RequestSample(
        profile="AI_EDGE",
        scenario="sequential",
        request_number=2,
        lab_number=1,
        success=False,
        latency_ms=500.0,
        decision_status="COLLECTING",
        decision_terminal=False,
        attempt_count=5,
        retry_count=0,
        burst_count=5,
        stage_latency_ms={"detect": 50.0},
    )

    result = benchmark._summarize_scenario(
        [terminal, incomplete],
        elapsed_seconds=2.0,
        edge_stats=None,
        server_stats=None,
    )

    assert result["terminal_decisions"] == 1
    assert result["incomplete_decisions"] == 1
    assert result["decision_latency_p50_ms"] == 100.0
    assert result["response_latency_p95_ms"] == 500.0
    assert result["inference_stage_latency_ms"]["detect"]["p50_ms"] == 10.0
    assert result["network_application_bytes_per_event"] is None
