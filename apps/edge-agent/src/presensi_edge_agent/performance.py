from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque

from presensi_edge_agent.logging import log_event

logger = logging.getLogger("presensi_edge_agent")

_LATENCY_NAMES = (
    "camera_read_ms",
    "preview_encode_ms",
    "camera_diagnostics_ms",
    "pipeline_total_ms",
    "temporal_sampling_ms",
    "preprocess_ms",
    "detect_ms",
    "quality_ms",
    "align_ms",
    "liveness_ms",
    "embed_ms",
    "match_ms",
    "temporal_decision_ms",
    "event_delivery_ms",
)
_COUNT_NAMES = (
    "camera_frames",
    "preview_frames",
    "event_delivered",
    "event_failed",
)


class EdgePerformanceMonitor:
    """Opt-in, privacy-safe rolling timing summary for local development."""

    def __init__(self, *, window_seconds: float = 10.0) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive.")
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._window_started = time.monotonic()
        self._latencies: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=512)
        )
        self._counts = {name: 0 for name in _COUNT_NAMES}

    @classmethod
    def from_environment(cls) -> EdgePerformanceMonitor | None:
        enabled = os.getenv("PRESENSI_EDGE_PERFORMANCE_LOGS", "").strip().lower()
        if enabled not in {"1", "true", "yes", "on"}:
            return None
        return cls()

    def observe(self, name: str, milliseconds: float) -> None:
        metric_name = name if name.endswith("_ms") else f"{name}_ms"
        if metric_name not in _LATENCY_NAMES or milliseconds < 0:
            return
        with self._lock:
            self._latencies[metric_name].append(milliseconds)

    def increment(self, name: str) -> None:
        if name not in self._counts:
            return
        with self._lock:
            self._counts[name] += 1

    def maybe_log(self) -> None:
        now = time.monotonic()
        with self._lock:
            elapsed = now - self._window_started
            if elapsed < self.window_seconds:
                return
            fields: dict[str, float | int] = {
                "window_seconds": round(elapsed, 1),
                "camera_read_fps": round(self._counts["camera_frames"] / elapsed, 1),
                "preview_fps": round(self._counts["preview_frames"] / elapsed, 1),
                "event_delivered": self._counts["event_delivered"],
                "event_failed": self._counts["event_failed"],
            }
            for name, samples in self._latencies.items():
                if not samples:
                    continue
                ordered = sorted(samples)
                fields[f"{name}_n"] = len(samples)
                fields[f"{name}_p50"] = round(_percentile(ordered, 0.50), 1)
                fields[f"{name}_p95"] = round(_percentile(ordered, 0.95), 1)
            self._latencies.clear()
            self._counts = {name: 0 for name in _COUNT_NAMES}
            self._window_started = now
        log_event(logger, logging.INFO, "edge_performance_window", **fields)


def _percentile(ordered_values: list[float], fraction: float) -> float:
    index = round((len(ordered_values) - 1) * fraction)
    return ordered_values[index]
