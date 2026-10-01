"""Optional OpenCV Zoo YuNet and SFace adapters.

Importing recognition_core does not require OpenCV or NumPy. These adapters load
those optional runtime dependencies only when an adapter or image loader is used.
"""

from __future__ import annotations

import importlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from recognition_core.domain import BoundingBox, FaceDetection, FaceEmbedding
from recognition_core.protocols import (
    AlignedFace,
    FaceAligner,
    FaceDetector,
    FaceEmbedder,
)


class OpenCVDependencyError(RuntimeError):
    """Raised when an OpenCV adapter is used without its optional dependencies."""


def _load_cv2() -> Any:
    try:
        return importlib.import_module("cv2")
    except ImportError as exc:
        raise OpenCVDependencyError(
            "OpenCV adapters require OpenCV and NumPy. Install this repository's "
            "optional extra with: "
            'python -m pip install -e "libs/recognition-core[opencv]".'
        ) from exc


def _load_numpy() -> Any:
    try:
        return importlib.import_module("numpy")
    except ImportError as exc:
        raise OpenCVDependencyError(
            "OpenCV adapters require NumPy. Install this repository's optional "
            "extra with: "
            'python -m pip install -e "libs/recognition-core[opencv]".'
        ) from exc


def _required_model_path(path: str | Path) -> Path:
    model_path = Path(path).expanduser()
    if not model_path.is_file():
        raise FileNotFoundError(f"Model file does not exist: {model_path}")
    return model_path.resolve()


@dataclass(frozen=True, slots=True)
class YuNetConfig:
    score_threshold: float = 0.9
    nms_threshold: float = 0.3
    top_k: int = 5000
    initial_input_size: tuple[int, int] = (320, 320)

    def __post_init__(self) -> None:
        for name, value in (
            ("score_threshold", self.score_threshold),
            ("nms_threshold", self.nms_threshold),
        ):
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be finite and between 0 and 1.")
        if self.top_k < 1:
            raise ValueError("top_k must be positive.")
        if any(dimension < 1 for dimension in self.initial_input_size):
            raise ValueError("initial_input_size dimensions must be positive.")


class YuNetFaceDetector(FaceDetector):
    """FaceDetectorYN adapter producing the shared five-landmark domain value."""

    def __init__(
        self,
        model_path: str | Path,
        config: YuNetConfig | None = None,
    ) -> None:
        path = _required_model_path(model_path)
        self.config = config or YuNetConfig()
        self._cv2 = _load_cv2()
        self._numpy = _load_numpy()
        self._detector = self._cv2.FaceDetectorYN.create(
            str(path),
            "",
            self.config.initial_input_size,
            self.config.score_threshold,
            self.config.nms_threshold,
            self.config.top_k,
        )

    def detect(self, frame: object) -> tuple[FaceDetection, ...]:
        image = cast(Any, frame)
        if not hasattr(image, "shape") or len(image.shape) < 2:
            raise ValueError("YuNet expects an image with height and width dimensions.")
        height, width = int(image.shape[0]), int(image.shape[1])
        if width < 1 or height < 1:
            raise ValueError("YuNet expects a non-empty image.")

        self._detector.setInputSize((width, height))
        result = self._detector.detect(image)
        if not isinstance(result, tuple) or len(result) != 2:
            raise RuntimeError("OpenCV FaceDetectorYN returned an unexpected result.")
        _, rows = result
        if rows is None:
            return ()

        detections: list[FaceDetection] = []
        for row in self._numpy.asarray(rows).tolist():
            if len(row) < 15:
                raise RuntimeError(
                    "YuNet returned a face row with fewer than 15 values."
                )
            values = tuple(float(value) for value in row[:15])
            if not all(math.isfinite(value) for value in values):
                raise RuntimeError(
                    "YuNet returned non-finite face coordinates or score."
                )
            x, y, box_width, box_height = (float(value) for value in row[:4])
            if box_width <= 0 or box_height <= 0:
                continue
            left = max(0.0, x)
            top = max(0.0, y)
            right = min(float(width), x + box_width)
            bottom = min(float(height), y + box_height)
            if right <= left or bottom <= top:
                continue
            landmarks = tuple(
                (values[index], values[index + 1]) for index in range(4, 14, 2)
            )
            detections.append(
                FaceDetection(
                    box=BoundingBox(left, top, right - left, bottom - top),
                    confidence=values[14],
                    landmarks=landmarks,
                )
            )
        return tuple(detections)


class SFaceModel(FaceAligner, FaceEmbedder):
    """SFace landmark alignment and normalized feature extraction adapter."""

    model_name = "opencv-zoo-sface"

    def __init__(self, model_path: str | Path, *, model_version: str) -> None:
        if not model_version.strip():
            raise ValueError("model_version is required.")
        path = _required_model_path(model_path)
        self.model_version = model_version
        self._cv2 = _load_cv2()
        self._numpy = _load_numpy()
        self._recognizer = self._cv2.FaceRecognizerSF.create(str(path), "")

    def align(self, frame: object, detection: FaceDetection) -> AlignedFace:
        if len(detection.landmarks) != 5:
            raise ValueError("SFace alignment requires exactly five YuNet landmarks.")
        box = detection.box
        raw_row = [box.x, box.y, box.width, box.height]
        for x, y in detection.landmarks:
            raw_row.extend((x, y))
        raw_row.append(detection.confidence)
        face_row = self._numpy.asarray(raw_row, dtype=self._numpy.float32)
        aligned = self._recognizer.alignCrop(cast(Any, frame), face_row)
        if aligned is None:
            raise RuntimeError("OpenCV SFace could not align the detected face.")
        return aligned

    def embed(self, face: AlignedFace) -> FaceEmbedding:
        raw_feature = self._recognizer.feature(cast(Any, face))
        feature = self._numpy.asarray(raw_feature, dtype=self._numpy.float64).reshape(
            -1
        )
        norm = float(self._numpy.linalg.norm(feature))
        if not math.isfinite(norm) or norm <= 0:
            raise ValueError("SFace returned an empty or non-finite embedding.")
        normalized = feature / norm
        values = tuple(float(value) for value in normalized.tolist())
        return FaceEmbedding(
            values=values,
            model_name=self.model_name,
            model_version=self.model_version,
            normalized=True,
        )


def read_color_image(path: str | Path) -> object:
    """Read a BGR image with OpenCV without logging or retaining image content."""
    image_path = Path(path).expanduser()
    if not image_path.is_file():
        raise FileNotFoundError(f"Image file does not exist: {image_path}")
    cv2 = _load_cv2()
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"OpenCV could not decode image: {image_path}")
    return image


def model_version_from_path(path: str | Path) -> str:
    """Use the configured asset filename as its visible model version label."""
    return Path(path).stem
