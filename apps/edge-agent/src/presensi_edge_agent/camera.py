from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from presensi_edge_agent.config import CameraSettings


class CameraUnavailableError(RuntimeError):
    """Raised when the configured camera cannot be opened or read."""


def _cv2() -> Any:
    try:
        return importlib.import_module("cv2")
    except ImportError as exc:
        raise CameraUnavailableError(
            "Camera support is optional. Install the edge extra: "
            'python -m pip install -e "apps/edge-agent[camera]".'
        ) from exc


def _backend(cv2: Any, backend: str) -> int | None:
    backends = {
        "dshow": "CAP_DSHOW",
        "msmf": "CAP_MSMF",
        "v4l2": "CAP_V4L2",
    }
    if backend == "auto":
        return None
    attribute = backends[backend]
    return int(getattr(cv2, attribute))


def _video_capture(cv2: Any, index: int, backend: str) -> Any:
    selected_backend = _backend(cv2, backend)
    if selected_backend is None:
        return cv2.VideoCapture(index)
    return cv2.VideoCapture(index, selected_backend)


@dataclass(frozen=True, slots=True)
class CameraInfo:
    index: int
    opened: bool


def enumerate_cameras(
    max_index: int,
    *,
    backend: str = "auto",
    capture_factory: Callable[[int, str], Any] | None = None,
) -> tuple[CameraInfo, ...]:
    if max_index < 0:
        raise ValueError("max_index must not be negative.")
    cameras: list[CameraInfo] = []
    for index in range(max_index + 1):
        capture: Any | None = None
        try:
            if capture_factory is None:
                cv2 = _cv2()
                capture = _video_capture(cv2, index, backend)
            else:
                capture = capture_factory(index, backend)
            if capture is not None and capture.isOpened():
                cameras.append(CameraInfo(index=index, opened=True))
        except (OSError, RuntimeError):
            continue
        finally:
            if capture is not None:
                capture.release()
    return tuple(cameras)


class OpenCVCamera:
    def __init__(
        self,
        settings: CameraSettings,
        *,
        max_frame_size: tuple[int, int] | None = None,
    ) -> None:
        self.settings = settings
        self.max_frame_size = max_frame_size
        self._cv2 = _cv2()
        self._capture: Any | None = None

    def open(self) -> None:
        self.close()
        capture = _video_capture(self._cv2, self.settings.index, self.settings.backend)
        if not capture.isOpened():
            capture.release()
            raise CameraUnavailableError(
                f"Unable to open configured camera index {self.settings.index}."
            )
        capture.set(self._cv2.CAP_PROP_FRAME_WIDTH, self.settings.width)
        capture.set(self._cv2.CAP_PROP_FRAME_HEIGHT, self.settings.height)
        capture.set(self._cv2.CAP_PROP_FPS, self.settings.fps)
        autofocus_property = getattr(self._cv2, "CAP_PROP_AUTOFOCUS", None)
        if autofocus_property is not None:
            # Best effort only; fixed-focus and unsupported cameras ignore this.
            capture.set(autofocus_property, 1)
        if hasattr(self._cv2, "CAP_PROP_BUFFERSIZE"):
            capture.set(self._cv2.CAP_PROP_BUFFERSIZE, 1)
        if self.max_frame_size is not None:
            actual_width = int(capture.get(self._cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(capture.get(self._cv2.CAP_PROP_FRAME_HEIGHT))
            max_width, max_height = self.max_frame_size
            if actual_width > max_width or actual_height > max_height:
                capture.release()
                raise CameraUnavailableError(
                    "Camera negotiated a capture mode above the configured limit."
                )
        self._capture = capture

    def read(self) -> tuple[bool, object | None]:
        if self._capture is None:
            raise CameraUnavailableError("Camera is not open.")
        ok, frame = self._capture.read()
        if ok and frame is not None and self.max_frame_size is not None:
            shape = getattr(frame, "shape", None)
            if shape is not None and len(shape) >= 2:
                max_width, max_height = self.max_frame_size
                if int(shape[1]) > max_width or int(shape[0]) > max_height:
                    raise CameraUnavailableError(
                        "Camera returned a frame above the configured size limit."
                    )
        return bool(ok), frame

    def reported_mode(self) -> dict[str, int | float] | None:
        """Return the camera driver's negotiated mode when the stream is open."""
        if self._capture is None:
            return None
        return {
            "width": int(self._capture.get(self._cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(self._capture.get(self._cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": round(float(self._capture.get(self._cv2.CAP_PROP_FPS)), 1),
        }

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
