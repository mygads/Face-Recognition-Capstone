#!/usr/bin/env python3
"""Reproducible deployment-profile benchmark for AI_EDGE and AI_CENTRAL.

This runner deliberately requires a locally supplied image and provisioned
models/sessions. It never downloads models or creates performance numbers when
those inputs are unavailable.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import math
import os
import platform
import random
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from importlib import metadata
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import cv2
import httpx
import numpy as np
import psutil

from presensi_edge_agent.config import EdgeConfigError, load_config
from presensi_edge_agent.recognition import build_pipeline
from recognition_core.domain import FaceEmbedding, FrameObservation, GalleryEntry

ROOT = Path(__file__).resolve().parents[2]

STAGES = (
    "temporal_sampling",
    "preprocess",
    "detect",
    "quality",
    "align",
    "liveness",
    "embed",
    "match",
    "temporal_decision",
)
SCENARIOS = ("sequential", "two_labs_concurrent")
STATUS_PENDING = "PENDING HARDWARE"


@dataclass(slots=True)
class RequestSample:
    profile: str
    scenario: str
    request_number: int
    lab_number: int
    success: bool
    latency_ms: float | None
    decision_status: str | None
    decision_terminal: bool
    attempt_count: int
    retry_count: int
    burst_count: int
    gallery_size: int | None = None
    model_version: str | None = None
    request_bytes: int | None = None
    response_bytes: int | None = None
    stage_latency_ms: dict[str, float] = field(default_factory=dict)
    error_code: str | None = None


@dataclass(slots=True)
class LocalResourceStats:
    process_cpu_percent_mean: float | None = None
    process_rss_bytes_peak: int | None = None
    host_cpu_percent_mean: float | None = None
    host_memory_used_bytes_mean: int | None = None
    host_memory_total_bytes: int | None = None


@dataclass(slots=True)
class ServerResourceStats:
    process_cpu_percent_mean: float | None = None
    process_rss_bytes_peak: int | None = None
    host_cpu_percent_mean: float | None = None
    host_memory_used_bytes_mean: int | None = None
    host_memory_total_bytes: int | None = None


class LocalResourceMonitor:
    """Sample the benchmark process and host while a workload is running."""

    def __init__(self, interval_seconds: float = 0.2) -> None:
        self.interval_seconds = interval_seconds
        self.process = psutil.Process()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._process_cpu: list[float] = []
        self._process_rss: list[int] = []
        self._host_cpu: list[float] = []
        self._host_memory_used: list[int] = []
        self._host_memory_total: int | None = None

    def __enter__(self) -> LocalResourceMonitor:
        self.process.cpu_percent(interval=None)
        psutil.cpu_percent(interval=None)
        self._sample()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds * 3))
        self._sample()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self._sample()

    def _sample(self) -> None:
        try:
            self._process_cpu.append(self.process.cpu_percent(interval=None))
            self._process_rss.append(self.process.memory_info().rss)
            self._host_cpu.append(psutil.cpu_percent(interval=None))
            memory = psutil.virtual_memory()
            self._host_memory_used.append(memory.used)
            self._host_memory_total = memory.total
        except psutil.Error:
            return

    def result(self) -> LocalResourceStats:
        return LocalResourceStats(
            process_cpu_percent_mean=_mean(self._process_cpu),
            process_rss_bytes_peak=max(self._process_rss, default=None),
            host_cpu_percent_mean=_mean(self._host_cpu),
            host_memory_used_bytes_mean=_mean_int(self._host_memory_used),
            host_memory_total_bytes=self._host_memory_total,
        )


class ServerResourceMonitor:
    """Poll the AI service's process and host metrics during central runs."""

    def __init__(self, base_url: str, interval_seconds: float = 0.25) -> None:
        self.base_url = base_url.rstrip("/")
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client = httpx.Client(timeout=2.0, follow_redirects=False)
        self._samples: list[tuple[float, dict[str, Any]]] = []

    def __enter__(self) -> ServerResourceMonitor:
        self._sample()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds * 3))
        self._sample()
        self._client.close()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self._sample()

    def _sample(self) -> None:
        try:
            response = self._client.get(f"{self.base_url}/metrics")
            if response.status_code < 400:
                payload = response.json()
                if isinstance(payload, dict):
                    self._samples.append((time.perf_counter(), payload))
        except (httpx.HTTPError, ValueError):
            return

    def result(self) -> ServerResourceStats:
        cpu_percent: list[float] = []
        host_cpu: list[float] = []
        host_memory: list[int] = []
        rss: list[int] = []
        total_memory: int | None = None
        for (previous_time, previous), (current_time, current) in zip(
            self._samples, self._samples[1:]
        ):
            elapsed = current_time - previous_time
            if elapsed > 0:
                cpu_delta = float(current["process_cpu_seconds"]) - float(
                    previous["process_cpu_seconds"]
                )
                cpu_percent.append(max(0.0, cpu_delta / elapsed * 100))
        for _, payload in self._samples:
            try:
                rss.append(int(payload["process_rss_bytes"]))
                host_cpu.append(float(payload["host_cpu_percent"]))
                host_memory.append(int(payload["host_memory_used_bytes"]))
                total_memory = int(payload["host_memory_total_bytes"])
            except (KeyError, TypeError, ValueError):
                continue
        return ServerResourceStats(
            process_cpu_percent_mean=_mean(cpu_percent),
            process_rss_bytes_peak=max(rss, default=None),
            host_cpu_percent_mean=_mean(host_cpu),
            host_memory_used_bytes_mean=_mean_int(host_memory),
            host_memory_total_bytes=total_memory,
        )


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 3) if values else None


def _mean_int(values: list[int]) -> int | None:
    return round(statistics.fmean(values)) if values else None


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return round(ordered[index], 3)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _distribution_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _read_image(path: Path | None) -> Any | None:
    if path is None or not path.is_file():
        return None
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    try:
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    except cv2.error:
        return None
    return image if image is not None and image.size else None


def _normalized_random_vector(size: int, seed: int) -> tuple[float, ...]:
    generator = random.Random(seed)
    values = [generator.uniform(-1, 1) for _ in range(size)]
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        raise RuntimeError("Synthetic benchmark gallery vector was zero.")
    return tuple(value / norm for value in values)


def _make_gallery(
    pipeline: Any,
    image: Any,
    *,
    gallery_size: int,
    seed: int,
    model_version: str,
) -> tuple[GalleryEntry, ...]:
    processed = pipeline.preprocessor.preprocess(image)
    detections = pipeline.detector.detect(processed)
    if len(detections) != 1:
        raise ValueError("The supplied benchmark image must contain exactly one face.")
    quality = pipeline.quality_assessor.assess(processed, detections[0])
    if not quality.acceptable:
        raise ValueError(
            "The supplied benchmark face does not pass configured quality gates."
        )
    aligned = pipeline.aligner.align(processed, detections[0])
    probe = pipeline.embedder.embed(aligned)
    target_id = uuid5(NAMESPACE_URL, f"presensi-benchmark-target:{seed}")
    gallery = [GalleryEntry(student_id=target_id, embedding=probe)]
    for index in range(1, gallery_size):
        student_id = uuid5(NAMESPACE_URL, f"presensi-benchmark:{seed}:{index}")
        distractor = FaceEmbedding(
            values=_normalized_random_vector(len(probe.values), seed + index),
            model_name=probe.model_name,
            model_version=model_version,
            normalized=True,
        )
        gallery.append(GalleryEntry(student_id=student_id, embedding=distractor))
    pipeline.max_candidates = max(2, gallery_size)
    return tuple(gallery)


class EdgeWorker:
    def __init__(
        self,
        config_path: Path,
        image: Any,
        *,
        gallery_size: int,
        seed: int,
    ) -> None:
        self.config = load_config(config_path)
        if self.config.mode != "AI_EDGE":
            raise ValueError("The supplied edge config must use mode: AI_EDGE.")
        self.pipeline = build_pipeline(self.config)
        yunet_path = self.config.models.yunet_path
        sface_path = self.config.models.sface_path
        if yunet_path is None or sface_path is None:
            raise FileNotFoundError("YuNet and SFace model paths are required.")
        self.yunet_sha256 = _sha256(yunet_path)
        self.sface_sha256 = _sha256(sface_path)
        self.model_version = self.config.models.version or "unspecified"
        self.gallery = _make_gallery(
            self.pipeline,
            image,
            gallery_size=gallery_size,
            seed=seed,
            model_version=self.model_version,
        )
        self.image = image
        self._run_lock = threading.Lock()

    def warmup(self, frame_count: int, max_bursts: int) -> None:
        self.run("warmup", 0, 0, frame_count, max_bursts)

    def run(
        self,
        scenario: str,
        request_number: int,
        lab_number: int,
        frame_count: int,
        max_bursts: int,
    ) -> RequestSample:
        with self._run_lock:
            return self._run_unlocked(
                scenario, request_number, lab_number, frame_count, max_bursts
            )

    def _run_unlocked(
        self,
        scenario: str,
        request_number: int,
        lab_number: int,
        frame_count: int,
        max_bursts: int,
    ) -> RequestSample:
        track_id = f"benchmark-{scenario}-lab-{lab_number}-{request_number}"
        timestamp = datetime.now(UTC)
        stage_timings: dict[str, float] = defaultdict(float)
        started = time.perf_counter()
        burst_count = 0
        try:
            decision = None
            frames_seen = 0
            for _ in range(max_bursts):
                burst_count += 1
                for _ in range(frame_count):
                    observation = FrameObservation(
                        track_id=track_id,
                        captured_at=timestamp
                        + timedelta(milliseconds=50 * frames_seen),
                    )
                    decision = self.pipeline.process(
                        self.image,
                        self.gallery,
                        observation,
                        timing_observer=lambda stage, duration: (
                            stage_timings.__setitem__(
                                stage, stage_timings[stage] + duration
                            )
                        ),
                    )
                    frames_seen += 1
                if decision is not None and decision.status != "COLLECTING":
                    break
            if decision is None:
                raise RuntimeError("A benchmark burst contained no frames.")
            terminal = decision.status != "COLLECTING"
            return RequestSample(
                profile="AI_EDGE",
                scenario=scenario,
                request_number=request_number,
                lab_number=lab_number,
                success=terminal,
                latency_ms=round((time.perf_counter() - started) * 1000, 3),
                decision_status=decision.status,
                decision_terminal=terminal,
                attempt_count=burst_count,
                retry_count=0,
                burst_count=burst_count,
                gallery_size=len(self.gallery),
                model_version=self.model_version,
                stage_latency_ms=dict(stage_timings),
            )
        except Exception as exc:
            return RequestSample(
                profile="AI_EDGE",
                scenario=scenario,
                request_number=request_number,
                lab_number=lab_number,
                success=False,
                latency_ms=round((time.perf_counter() - started) * 1000, 3),
                decision_status=None,
                decision_terminal=False,
                attempt_count=burst_count,
                retry_count=0,
                burst_count=burst_count,
                gallery_size=None,
                model_version=None,
                error_code=type(exc).__name__,
                stage_latency_ms=dict(stage_timings),
            )


class HttpByteCounter:
    """Count HTTP/1.1 header and body bytes at the application layer."""

    def __init__(self) -> None:
        self.request_bytes = 0
        self.response_bytes = 0

    def on_request(self, request: httpx.Request) -> None:
        request_target = request.url.raw_path.decode("ascii", errors="replace")
        request_line = f"{request.method} {request_target} HTTP/1.1\r\n".encode()
        header_bytes = sum(
            len(name) + len(value) + 4 for name, value in request.headers.raw
        )
        self.request_bytes += (
            len(request_line) + header_bytes + 2 + len(request.content)
        )

    def on_response(self, response: httpx.Response) -> None:
        status_line = (
            f"HTTP/1.1 {response.status_code} {response.reason_phrase}\r\n".encode()
        )
        header_bytes = sum(
            len(name) + len(value) + 4 for name, value in response.headers.raw
        )
        self.response_bytes += (
            len(status_line) + header_bytes + 2 + len(response.content)
        )


@dataclass(frozen=True, slots=True)
class CentralLab:
    device_id: str
    session_id: str
    token: str = field(repr=False)
    lab_number: int = 1


class CentralWorker:
    def __init__(
        self,
        base_url: str,
        lab: CentralLab,
        image_bytes: bytes,
        content_type: str,
        *,
        timeout_seconds: float,
        retry_attempts: int,
        retry_backoff_ms: int,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.lab = lab
        self.image_bytes = image_bytes
        self.content_type = content_type
        self.retry_attempts = retry_attempts
        self.retry_backoff_ms = retry_backoff_ms
        self.byte_counter = HttpByteCounter()
        self._run_lock = threading.Lock()
        self.client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
            event_hooks={
                "request": [self.byte_counter.on_request],
                "response": [self.byte_counter.on_response],
            },
        )

    def close(self) -> None:
        self.client.close()

    def warmup(self, frame_count: int, max_bursts: int) -> None:
        self.run("warmup", 0, frame_count, max_bursts)

    def run(
        self,
        scenario: str,
        request_number: int,
        frame_count: int,
        max_bursts: int = 5,
    ) -> RequestSample:
        with self._run_lock:
            return self._run_unlocked(scenario, request_number, frame_count, max_bursts)

    def _run_unlocked(
        self,
        scenario: str,
        request_number: int,
        frame_count: int,
        max_bursts: int = 5,
    ) -> RequestSample:
        track_id = f"benchmark-{scenario}-lab-{self.lab.lab_number}-{request_number}"
        captured_at = datetime.now(UTC)
        url = (
            f"{self.base_url}/api/v1/recognition/sessions/{self.lab.session_id}/bursts"
        )
        headers = {
            "X-Device-ID": self.lab.device_id,
            "Authorization": f"Bearer {self.lab.token}",
            "X-Benchmark-Timing": "true",
        }
        sent_before = self.byte_counter.request_bytes
        received_before = self.byte_counter.response_bytes
        started = time.perf_counter()
        retry_count = 0
        attempt_count = 0
        burst_count = 0
        last_error: str | None = None
        decision_status: str | None = None
        gallery_size: int | None = None
        model_version: str | None = None
        stage_timings: dict[str, float] = defaultdict(float)
        terminal = False
        frames_sent = 0
        for burst_index in range(max_bursts):
            burst_count += 1
            body = {
                "track_id": track_id,
                "frames": [
                    {
                        "captured_at": (
                            captured_at
                            + timedelta(milliseconds=50 * (frames_sent + index))
                        ).isoformat(),
                        "content_type": self.content_type,
                        "image_base64": base64.b64encode(self.image_bytes).decode(
                            "ascii"
                        ),
                    }
                    for index in range(frame_count)
                ],
            }
            frames_sent += frame_count
            burst_succeeded = False
            for attempt in range(self.retry_attempts + 1):
                attempt_count += 1
                try:
                    response = self.client.post(url, headers=headers, json=body)
                    if response.status_code < 400:
                        payload = response.json()
                        if not isinstance(payload, dict) or not isinstance(
                            payload.get("status"), str
                        ):
                            raise ValueError("Invalid decision response.")
                        status_value = payload["status"]
                        if status_value not in {
                            "COLLECTING",
                            "ACCEPTED",
                            "NEED_FRONTAL_RETRY",
                            "REJECTED",
                        }:
                            raise ValueError("Unknown decision status.")
                        decision_status = status_value
                        raw_model_version = payload.get("model_version")
                        if isinstance(raw_model_version, str):
                            model_version = raw_model_version
                        raw_gallery_size = response.headers.get(
                            "X-Recognition-Gallery-Template-Count"
                        )
                        if raw_gallery_size is not None:
                            try:
                                gallery_size = max(0, int(raw_gallery_size))
                            except ValueError:
                                gallery_size = None
                        raw_stages = response.headers.get(
                            "X-Recognition-Stage-Timings-Ms"
                        )
                        if raw_stages:
                            try:
                                parsed_stages = json.loads(raw_stages)
                            except ValueError:
                                parsed_stages = None
                            if isinstance(parsed_stages, dict):
                                for name, value in parsed_stages.items():
                                    if (
                                        isinstance(value, (float, int))
                                        and not isinstance(value, bool)
                                        and math.isfinite(float(value))
                                        and float(value) >= 0
                                    ):
                                        stage_timings[str(name)] += float(value)
                        burst_succeeded = True
                        last_error = None
                        break
                    last_error = _error_code(response)
                    retryable = (
                        response.status_code
                        in {
                            408,
                            425,
                            429,
                            502,
                            503,
                            504,
                        }
                        or response.status_code >= 500
                    )
                    if not retryable:
                        break
                except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
                    last_error = (
                        type(exc).__name__
                        if isinstance(exc, httpx.HTTPError)
                        else "invalid_response"
                    )
                    break
                if attempt + 1 < self.retry_attempts + 1:
                    retry_count += 1
                    time.sleep(self.retry_backoff_ms * (2**attempt) / 1000)
            if not burst_succeeded:
                break
            if decision_status != "COLLECTING":
                terminal = True
                break
        return RequestSample(
            profile="AI_CENTRAL",
            scenario=scenario,
            request_number=request_number,
            lab_number=self.lab.lab_number,
            success=terminal,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
            decision_status=decision_status,
            decision_terminal=terminal,
            attempt_count=attempt_count,
            retry_count=retry_count,
            burst_count=burst_count,
            gallery_size=gallery_size,
            model_version=model_version,
            request_bytes=self.byte_counter.request_bytes - sent_before,
            response_bytes=self.byte_counter.response_bytes - received_before,
            stage_latency_ms=stage_timings,
            error_code=last_error,
        )


def _error_code(response: httpx.Response) -> str:
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict) and isinstance(error.get("code"), str):
            return str(error["code"])[:80]
    except ValueError:
        pass
    return f"http_{response.status_code}"


def _pending(reason: str) -> dict[str, Any]:
    return {
        "status": STATUS_PENDING,
        "reason": reason,
        "request_count": 0,
        "terminal_decisions": None,
        "incomplete_decisions": None,
        "error_count": None,
        "retry_count": None,
        "retry_rate": None,
        "incomplete_rate": None,
        "error_rate": None,
        "duration_seconds": None,
        "throughput_decisions_per_second": None,
        "decision_latency_p50_ms": None,
        "decision_latency_p95_ms": None,
        "response_latency_p50_ms": None,
        "response_latency_p95_ms": None,
        "decision_status_counts": {},
        "inference_stage_latency_ms": {},
        "model_versions": [],
        "edge": {},
        "server": {},
        "network_application_bytes_per_event": None,
        "request_samples": [],
        "gallery_sizes": [],
    }


def _summarize_scenario(
    samples: list[RequestSample],
    *,
    elapsed_seconds: float,
    edge_stats: LocalResourceStats | None,
    server_stats: ServerResourceStats | None,
) -> dict[str, Any]:
    count = len(samples)
    successful = [sample for sample in samples if sample.success]
    errors = sum(sample.error_code is not None for sample in samples)
    incomplete = count - len(successful) - errors
    retry_count = sum(sample.retry_count for sample in samples)
    latencies = [
        sample.latency_ms for sample in successful if sample.latency_ms is not None
    ]
    response_latencies = [
        sample.latency_ms for sample in samples if sample.latency_ms is not None
    ]
    decision_status_counts = dict(
        sorted(
            Counter(
                sample.decision_status
                for sample in samples
                if sample.decision_status is not None
            ).items()
        )
    )
    stage_samples: dict[str, list[float]] = defaultdict(list)
    for sample in samples:
        for stage, duration in sample.stage_latency_ms.items():
            stage_samples[stage].append(duration)
    bytes_total = sum(
        (sample.request_bytes or 0) + (sample.response_bytes or 0) for sample in samples
    )
    byte_samples = [
        sample
        for sample in samples
        if sample.request_bytes is not None and sample.response_bytes is not None
    ]
    gallery_sizes = sorted(
        {sample.gallery_size for sample in samples if sample.gallery_size is not None}
    )
    return {
        "status": "COMPLETED"
        if count > 0 and errors == 0 and incomplete == 0
        else "COMPLETED WITH ERRORS"
        if errors and successful
        else "FAILED"
        if errors
        else "INCOMPLETE TRACKS",
        "reason": None
        if successful and incomplete == 0
        else "Some tracks remained COLLECTING at the burst limit."
        if incomplete and successful
        else "All tracks remained COLLECTING at the burst limit."
        if incomplete
        else "All measured requests failed.",
        "request_count": count,
        "terminal_decisions": len(successful),
        "incomplete_decisions": incomplete,
        "error_count": errors,
        "retry_count": retry_count,
        "retry_rate": round(sum(s.retry_count > 0 for s in samples) / count, 6)
        if count
        else None,
        "incomplete_rate": round(incomplete / count, 6) if count else None,
        "error_rate": round(errors / count, 6) if count else None,
        "duration_seconds": round(elapsed_seconds, 6),
        "throughput_decisions_per_second": round(len(successful) / elapsed_seconds, 6)
        if elapsed_seconds > 0
        else None,
        "decision_latency_p50_ms": _percentile(latencies, 0.50),
        "decision_latency_p95_ms": _percentile(latencies, 0.95),
        "response_latency_p50_ms": _percentile(response_latencies, 0.50),
        "response_latency_p95_ms": _percentile(response_latencies, 0.95),
        "decision_status_counts": decision_status_counts,
        "gallery_sizes": gallery_sizes,
        "model_versions": sorted(
            {sample.model_version for sample in samples if sample.model_version}
        ),
        "inference_stage_latency_ms": {
            stage: {
                "sample_count": len(values),
                "p50_ms": _percentile(values, 0.50),
                "p95_ms": _percentile(values, 0.95),
            }
            for stage, values in sorted(stage_samples.items())
        },
        "edge": asdict(edge_stats) if edge_stats is not None else {},
        "server": asdict(server_stats) if server_stats is not None else {},
        "network_application_bytes_per_event": round(bytes_total / len(byte_samples), 3)
        if byte_samples
        else None,
        "request_samples": [asdict(sample) for sample in samples],
    }


SUMMARY_FIELDS = [
    "profile",
    "scenario",
    "status",
    "reason",
    "request_count",
    "terminal_decisions",
    "incomplete_decisions",
    "error_count",
    "error_rate",
    "retry_count",
    "retry_rate",
    "incomplete_rate",
    "duration_seconds",
    "throughput_decisions_per_second",
    "decision_latency_p50_ms",
    "decision_latency_p95_ms",
    "response_latency_p50_ms",
    "response_latency_p95_ms",
    "decision_status_counts",
    "gallery_sizes",
    "model_versions",
    "network_application_bytes_per_event",
    "edge_process_cpu_percent_mean",
    "edge_process_rss_bytes_peak",
    "edge_host_cpu_percent_mean",
    "edge_host_memory_used_bytes_mean",
    "edge_host_memory_total_bytes",
    "server_process_cpu_percent_mean",
    "server_process_rss_bytes_peak",
    "server_host_cpu_percent_mean",
    "server_host_memory_used_bytes_mean",
    "server_host_memory_total_bytes",
    *[f"stage_{stage}_{stat}_ms" for stage in STAGES for stat in ("p50", "p95")],
]


def _flatten_summary(
    profile: str, scenario: str, result: dict[str, Any]
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "profile": profile,
        "scenario": scenario,
        **{
            field: result.get(field)
            for field in SUMMARY_FIELDS
            if field not in {"profile", "scenario"}
        },
    }
    row["decision_status_counts"] = json.dumps(
        row["decision_status_counts"], sort_keys=True, separators=(",", ":")
    )
    row["gallery_sizes"] = json.dumps(row["gallery_sizes"], separators=(",", ":"))
    row["model_versions"] = json.dumps(row["model_versions"], separators=(",", ":"))
    for resource_name in ("edge", "server"):
        resource = result.get(resource_name, {})
        for key, value in resource.items():
            row[f"{resource_name}_{key}"] = value
    for stage in STAGES:
        stage_result = result.get("inference_stage_latency_ms", {}).get(stage, {})
        row[f"stage_{stage}_p50_ms"] = stage_result.get("p50_ms")
        row[f"stage_{stage}_p95_ms"] = stage_result.get("p95_ms")
    return row


def _write_outputs(output_dir: Path, report: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    csv_rows = [
        _flatten_summary(profile, scenario, result)
        for profile, profile_result in report["profiles"].items()
        for scenario, result in profile_result["scenarios"].items()
    ]
    with (output_dir / "summary.csv").open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(
            target, fieldnames=SUMMARY_FIELDS, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(csv_rows)
    samples = [
        sample
        for profile_result in report["profiles"].values()
        for scenario_result in profile_result["scenarios"].values()
        for sample in scenario_result.get("request_samples", [])
    ]
    sample_fields = [
        "profile",
        "scenario",
        "request_number",
        "lab_number",
        "success",
        "latency_ms",
        "decision_status",
        "decision_terminal",
        "attempt_count",
        "retry_count",
        "burst_count",
        "gallery_size",
        "model_version",
        "request_bytes",
        "response_bytes",
        "error_code",
        "stage_latency_ms",
    ]
    with (output_dir / "samples.csv").open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=sample_fields)
        writer.writeheader()
        for sample in samples:
            writer.writerow(
                {
                    **sample,
                    "stage_latency_ms": json.dumps(
                        sample["stage_latency_ms"],
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                }
            )
    (output_dir / "summary.md").write_text(_markdown_summary(report), encoding="utf-8")


def _display(value: Any, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value}{suffix}"


def _markdown_summary(report: dict[str, Any]) -> str:
    lines = [
        "# AI_EDGE vs AI_CENTRAL deployment benchmark",
        "",
        f"- Run: `{report['metadata']['run_id']}`",
        f"- Started: `{report['metadata']['started_at_utc']}`",
        f"- Overall status: **{report['overall_status']}**",
        "- Workload source: locally supplied image; path and image data are not written to the report.",  # noqa: E501
        "- No performance values are synthesized. Missing measurements remain blank/null.",  # noqa: E501
        "",
        "## Results",
        "",
        "| Profile | Scenario | Status | Gallery size(s) | Decisions/s | Decision p50 ms | Decision p95 ms | Retries | Errors | Incomplete | Edge host CPU % | Edge host RAM MB | Server host CPU % | Server host RAM MB | App bytes/event |",  # noqa: E501
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for profile, profile_result in report["profiles"].items():
        for scenario, result in profile_result["scenarios"].items():
            edge = result.get("edge", {})
            server = result.get("server", {})
            lines.append(
                "| {profile} | {scenario} | {status} | {gallery_sizes} | {throughput} | {p50} | {p95} | {retries} | {errors} | {incomplete} | {edge_cpu} | {edge_ram} | {server_cpu} | {server_ram} | {bytes_per_event} |".format(  # noqa: E501
                    profile=profile,
                    scenario=scenario,
                    status=result["status"],
                    gallery_sizes=_display(
                        ",".join(
                            str(value) for value in result.get("gallery_sizes", [])
                        )
                        or None
                    ),
                    throughput=_display(result.get("throughput_decisions_per_second")),
                    p50=_display(result.get("decision_latency_p50_ms")),
                    p95=_display(result.get("decision_latency_p95_ms")),
                    retries=_display(result.get("retry_count")),
                    errors=_display(result.get("error_count")),
                    incomplete=_display(result.get("incomplete_decisions")),
                    edge_cpu=_display(edge.get("host_cpu_percent_mean")),
                    edge_ram=_display(
                        round(edge["host_memory_used_bytes_mean"] / 1_000_000, 2)
                        if edge.get("host_memory_used_bytes_mean") is not None
                        else None
                    ),
                    server_cpu=_display(server.get("host_cpu_percent_mean")),
                    server_ram=_display(
                        round(server["host_memory_used_bytes_mean"] / 1_000_000, 2)
                        if server.get("host_memory_used_bytes_mean") is not None
                        else None
                    ),
                    bytes_per_event=_display(
                        result.get("network_application_bytes_per_event")
                    ),
                )
            )
    lines.extend(["", "## Decision states", ""])
    lines.append("Terminal decision latency excludes tracks that remained COLLECTING.")
    lines.append("")
    lines.append("| Profile | Scenario | Final track states |")
    lines.append("|---|---|---|")
    for profile, profile_result in report["profiles"].items():
        for scenario, result in profile_result["scenarios"].items():
            states = result.get("decision_status_counts", {})
            display_states = json.dumps(states, sort_keys=True) if states else "—"
            lines.append(f"| {profile} | {scenario} | `{display_states}` |")
    lines.extend(["", "## Inference stages", ""])
    lines.append("Per-decision stage time is summed across frames and bursts.")
    lines.append("")
    lines.append("| Profile | Scenario | Stage | Samples | p50 ms | p95 ms |")
    lines.append("|---|---|---|---:|---:|---:|")
    for profile, profile_result in report["profiles"].items():
        for scenario, result in profile_result["scenarios"].items():
            for stage, metric in result.get("inference_stage_latency_ms", {}).items():
                lines.append(
                    f"| {profile} | {scenario} | {stage} | {metric['sample_count']} | {metric['p50_ms']} | {metric['p95_ms']} |"  # noqa: E501
                )
    lines.extend(["", "## Method and limits", ""])
    lines.extend(f"- {item}" for item in report["methodology"])
    if report.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in report["warnings"])
    lines.extend(["", "## Blockers", ""])
    blockers = [
        f"- **{profile} / {scenario}:** {result['reason']}"
        for profile, profile_result in report["profiles"].items()
        for scenario, result in profile_result["scenarios"].items()
        if result["status"] == STATUS_PENDING and result.get("reason")
    ]
    lines.extend(blockers or ["- None recorded."])
    return "\n".join(lines) + "\n"


def _scenario_samples(
    workers: list[Any],
    profile: str,
    scenario: str,
    *,
    iterations: int,
    frame_count: int,
    max_bursts: int,
    concurrency: int,
) -> tuple[list[RequestSample], float, LocalResourceStats, ServerResourceStats | None]:
    samples: list[RequestSample] = []
    started = time.perf_counter()
    with LocalResourceMonitor() as local_monitor:
        if concurrency == 1:
            worker = workers[0]
            for index in range(iterations):
                samples.append(
                    worker.run(scenario, index + 1, 1, frame_count, max_bursts)
                    if profile == "AI_EDGE"
                    else worker.run(scenario, index + 1, frame_count, max_bursts)
                )
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = []
                for lab_number, worker in enumerate(workers[:concurrency], start=1):
                    for index in range(iterations):
                        if profile == "AI_EDGE":
                            futures.append(
                                executor.submit(
                                    worker.run,
                                    scenario,
                                    index + 1,
                                    lab_number,
                                    frame_count,
                                    max_bursts,
                                )
                            )
                        else:
                            futures.append(
                                executor.submit(
                                    worker.run,
                                    scenario,
                                    index + 1,
                                    frame_count,
                                    max_bursts,
                                )
                            )
                for future in as_completed(futures):
                    samples.append(future.result())
    elapsed = time.perf_counter() - started
    local_stats = local_monitor.result()
    return samples, elapsed, local_stats, None


def _record_profile(
    scenarios: dict[str, dict[str, Any]],
    profile: str,
    scenario: str,
    *,
    workers: list[Any],
    iterations: int,
    frame_count: int,
    max_bursts: int,
    concurrency: int,
    central_url: str | None = None,
) -> None:
    server_stats: ServerResourceStats | None
    if profile == "AI_CENTRAL" and central_url:
        monitor = ServerResourceMonitor(central_url)
        with monitor:
            samples, elapsed, edge_stats, _ = _scenario_samples(
                workers,
                profile,
                scenario,
                iterations=iterations,
                frame_count=frame_count,
                max_bursts=max_bursts,
                concurrency=concurrency,
            )
        server_stats = monitor.result()
    else:
        samples, elapsed, edge_stats, server_stats = _scenario_samples(
            workers,
            profile,
            scenario,
            iterations=iterations,
            frame_count=frame_count,
            max_bursts=max_bursts,
            concurrency=concurrency,
        )
    scenarios[scenario] = _summarize_scenario(
        samples,
        elapsed_seconds=elapsed,
        edge_stats=edge_stats,
        server_stats=server_stats,
    )


def _default_scenarios(reason: str) -> dict[str, dict[str, Any]]:
    return {scenario: _pending(reason) for scenario in SCENARIOS}


def _image_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    raise ValueError("Benchmark images must use JPEG, PNG, or WebP extension.")


def _git_revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image", type=Path, help="Local legal/non-sensitive benchmark face image."
    )
    parser.add_argument(
        "--edge-config",
        type=Path,
        help="AI_EDGE YAML config with local model paths and calibrated thresholds.",
    )
    parser.add_argument(
        "--central-url", help="Base URL of the running AI_CENTRAL service."
    )
    parser.add_argument("--device-id", help="AI_CENTRAL lab 1 device UUID.")
    parser.add_argument("--session-id", help="Active AI_CENTRAL lab 1 session UUID.")
    parser.add_argument(
        "--token-env",
        default="PRESENSI_BENCH_DEVICE_TOKEN",
        help="Environment variable holding lab 1 device token.",
    )
    parser.add_argument(
        "--lab2-device-id",
        help="AI_CENTRAL lab 2 device UUID; required for two-lab central load.",
    )
    parser.add_argument(
        "--lab2-session-id", help="Active AI_CENTRAL lab 2 session UUID."
    )
    parser.add_argument(
        "--lab2-token-env",
        default="PRESENSI_BENCH_LAB2_DEVICE_TOKEN",
        help="Environment variable holding lab 2 device token.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=30,
        help="Measured decisions per lab and scenario, excluding warmup.",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=3,
        help="Warmup decisions per lab; excluded from report metrics.",
    )
    parser.add_argument(
        "--frames-per-decision",
        type=int,
        default=3,
        help="Repeated frames per decision burst (1-5).",
    )
    parser.add_argument(
        "--max-bursts",
        type=int,
        default=5,
        help="Maximum sequential bursts allowed to reach a terminal decision.",
    )
    parser.add_argument(
        "--gallery-size",
        type=int,
        default=30,
        help="Synthetic gallery size for AI_EDGE only.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20261002,
        help="Seed for AI_EDGE synthetic distractor templates.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument(
        "--retry-attempts",
        type=int,
        default=2,
        help="Retries after the initial central HTTP attempt.",
    )
    parser.add_argument("--retry-backoff-ms", type=int, default=250)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "tests" / "deployment-benchmark" / "reports" / "latest",
    )
    return parser


def _methodology() -> list[str]:
    return [
        (
            "Latency starts at a decoded image and ends at a terminal AI_EDGE track "
            "decision or AI_CENTRAL response. It excludes camera capture and Core API "
            "attendance writes. COLLECTING tracks are reported as incomplete."
        ),
        (
            "Stage timings come from recognition-core and are summed across frames and "
            "bursts until a terminal decision. They measure pipeline work, "
            "not camera time."
        ),
        (
            "AI_EDGE uses the real local YuNet/SFace pipeline and a seeded synthetic "
            "gallery. One target template is derived from the supplied test image; "
            "remaining distractors are seeded normalized vectors. This workload is "
            "for performance only, not threshold calibration or demographic evaluation."
        ),
        (
            "AI_CENTRAL requests go to the configured service with active-session "
            "galleries. The two-lab scenario runs one serialized stream per device "
            "concurrently. HTTP byte estimates include HTTP/1.1 headers and bodies, "
            "and exclude TLS, TCP/IP, and link-layer framing."
        ),
        (
            "CPU reports process percent normalized to one core (may exceed 100%) and "
            "sampled host CPU percent. RAM reports peak process RSS and average host "
            "memory use. Central server values come from its /metrics endpoint."
        ),
        (
            "Sequential runs one lab at a time. Two-lab runs two workers concurrently. "
            "AI_EDGE workers share this benchmark host; repeat one worker on each "
            "real lab PC before making a deployment decision."
        ),
        (
            "Warmup is excluded. Decision latency percentiles use terminal track "
            "decisions; response latency covers all measured logical requests. "
            "Retry/error rates use all logical requests. Percentiles use nearest "
            "rank. This runner saves no camera or raw image, and omits image paths "
            "and credentials from reports."
        ),
    ]


def _make_central_labs(
    args: argparse.Namespace, blockers: dict[str, str]
) -> list[CentralLab]:
    labs: list[CentralLab] = []
    for number, (device_id, session_id, token_env) in enumerate(
        (
            (args.device_id, args.session_id, args.token_env),
            (args.lab2_device_id, args.lab2_session_id, args.lab2_token_env),
        ),
        start=1,
    ):
        if not all((device_id, session_id)):
            continue
        token = os.environ.get(token_env, "").strip()
        if not token:
            blockers["AI_CENTRAL"] = (
                f"Set {token_env} in the environment. "
                "The token value is never printed or saved."
            )
            continue
        try:
            UUID(device_id)
            UUID(session_id)
        except ValueError:
            blockers["AI_CENTRAL"] = "Device and session identifiers must be UUIDs."
            continue
        labs.append(CentralLab(device_id, session_id, token, number))
    return labs


def run(args: argparse.Namespace) -> dict[str, Any]:
    started_at = datetime.now(UTC)
    if args.iterations < 1 or args.warmup < 0:
        raise ValueError("Iterations must be positive and warmup cannot be negative.")
    if args.max_bursts < 1:
        raise ValueError("max-bursts must be positive.")
    if not 1 <= args.frames_per_decision <= 5:
        raise ValueError("frames-per-decision must be between 1 and 5.")
    if args.gallery_size < 2:
        raise ValueError("gallery-size must be at least 2.")
    if args.retry_attempts < 0 or args.retry_backoff_ms < 0:
        raise ValueError("Retry settings cannot be negative.")
    if args.timeout_seconds <= 0:
        raise ValueError("timeout-seconds must be positive.")

    blockers: dict[str, str] = {}
    image = _read_image(args.image)
    if image is None:
        blockers["AI_EDGE"] = (
            "Provide --image with a local approved fixture, --edge-config, and "
            "locally provisioned YuNet/SFace model files."
        )
        blockers["AI_CENTRAL"] = (
            "Provide --image, a running AI Central URL, active lab session/device "
            "IDs, and their device tokens."
        )
    edge_workers: list[EdgeWorker] = []
    if image is not None and args.edge_config is not None:
        try:
            edge_workers = [
                EdgeWorker(
                    args.edge_config,
                    image,
                    gallery_size=args.gallery_size,
                    seed=args.seed,
                )
                for _ in range(2)
            ]
        except (OSError, ValueError, EdgeConfigError, RuntimeError) as exc:
            blockers["AI_EDGE"] = f"Local model/config not ready: {type(exc).__name__}."
            edge_workers = []
    elif "AI_EDGE" not in blockers:
        blockers["AI_EDGE"] = (
            "Provide --edge-config with local models and calibrated thresholds."
        )

    central_labs = _make_central_labs(args, blockers)
    central_workers: list[CentralWorker] = []
    if args.central_url and image is not None and central_labs:
        try:
            _image_content_type(args.image)
            success, encoded = cv2.imencode(
                ".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 85]
            )
            if not success:
                raise ValueError("Could not encode benchmark image as JPEG.")
            frame_bytes = encoded.tobytes()
            central_workers = [
                CentralWorker(
                    args.central_url,
                    lab,
                    frame_bytes,
                    "image/jpeg",
                    timeout_seconds=args.timeout_seconds,
                    retry_attempts=args.retry_attempts,
                    retry_backoff_ms=args.retry_backoff_ms,
                )
                for lab in central_labs
            ]
        except (OSError, ValueError) as exc:
            blockers["AI_CENTRAL"] = (
                f"Central request workload could not be prepared: {type(exc).__name__}."
            )
            central_workers = []
    elif "AI_CENTRAL" not in blockers:
        blockers["AI_CENTRAL"] = (
            "Provide --central-url, lab 1 device/session IDs, and its token variable."
        )

    profiles: dict[str, Any] = {
        "AI_EDGE": {
            "scenarios": _default_scenarios(
                blockers.get("AI_EDGE", "AI_EDGE was not configured.")
            )
        },
        "AI_CENTRAL": {
            "scenarios": _default_scenarios(
                blockers.get("AI_CENTRAL", "AI_CENTRAL was not configured.")
            )
        },
    }
    warnings: list[str] = []
    if edge_workers:
        try:
            for worker in edge_workers:
                for _ in range(args.warmup):
                    worker.warmup(args.frames_per_decision, args.max_bursts)
            scenarios = profiles["AI_EDGE"]["scenarios"]
            _record_profile(
                scenarios,
                "AI_EDGE",
                "sequential",
                workers=edge_workers[:1],
                iterations=args.iterations,
                frame_count=args.frames_per_decision,
                max_bursts=args.max_bursts,
                concurrency=1,
            )
            _record_profile(
                scenarios,
                "AI_EDGE",
                "two_labs_concurrent",
                workers=edge_workers,
                iterations=args.iterations,
                frame_count=args.frames_per_decision,
                max_bursts=args.max_bursts,
                concurrency=2,
            )
            profiles["AI_EDGE"]["models"] = {
                "version": edge_workers[0].model_version,
                "yunet_sha256": edge_workers[0].yunet_sha256,
                "sface_sha256": edge_workers[0].sface_sha256,
            }
        except Exception as exc:
            blockers["AI_EDGE"] = f"Benchmark failed: {type(exc).__name__}."
            profiles["AI_EDGE"]["scenarios"] = _default_scenarios(blockers["AI_EDGE"])

    if central_workers:
        try:
            for central_worker in central_workers:
                for _ in range(args.warmup):
                    central_worker.warmup(args.frames_per_decision, args.max_bursts)
            scenarios = profiles["AI_CENTRAL"]["scenarios"]
            _record_profile(
                scenarios,
                "AI_CENTRAL",
                "sequential",
                workers=central_workers[:1],
                iterations=args.iterations,
                frame_count=args.frames_per_decision,
                max_bursts=args.max_bursts,
                concurrency=1,
                central_url=args.central_url,
            )
            if len(central_workers) >= 2:
                _record_profile(
                    scenarios,
                    "AI_CENTRAL",
                    "two_labs_concurrent",
                    workers=central_workers[:2],
                    iterations=args.iterations,
                    frame_count=args.frames_per_decision,
                    max_bursts=args.max_bursts,
                    concurrency=2,
                    central_url=args.central_url,
                )
            else:
                scenarios["two_labs_concurrent"] = _pending(
                    "Provide a second active device/session pair and token to measure "
                    "two central labs concurrently."
                )
            profiles["AI_CENTRAL"]["timing_enabled"] = any(
                scenario["inference_stage_latency_ms"]
                for scenario in scenarios.values()
            )
            if not any(
                scenario["inference_stage_latency_ms"]
                for scenario in scenarios.values()
            ):
                warnings.append(
                    "AI_CENTRAL stage timings were not returned. Set "
                    "PRESENSI_AI_BENCHMARK_TIMING_ENABLED=true on the service and "
                    "restart it for a benchmark run."
                )
            if not any(
                scenario.get("server", {}).get("process_cpu_percent_mean") is not None
                for scenario in scenarios.values()
            ):
                warnings.append(
                    "AI_CENTRAL process/host resource samples were not returned. "
                    "Verify that /metrics is reachable from the benchmark client."
                )
        except Exception as exc:
            blockers["AI_CENTRAL"] = f"Benchmark failed: {type(exc).__name__}."
            profiles["AI_CENTRAL"]["scenarios"] = _default_scenarios(
                blockers["AI_CENTRAL"]
            )
        finally:
            for central_worker in central_workers:
                central_worker.close()

    for profile_result in profiles.values():
        for scenario in profile_result["scenarios"].values():
            if scenario["status"] in {STATUS_PENDING, "FAILED"}:
                continue
            if scenario["error_count"]:
                scenario["status"] = "COMPLETED WITH ERRORS"

    pending_count = sum(
        scenario["status"] == STATUS_PENDING
        for profile_result in profiles.values()
        for scenario in profile_result["scenarios"].values()
    )
    failure_count = sum(
        scenario["status"] == "FAILED"
        for profile_result in profiles.values()
        for scenario in profile_result["scenarios"].values()
    )
    overall = (
        STATUS_PENDING
        if pending_count == 4
        else "PARTIAL / PENDING HARDWARE"
        if pending_count
        else "FAILED"
        if failure_count == 4
        else "COMPLETED WITH ERRORS"
        if failure_count
        or any(
            scenario["status"] == "COMPLETED WITH ERRORS"
            for result in profiles.values()
            for scenario in result["scenarios"].values()
        )
        else "INCOMPLETE TRACKS"
        if any(
            scenario["status"] == "INCOMPLETE TRACKS"
            for result in profiles.values()
            for scenario in result["scenarios"].values()
        )
        else "COMPLETED"
    )
    finished_at = datetime.now(UTC)
    host_memory = psutil.virtual_memory()
    report = {
        "overall_status": overall,
        "metadata": {
            "schema_version": 1,
            "run_id": started_at.strftime("%Y%m%dT%H%M%SZ"),
            "started_at_utc": started_at.isoformat(),
            "finished_at_utc": finished_at.isoformat(),
            "git_revision": _git_revision(),
            "host": {
                "os": platform.platform(),
                "machine": platform.machine(),
                "processor": platform.processor() or None,
                "logical_cpu_count": psutil.cpu_count(logical=True),
                "physical_cpu_count": psutil.cpu_count(logical=False),
                "memory_total_bytes": host_memory.total,
                "python": platform.python_version(),
                "libraries": {
                    "numpy": np.__version__,
                    "opencv": cv2.__version__,
                    "httpx": httpx.__version__,
                    "psutil": psutil.__version__,
                    "opencv_distribution": _distribution_version(
                        "opencv-python-headless"
                    )
                    or _distribution_version("opencv-python"),
                },
            },
            "configuration": {
                "iterations_per_lab_scenario": args.iterations,
                "warmup_per_lab": args.warmup,
                "frames_per_decision": args.frames_per_decision,
                "max_bursts_per_decision": args.max_bursts,
                "edge_synthetic_gallery_size": args.gallery_size,
                "synthetic_gallery_seed": args.seed,
                "retry_attempts": args.retry_attempts,
                "retry_backoff_ms": args.retry_backoff_ms,
                "image_path_recorded": False,
                "device_tokens_recorded": False,
                "fixture_image_saved_or_hashed": False,
            },
        },
        "profiles": profiles,
        "methodology": _methodology(),
        "warnings": warnings,
    }
    return report


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = run(args)
        _write_outputs(args.output_dir, report)
    except (OSError, ValueError) as exc:
        print(f"benchmark error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": report["overall_status"],
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
