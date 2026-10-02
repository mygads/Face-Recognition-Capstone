"""Local webcam placement and lighting utility; never records camera frames."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from presensi_edge_agent.camera import enumerate_cameras
from presensi_edge_agent.config import EdgeConfig, EdgeConfigError, load_config
from recognition_core.domain import FaceDetection, FaceQuality
from recognition_core.opencv_models import YuNetConfig, YuNetFaceDetector
from recognition_core.opencv_quality import OpenCVFaceQualityAssessor


class CalibrationError(RuntimeError):
    """Raised when the local camera diagnostic cannot continue safely."""


@dataclass(frozen=True, slots=True)
class FaceObservation:
    detection: FaceDetection
    quality: FaceQuality
    face_pixels: int
    face_brightness: float
    blur_score: float
    background_brightness: float | None
    warnings: tuple[str, ...]


class ScalarSummary:
    """Constant-memory aggregate for one numeric diagnostic signal."""

    def __init__(self) -> None:
        self.count = 0
        self.total = 0.0
        self.minimum: float | None = None
        self.maximum: float | None = None

    def add(self, value: float) -> None:
        if not math.isfinite(value):
            return
        self.count += 1
        self.total += value
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)

    def as_dict(self) -> dict[str, int | float] | None:
        if self.count == 0:
            return None
        assert self.minimum is not None and self.maximum is not None
        return {
            "count": self.count,
            "mean": round(self.total / self.count, 3),
            "min": round(self.minimum, 3),
            "max": round(self.maximum, 3),
        }


class CalibrationStats:
    """Store aggregate camera-quality measurements, never frame content."""

    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.frame_count = 0
        self.single_face_frames = 0
        self.multiple_face_frames = 0
        self.no_face_frames = 0
        self.quality_accepted_faces = 0
        self.face_count = 0
        self.backlight_frames = 0
        self.warnings: Counter[str] = Counter()
        self.frame_brightness = ScalarSummary()
        self.face_short_side = ScalarSummary()
        self.face_brightness = ScalarSummary()
        self.background_brightness = ScalarSummary()
        self.blur_score = ScalarSummary()
        self.quality_score = ScalarSummary()

    def record(
        self,
        observations: tuple[FaceObservation, ...],
        frame_warnings: set[str],
        *,
        frame_brightness: float,
    ) -> None:
        self.frame_count += 1
        self.frame_brightness.add(frame_brightness)
        if not observations:
            self.no_face_frames += 1
        elif len(observations) == 1:
            self.single_face_frames += 1
        else:
            self.multiple_face_frames += 1

        for observation in observations:
            self.face_count += 1
            self.quality_accepted_faces += int(observation.quality.acceptable)
            self.face_short_side.add(float(observation.face_pixels))
            self.face_brightness.add(observation.face_brightness)
            self.blur_score.add(observation.blur_score)
            self.quality_score.add(observation.quality.score)
            if observation.background_brightness is not None:
                self.background_brightness.add(observation.background_brightness)
            frame_warnings.update(observation.warnings)
        if "BACKLIGHT" in frame_warnings:
            self.backlight_frames += 1
        self.warnings.update(frame_warnings)

    def report(self, *, elapsed_seconds: float) -> dict[str, Any]:
        return {
            "duration_seconds": round(elapsed_seconds, 3),
            "frames_seen": self.frame_count,
            "observed_preview_fps": round(self.frame_count / elapsed_seconds, 3)
            if elapsed_seconds > 0 and self.frame_count
            else None,
            "face_frames": {
                "none": self.no_face_frames,
                "one": self.single_face_frames,
                "multiple": self.multiple_face_frames,
            },
            "face_detections": self.face_count,
            "quality_accepted_detections": self.quality_accepted_faces,
            "quality_acceptance_percent": round(
                100 * self.quality_accepted_faces / self.face_count, 2
            )
            if self.face_count
            else None,
            "backlight_frames": self.backlight_frames,
            "warning_frame_counts": dict(sorted(self.warnings.items())),
            "scene_brightness_proxy_gray_0_255": self.frame_brightness.as_dict(),
            "face_short_side_px": self.face_short_side.as_dict(),
            "face_brightness_proxy_gray_0_255": self.face_brightness.as_dict(),
            "background_brightness_proxy_gray_0_255": (
                self.background_brightness.as_dict()
            ),
            "face_blur_laplacian_variance": self.blur_score.as_dict(),
            "face_quality_score_0_1": self.quality_score.as_dict(),
        }


def _cv2() -> Any:
    try:
        import cv2
    except ImportError as exc:
        raise CalibrationError(
            'OpenCV is missing. Install the "camera-preview" optional extra.'
        ) from exc
    return cv2


def _defaults_from_config(
    config: EdgeConfig | None,
) -> dict[str, Any]:
    if config is None:
        return {
            "camera_index": 0,
            "width": 1280,
            "height": 720,
            "fps": 30,
            "backend": "auto",
            "scan_max_index": 8,
            "model_path": None,
            "model_version": "unspecified",
            "min_face_pixels": 80,
            "min_blur_score": 45.0,
            "min_brightness": 25.0,
            "max_brightness": 235.0,
        }
    return {
        "camera_index": config.camera.index,
        "width": config.camera.width,
        "height": config.camera.height,
        "fps": config.camera.fps,
        "backend": config.camera.backend,
        "scan_max_index": config.camera.scan_max_index,
        "model_path": config.models.yunet_path,
        "model_version": (
            config.models.yunet_path.stem
            if config.models.yunet_path is not None
            else "unspecified"
        ),
        "min_face_pixels": config.quality.min_face_pixels,
        "min_blur_score": config.quality.min_laplacian_variance,
        "min_brightness": config.quality.min_brightness,
        "max_brightness": config.quality.max_brightness,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview a local UVC camera and inspect face framing, blur, and "
            "lighting. Frames are analyzed in memory and never saved."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        help=(
            "Optional edge-agent YAML; only camera, YuNet path, and quality "
            "values are used."
        ),
    )
    parser.add_argument("--camera-index", type=int)
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--fps", type=int)
    parser.add_argument("--backend", choices=("auto", "dshow", "msmf", "v4l2"))
    parser.add_argument("--scan-max-index", type=int)
    parser.add_argument("--list-cameras", action="store_true")
    parser.add_argument("--yunet-model", type=Path)
    parser.add_argument("--model-version")
    parser.add_argument("--min-face-pixels", type=int)
    parser.add_argument("--min-blur-score", type=float)
    parser.add_argument("--min-brightness", type=float)
    parser.add_argument("--max-brightness", type=float)
    parser.add_argument(
        "--backlight-delta",
        type=float,
        default=40.0,
        help="Face-to-background brightness gap that raises a backlight warning.",
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=0.0,
        help="Stop automatically after this duration; 0 means stop with Q or Esc.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Optional JSON calibration report. Contains aggregates only, no frames.",
    )
    return parser


def _open_capture(cv2: Any, camera_index: int, backend: str) -> Any:
    backend_names = {
        "dshow": "CAP_DSHOW",
        "msmf": "CAP_MSMF",
        "v4l2": "CAP_V4L2",
    }
    backend_id = None
    if backend != "auto":
        backend_id = getattr(cv2, backend_names[backend], None)
        if backend_id is None:
            raise CalibrationError(
                f"Camera backend {backend!r} is unavailable on this operating system."
            )
    capture = (
        cv2.VideoCapture(camera_index)
        if backend_id is None
        else cv2.VideoCapture(camera_index, backend_id)
    )
    if not capture.isOpened():
        capture.release()
        raise CalibrationError(f"Cannot open camera index {camera_index}.")
    return capture


def _signal(quality: FaceQuality, name: str) -> float | None:
    return next((value for key, value in quality.signals if key == name), None)


def _face_bounds(
    detection: FaceDetection, width: int, height: int
) -> tuple[int, int, int, int]:
    left = max(0, min(width - 1, int(detection.box.x)))
    top = max(0, min(height - 1, int(detection.box.y)))
    right = max(left + 1, min(width, math.ceil(detection.box.x + detection.box.width)))
    bottom = max(
        top + 1, min(height, math.ceil(detection.box.y + detection.box.height))
    )
    return left, top, right, bottom


def _background_brightness(
    gray_frame: Any,
    bounds: tuple[int, int, int, int],
    cv2: Any,
    np: Any,
) -> float | None:
    height, width = gray_frame.shape[:2]
    left, top, right, bottom = bounds
    mask = np.full((height, width), 255, dtype=np.uint8)
    cv2.rectangle(mask, (left, top), (right, bottom), 0, thickness=-1)
    if not np.any(mask):
        return None
    return float(cv2.mean(gray_frame, mask=mask)[0])


def _analyze_face(
    frame: Any,
    gray_frame: Any,
    detection: FaceDetection,
    assessor: OpenCVFaceQualityAssessor,
    *,
    cv2: Any,
    np: Any,
    min_face_pixels: int,
    min_blur_score: float,
    min_brightness: float,
    max_brightness: float,
    backlight_delta: float,
) -> FaceObservation:
    quality = assessor.assess(frame, detection)
    face_pixels_value = _signal(quality, "face_size_px")
    blur_score = _signal(quality, "sharpness")
    face_brightness = _signal(quality, "brightness")
    if face_pixels_value is None or blur_score is None or face_brightness is None:
        raise CalibrationError("Quality assessor did not return expected signals.")
    face_pixels = int(face_pixels_value)
    bounds = _face_bounds(detection, int(frame.shape[1]), int(frame.shape[0]))
    background = _background_brightness(gray_frame, bounds, cv2, np)
    warnings: list[str] = []
    if face_pixels < min_face_pixels:
        warnings.append("FACE_TOO_SMALL")
    if blur_score < min_blur_score:
        warnings.append("BLURRY")
    if face_brightness < min_brightness:
        warnings.append("TOO_DARK")
    elif face_brightness > max_brightness:
        warnings.append("TOO_BRIGHT")
    if (
        background is not None
        and background >= min_brightness
        and background - face_brightness >= backlight_delta
    ):
        warnings.append("BACKLIGHT")
    return FaceObservation(
        detection=detection,
        quality=quality,
        face_pixels=face_pixels,
        face_brightness=face_brightness,
        blur_score=blur_score,
        background_brightness=background,
        warnings=tuple(warnings),
    )


def _warning_text(code: str) -> str:
    return {
        "NO_FACE": "No face detected — adjust camera framing or distance.",
        "MULTIPLE_FACES": "Multiple faces — calibrate with one person in view.",
        "FACE_TOO_SMALL": "Face is small — move camera closer or frame the path.",
        "BLURRY": "Image is blurry — stabilize camera or improve light/motion.",
        "TOO_DARK": (
            "Lighting is low — try diffuse frontal light or reposition the camera."
        ),
        "TOO_BRIGHT": "Face is over-bright — reduce direct light or adjust exposure.",
        "BACKLIGHT": "Background is much brighter — change camera/light direction.",
    }.get(code, code.replace("_", " "))


def _draw_overlay(
    frame: Any,
    observations: tuple[FaceObservation, ...],
    warnings: set[str],
    *,
    fps: float,
    frame_brightness: float,
    cv2: Any,
) -> Any:
    shown = frame.copy()
    height, width = shown.shape[:2]
    for index, observation in enumerate(observations, start=1):
        bounds = _face_bounds(observation.detection, width, height)
        left, top, right, bottom = bounds
        color = (40, 180, 40) if observation.quality.acceptable else (0, 165, 255)
        cv2.rectangle(shown, (left, top), (right, bottom), color, 2)
        label = (
            f"Face {index}: {right - left}x{bottom - top}px "
            f"blur={observation.blur_score:.0f} "
            f"bright={observation.face_brightness:.0f} "
            f"quality={observation.quality.score:.2f}"
        )
        text_y = max(22, top - 8)
        cv2.putText(
            shown,
            label,
            (left, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            color,
            2,
            cv2.LINE_AA,
        )

    cv2.putText(
        shown,
        f"Preview FPS {fps:.1f} | frame brightness proxy {frame_brightness:.0f}/255",
        (12, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    for index, warning in enumerate(sorted(warnings)):
        cv2.putText(
            shown,
            _warning_text(warning),
            (12, 52 + 24 * index),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.57,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
    cv2.putText(
        shown,
        "Q / Esc: close  |  Frames are not saved",
        (12, max(30, height - 14)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return shown


def _run_preview(args: argparse.Namespace) -> dict[str, Any]:
    cv2 = _cv2()
    import numpy as np

    config = load_config(args.config, environ={}) if args.config else None
    defaults = _defaults_from_config(config)
    camera_index = (
        args.camera_index if args.camera_index is not None else defaults["camera_index"]
    )
    width = args.width if args.width is not None else defaults["width"]
    height = args.height if args.height is not None else defaults["height"]
    fps = args.fps if args.fps is not None else defaults["fps"]
    backend = args.backend or defaults["backend"]
    model_path = args.yunet_model or defaults["model_path"]
    model_version = args.model_version or defaults["model_version"]
    if (not model_version or model_version == "unspecified") and model_path is not None:
        model_version = Path(model_path).stem
    min_face_pixels = (
        args.min_face_pixels
        if args.min_face_pixels is not None
        else defaults["min_face_pixels"]
    )
    min_blur_score = (
        args.min_blur_score
        if args.min_blur_score is not None
        else defaults["min_blur_score"]
    )
    min_brightness = (
        args.min_brightness
        if args.min_brightness is not None
        else defaults["min_brightness"]
    )
    max_brightness = (
        args.max_brightness
        if args.max_brightness is not None
        else defaults["max_brightness"]
    )
    if width < 1 or height < 1 or fps < 1 or camera_index < 0:
        raise CalibrationError("Camera index and requested mode must be positive.")
    if min_face_pixels < 1 or min_blur_score < 0 or args.backlight_delta < 0:
        raise CalibrationError("Quality and backlight settings are invalid.")
    if not 0 <= min_brightness < max_brightness <= 255:
        raise CalibrationError("Brightness limits must satisfy 0 <= min < max <= 255.")
    if args.duration_seconds < 0:
        raise CalibrationError("Duration must not be negative.")
    if model_path is None or not Path(model_path).is_file():
        raise CalibrationError(
            "Provide --yunet-model or a local models.yunet_path in --config. "
            "The utility does not download model weights."
        )

    detector = YuNetFaceDetector(model_path, YuNetConfig())
    assessor = OpenCVFaceQualityAssessor(
        min_face_pixels=min_face_pixels,
        min_laplacian_variance=min_blur_score,
        min_brightness=min_brightness,
        max_brightness=max_brightness,
    )
    capture = _open_capture(cv2, camera_index, backend)
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    capture.set(cv2.CAP_PROP_FPS, fps)
    if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    driver_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    driver_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    reported_fps = float(capture.get(cv2.CAP_PROP_FPS))
    if not math.isfinite(reported_fps) or reported_fps <= 0:
        reported_fps = 0.0

    stats = CalibrationStats()
    frame_times: deque[float] = deque(maxlen=30)
    window_name = "Camera installation calibration"
    try:
        try:
            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        except cv2.error as exc:
            raise CalibrationError(
                "OpenCV preview window is unavailable. Install the desktop "
                '"camera-preview" extra in a local GUI session.'
            ) from exc
        while True:
            ok, frame = capture.read()
            if not ok or frame is None or not getattr(frame, "size", 0):
                raise CalibrationError("Camera stopped returning image frames.")
            frame_started = time.perf_counter()
            frame_times.append(frame_started)
            loop_fps = (
                (len(frame_times) - 1) / (frame_times[-1] - frame_times[0])
                if len(frame_times) > 1 and frame_times[-1] > frame_times[0]
                else 0.0
            )
            gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            frame_brightness = float(np.mean(gray_frame))
            detections = tuple(detector.detect(frame))
            observations = tuple(
                _analyze_face(
                    frame,
                    gray_frame,
                    detection,
                    assessor,
                    cv2=cv2,
                    np=np,
                    min_face_pixels=min_face_pixels,
                    min_blur_score=min_blur_score,
                    min_brightness=min_brightness,
                    max_brightness=max_brightness,
                    backlight_delta=args.backlight_delta,
                )
                for detection in detections
            )
            frame_warnings = {
                warning for item in observations for warning in item.warnings
            }
            if not detections:
                frame_warnings.add("NO_FACE")
                if frame_brightness < min_brightness:
                    frame_warnings.add("TOO_DARK")
            elif len(detections) > 1:
                frame_warnings.add("MULTIPLE_FACES")
            stats.record(
                observations,
                frame_warnings,
                frame_brightness=frame_brightness,
            )
            preview = _draw_overlay(
                frame,
                observations,
                frame_warnings,
                fps=loop_fps,
                frame_brightness=frame_brightness,
                cv2=cv2,
            )
            try:
                cv2.imshow(window_name, preview)
            except cv2.error as exc:
                raise CalibrationError(
                    "Could not display the preview. Use a local GUI session and "
                    "the desktop OpenCV build."
                ) from exc
            key = int(cv2.waitKey(1)) & 0xFF
            elapsed = time.perf_counter() - stats.started
            if key in (27, ord("q"), ord("Q")):
                break
            if args.duration_seconds and elapsed >= args.duration_seconds:
                break
    finally:
        capture.release()
        try:
            cv2.destroyWindow(window_name)
        except cv2.error:
            pass

    elapsed_seconds = time.perf_counter() - stats.started
    capture_width = int(frame.shape[1])
    capture_height = int(frame.shape[0])
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "utility": "presensi-camera-calibration",
        "model": {"name": "opencv-zoo-yunet", "version": model_version},
        "camera": {
            "index": camera_index,
            "backend": backend,
            "requested_width": width,
            "requested_height": height,
            "requested_fps": fps,
            "driver_reported_width": driver_width or None,
            "driver_reported_height": driver_height or None,
            "driver_reported_fps": reported_fps or None,
            "observed_frame_width": capture_width,
            "observed_frame_height": capture_height,
        },
        "quality_limits": {
            "min_face_pixels": min_face_pixels,
            "min_blur_laplacian_variance": min_blur_score,
            "min_brightness_gray_0_255": min_brightness,
            "max_brightness_gray_0_255": max_brightness,
            "backlight_delta_gray_0_255": args.backlight_delta,
        },
        "measurements": stats.report(elapsed_seconds=elapsed_seconds),
        "privacy": {
            "frames_saved": False,
            "face_images_saved": False,
            "embeddings_saved": False,
            "model_path_recorded": False,
        },
        "interpretation": [
            "Brightness is a grayscale pixel-value proxy, not lux or sensor exposure.",
            "Observed preview FPS includes face detection and display processing; "
            "it is not a camera-only FPS measurement.",
            "Blur, size, brightness, and backlight warnings are setup heuristics, "
            "not identity or attendance decisions.",
        ],
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    if path.suffix.lower() != ".json":
        raise CalibrationError("Calibration report path must end in .json.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config, environ={}) if args.config else None
        defaults = _defaults_from_config(config)
        if args.list_cameras:
            backend = args.backend or defaults["backend"]
            max_index = (
                args.scan_max_index
                if args.scan_max_index is not None
                else defaults["scan_max_index"]
            )
            cameras = enumerate_cameras(max_index, backend=backend)
            print(json.dumps({"camera_indices": [camera.index for camera in cameras]}))
            return 0
        report = _run_preview(args)
        if args.report:
            _write_report(args.report, report)
            print(f"Calibration report saved: {args.report}")
        else:
            print(
                json.dumps(
                    {
                        "measurements": report["measurements"],
                        "privacy": report["privacy"],
                    },
                    ensure_ascii=False,
                )
            )
        return 0
    except (CalibrationError, EdgeConfigError, OSError, ValueError) as exc:
        print(f"camera calibration error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Camera preview stopped by user.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
