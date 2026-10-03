"""Ephemeral camera health measurements safe to expose as device telemetry."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from datetime import UTC, datetime
from typing import Literal, cast

CameraQualityState = Literal[
    "not_checked",
    "ready",
    "adjust",
    "no_face",
    "multiple_faces",
    "unavailable",
]
CameraQualitySource = Literal["face_check", "frame_filter"]


class CameraRuntimeMetrics:
    """Measure capture FPS and report coarse camera quality without image data."""

    _fps_window_seconds = 5.0

    def __init__(self, requested_fps: int) -> None:
        self.requested_fps = requested_fps
        self._lock = threading.Lock()
        self._frame_times: deque[float] = deque()
        self._frame_width: int | None = None
        self._frame_height: int | None = None
        self._driver_fps: float | None = None
        self._quality_state: CameraQualityState = "not_checked"
        self._quality_source: CameraQualitySource | None = None
        self._quality_checked_at: str | None = None

    def set_driver_mode(self, mode: dict[str, int | float] | None) -> None:
        if mode is None:
            return
        width = mode.get("width")
        height = mode.get("height")
        fps = mode.get("fps")
        with self._lock:
            if type(width) is int and 1 <= width <= 8192:
                self._frame_width = width
            if type(height) is int and 1 <= height <= 8192:
                self._frame_height = height
            if isinstance(fps, (int, float)) and math.isfinite(fps) and 0 < fps <= 240:
                self._driver_fps = float(fps)

    def record_frame(self, frame: object) -> None:
        now = time.monotonic()
        shape = getattr(frame, "shape", None)
        width = int(shape[1]) if shape is not None and len(shape) >= 2 else None
        height = int(shape[0]) if shape is not None and len(shape) >= 2 else None
        with self._lock:
            self._frame_times.append(now)
            cutoff = now - self._fps_window_seconds
            while self._frame_times and self._frame_times[0] < cutoff:
                self._frame_times.popleft()
            if width is not None and 1 <= width <= 8192:
                self._frame_width = width
            if height is not None and 1 <= height <= 8192:
                self._frame_height = height

    def set_quality_state(
        self,
        state: str,
        *,
        source: CameraQualitySource | None = None,
    ) -> None:
        allowed = {
            "not_checked",
            "ready",
            "adjust",
            "no_face",
            "multiple_faces",
            "unavailable",
        }
        safe_state = cast(
            CameraQualityState, state if state in allowed else "unavailable"
        )
        with self._lock:
            self._quality_state = safe_state
            self._quality_source = source if safe_state != "not_checked" else None
            self._quality_checked_at = datetime.now(UTC).isoformat()

    def snapshot(self) -> dict[str, object]:
        now = time.monotonic()
        with self._lock:
            while (
                self._frame_times
                and self._frame_times[0] < now - self._fps_window_seconds
            ):
                self._frame_times.popleft()
            capture_fps: float | None = None
            if (
                len(self._frame_times) >= 2
                and now - self._frame_times[-1] <= 3.0
                and self._frame_times[-1] > self._frame_times[0]
            ):
                capture_fps = (len(self._frame_times) - 1) / (
                    self._frame_times[-1] - self._frame_times[0]
                )
            return {
                "frame_width": self._frame_width,
                "frame_height": self._frame_height,
                "capture_fps": (
                    round(capture_fps, 1) if capture_fps is not None else None
                ),
                "requested_fps": float(self.requested_fps),
                "driver_fps": self._driver_fps,
                "quality_state": self._quality_state,
                "quality_source": self._quality_source,
                "quality_checked_at": self._quality_checked_at,
                "measured_at": datetime.now(UTC).isoformat(),
            }


__all__ = ["CameraRuntimeMetrics", "CameraQualitySource", "CameraQualityState"]
