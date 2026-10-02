from __future__ import annotations

import importlib
import time
from pathlib import Path
from typing import Any, Callable, cast

import yaml

from presensi_edge_agent.camera import CameraUnavailableError, _video_capture
from presensi_edge_agent.config import EdgeConfig

_EDGE_RESOLUTIONS = ((640, 480), (1280, 720), (1920, 1080))
_STB_RESOLUTIONS = ((640, 360), (640, 480), (1280, 720))


def _read_choice(
    prompt: str,
    choices: list[str],
    *,
    default: str,
    input_fn: Callable[[str], str],
) -> str:
    while True:
        answer = input_fn(
            f"{prompt} [{'/'.join(choices)}] (default {default}): "
        ).strip()
        selected = answer or default
        if selected in choices:
            return selected
        print(f"Choose one of: {', '.join(choices)}")


def _probe_mode(
    index: int,
    backend: str,
    width: int,
    height: int,
    fps: int,
) -> tuple[int, int, float, float]:
    try:
        cv2: Any = importlib.import_module("cv2")
    except ImportError as exc:
        raise CameraUnavailableError(
            "Camera setup requires the camera extra: "
            'python -m pip install -e "apps/edge-agent[camera]".'
        ) from exc

    capture = _video_capture(cv2, index, backend)
    try:
        if not capture.isOpened():
            raise CameraUnavailableError(f"Camera index {index} could not be opened.")
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        capture.set(cv2.CAP_PROP_FPS, fps)
        if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        first_frame: object | None = None
        started = time.perf_counter()
        frame_count = 0
        deadline = started + 2.0
        while frame_count < 8 and time.perf_counter() < deadline:
            ok, frame = capture.read()
            if ok and frame is not None:
                first_frame = frame if first_frame is None else first_frame
                frame_count += 1
        elapsed = time.perf_counter() - started
        if first_frame is None:
            raise CameraUnavailableError(
                f"Camera index {index} opened but did not return a frame."
            )
        shape = cast(tuple[int, ...] | None, getattr(first_frame, "shape", None))
        if shape is None or len(shape) < 2:
            raise CameraUnavailableError("The camera returned an invalid frame.")
        actual_width = int(shape[1])
        actual_height = int(shape[0])
        reported_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        measured_fps = (
            (frame_count - 1) / elapsed if elapsed > 0 and frame_count > 1 else 0
        )
        return actual_width, actual_height, reported_fps, measured_fps
    finally:
        capture.release()


def _write_camera_config(
    config_path: Path,
    config: EdgeConfig,
    *,
    index: int,
    width: int,
    height: int,
    fps: int,
) -> None:
    try:
        values = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError("Could not read the generated device YAML.") from exc
    if not isinstance(values, dict) or not isinstance(values.get("camera"), dict):
        raise ValueError("The device YAML does not contain a camera section.")
    camera = values["camera"]
    camera.update({"index": index, "width": width, "height": height, "fps": fps})
    camera["backend"] = config.camera.backend
    config_path.write_text(
        yaml.safe_dump(values, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def configure_camera_interactively(
    config: EdgeConfig,
    *,
    input_fn: Callable[[str], str] = input,
) -> None:
    """Select and verify camera capture settings, then persist them to device YAML."""
    from presensi_edge_agent.camera import enumerate_cameras

    cameras = enumerate_cameras(
        config.camera.scan_max_index, backend=config.camera.backend
    )
    if not cameras:
        raise CameraUnavailableError(
            "No camera indices were found. Connect the UVC camera, check OS "
            "camera permission, then run configure-camera again."
        )

    print("\nDetected camera indices (labels vary by operating system):")
    indices = [camera.index for camera in cameras]
    for index in indices:
        marker = " (current)" if index == config.camera.index else ""
        print(f"  {index}{marker}")
    default_index = (
        config.camera.index if config.camera.index in indices else indices[0]
    )
    camera_index = int(
        _read_choice(
            "Camera index",
            [str(value) for value in indices],
            default=str(default_index),
            input_fn=input_fn,
        )
    )

    resolutions = (
        _STB_RESOLUTIONS if config.mode == "STB_GATEWAY" else _EDGE_RESOLUTIONS
    )
    resolution_labels = [f"{width}x{height}" for width, height in resolutions]
    current_resolution = f"{config.camera.width}x{config.camera.height}"
    default_resolution = (
        current_resolution
        if current_resolution in resolution_labels
        else resolution_labels[0]
    )
    selected_resolution = _read_choice(
        "Requested capture resolution",
        resolution_labels,
        default=default_resolution,
        input_fn=input_fn,
    )
    width, height = (int(value) for value in selected_resolution.split("x"))

    fps_choices = (
        ["5", "10", "15"] if config.mode == "STB_GATEWAY" else ["15", "24", "30"]
    )
    default_fps = (
        str(config.camera.fps)
        if str(config.camera.fps) in fps_choices
        else fps_choices[0]
    )
    fps = int(
        _read_choice(
            "Requested camera FPS",
            fps_choices,
            default=default_fps,
            input_fn=input_fn,
        )
    )

    actual_width, actual_height, reported_fps, measured_fps = _probe_mode(
        camera_index, config.camera.backend, width, height, fps
    )
    print(
        f"\nCamera returned {actual_width}x{actual_height}; driver FPS: "
        f"{reported_fps:g}; short probe: {measured_fps:.1f} FPS."
    )
    if (actual_width, actual_height) != (width, height):
        if actual_width <= 0 or actual_height <= 0:
            raise CameraUnavailableError(
                "The camera returned invalid frame dimensions."
            )
        if config.mode == "STB_GATEWAY" and (
            actual_width > 1280 or actual_height > 720
        ):
            raise CameraUnavailableError(
                "The STB camera negotiated above 1280x720. Choose a lower "
                "camera mode with v4l2-ctl before continuing."
            )
        print("The driver negotiated a different resolution than requested.")
        use_actual = (
            input_fn(
                f"Save the actual mode {actual_width}x{actual_height} instead? [Y/n] "
            )
            .strip()
            .lower()
        )
        if use_actual in {"n", "no"}:
            print(
                "No settings were changed. Run configure-camera and choose "
                "another mode."
            )
            return
        width, height = actual_width, actual_height
    confirm = input_fn("Save these requested camera settings? [Y/n] ").strip().lower()
    if confirm in {"n", "no"}:
        print("Camera settings were not changed. Run configure-camera to try again.")
        return

    _write_camera_config(
        config.config_path,
        config,
        index=camera_index,
        width=width,
        height=height,
        fps=fps,
    )
    print(
        f"Saved camera index {camera_index}, {width}x{height} at requested {fps} FPS."
    )
    print(f"Configuration: {config.config_path}")
