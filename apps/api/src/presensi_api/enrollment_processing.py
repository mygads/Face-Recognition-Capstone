from __future__ import annotations

import importlib
import io
import math
import os
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from PIL import Image, UnidentifiedImageError

from presensi_api.api.errors import ApiProblem

MAX_CAPTURE_BYTES = 3 * 1024 * 1024
MAX_TOTAL_CAPTURE_BYTES = 15 * 1024 * 1024
MAX_CAPTURE_PIXELS = 16_000_000
MAX_CAPTURE_WIDTH = 4096
MAX_CAPTURE_HEIGHT = 4096


@dataclass(frozen=True, slots=True)
class EnrollmentFrameResult:
    accepted: bool
    model_name: str
    model_version: str
    embedding: tuple[float, ...] | None
    quality_score: float
    quality_metadata: dict[str, float | int | str | bool]
    reason: str | None = None


class EnrollmentProcessor(Protocol):
    def process(
        self, image_bytes: bytes, *, model_version: str
    ) -> EnrollmentFrameResult: ...


class OpenCVEnrollmentProcessor:
    """Extract one quality-approved embedding without retaining the input image."""

    def __init__(
        self,
        *,
        yunet_path: str,
        sface_path: str,
        model_version: str,
        min_face_pixels: int = 80,
        min_laplacian_variance: float = 45.0,
        min_brightness: float = 25.0,
        max_brightness: float = 235.0,
    ) -> None:
        try:
            core_models = importlib.import_module("recognition_core.opencv_models")
            quality_module = importlib.import_module("recognition_core.opencv_quality")
            cv2 = importlib.import_module("cv2")
            numpy = importlib.import_module("numpy")
        except ImportError as exc:
            raise RuntimeError(
                "OpenCV recognition dependencies are unavailable."
            ) from exc
        self._cv2 = cv2
        self._numpy = numpy
        self._detector = core_models.YuNetFaceDetector(yunet_path)
        self._model = core_models.SFaceModel(sface_path, model_version=model_version)
        self._quality_assessor = quality_module.OpenCVFaceQualityAssessor(
            min_face_pixels=min_face_pixels,
            min_laplacian_variance=min_laplacian_variance,
            min_brightness=min_brightness,
            max_brightness=max_brightness,
        )

    def process(
        self, image_bytes: bytes, *, model_version: str
    ) -> EnrollmentFrameResult:
        del model_version  # The configured SFace asset owns its immutable version.
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(image_bytes)) as image:
                    if image.format not in {"JPEG", "PNG", "WEBP"}:
                        return _rejected(self._model.model_version, "unsupported_image")
                    width, height = image.size
                    if (
                        width < 1
                        or height < 1
                        or width > MAX_CAPTURE_WIDTH
                        or height > MAX_CAPTURE_HEIGHT
                        or width * height > MAX_CAPTURE_PIXELS
                    ):
                        return _rejected(self._model.model_version, "image_dimensions")
                    image.load()
                    rgb = image.convert("RGB")
            frame = self._cv2.cvtColor(
                self._numpy.asarray(rgb), self._cv2.COLOR_RGB2BGR
            )
        except (
            UnidentifiedImageError,
            OSError,
            ValueError,
            Image.DecompressionBombError,
        ):
            return _rejected(self._model.model_version, "image_decode_failed")

        detections = self._detector.detect(frame)
        if len(detections) != 1:
            return _rejected(
                self._model.model_version,
                "no_face" if not detections else "multiple_faces",
            )
        detection = detections[0]
        quality = self._quality_assessor.assess(frame, detection)
        metadata: dict[str, float | int | str | bool] = {
            "score": quality.score,
            "accepted": quality.acceptable,
            "reason_codes": ",".join(quality.reason_codes),
        }
        metadata.update(
            {
                name: float(value)
                for name, value in quality.signals
                if math.isfinite(value)
            }
        )
        if not quality.acceptable:
            return EnrollmentFrameResult(
                accepted=False,
                model_name=self._model.model_name,
                model_version=self._model.model_version,
                embedding=None,
                quality_score=quality.score,
                quality_metadata=metadata,
                reason="quality_rejected",
            )
        aligned = self._model.align(frame, detection)
        embedding = self._model.embed(aligned)
        return EnrollmentFrameResult(
            accepted=True,
            model_name=embedding.model_name,
            model_version=embedding.model_version,
            embedding=embedding.values,
            quality_score=quality.score,
            quality_metadata=metadata,
        )


def get_enrollment_processor(
    quality_settings: Mapping[str, object] | None = None,
) -> EnrollmentProcessor:
    yunet_path = os.getenv("PRESENSI_ENROLLMENT_YUNET_MODEL_PATH", "").strip()
    sface_path = os.getenv("PRESENSI_ENROLLMENT_SFACE_MODEL_PATH", "").strip()
    model_version = os.getenv("PRESENSI_ENROLLMENT_MODEL_VERSION", "").strip()
    if not yunet_path or not sface_path or not model_version:
        raise ApiProblem(
            503,
            "enrollment_models_unavailable",
            "Enrollment image processing is not configured on this server.",
        )
    try:
        values = quality_settings or {}
        return OpenCVEnrollmentProcessor(
            yunet_path=yunet_path,
            sface_path=sface_path,
            model_version=model_version,
            min_face_pixels=_quality_int(
                values,
                "min_face_pixels",
                "PRESENSI_ENROLLMENT_MIN_FACE_PIXELS",
                80,
            ),
            min_laplacian_variance=_quality_float(
                values,
                "min_sharpness",
                "PRESENSI_ENROLLMENT_MIN_SHARPNESS",
                45.0,
            ),
            min_brightness=_quality_float(
                values,
                "min_brightness",
                "PRESENSI_ENROLLMENT_MIN_BRIGHTNESS",
                25.0,
            ),
            max_brightness=_quality_float(
                values,
                "max_brightness",
                "PRESENSI_ENROLLMENT_MAX_BRIGHTNESS",
                235.0,
            ),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise ApiProblem(
            503,
            "enrollment_models_unavailable",
            "Enrollment image processing is not configured on this server.",
        ) from exc


def _setting_value(
    settings: Mapping[str, object],
    name: str,
    environment_name: str,
    default: int | float,
) -> object:
    value = settings.get(name)
    return os.getenv(environment_name, str(default)) if value is None else value


def _quality_int(
    settings: Mapping[str, object], name: str, environment_name: str, default: int
) -> int:
    value = _setting_value(settings, name, environment_name, default)
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        parsed = float(value)
        if math.isfinite(parsed) and parsed.is_integer():
            return int(parsed)
    raise ValueError(f"{name} must be an integer.")


def _quality_float(
    settings: Mapping[str, object],
    name: str,
    environment_name: str,
    default: float,
) -> float:
    value = _setting_value(settings, name, environment_name, default)
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"{name} must be a number.")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite.")
    return parsed


def _rejected(model_version: str, reason: str) -> EnrollmentFrameResult:
    return EnrollmentFrameResult(
        accepted=False,
        model_name="opencv-zoo-sface",
        model_version=model_version,
        embedding=None,
        quality_score=0.0,
        quality_metadata={"score": 0.0, "accepted": False, "reason_codes": reason},
        reason=reason,
    )
