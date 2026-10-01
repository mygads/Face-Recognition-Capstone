from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from recognition_core.opencv_models import (
    OpenCVDependencyError,
    SFaceModel,
    YuNetConfig,
    YuNetFaceDetector,
)


class FakeArray(list[Any]):
    def tolist(self) -> list[Any]:
        return list(self)

    def reshape(self, *_shape: int) -> FakeArray:
        return self

    def __truediv__(self, divisor: float) -> FakeArray:
        return FakeArray([float(value) / divisor for value in self])


class FakeNumpy:
    float32 = "float32"
    float64 = "float64"

    @staticmethod
    def asarray(values: Any, dtype: Any = None) -> FakeArray:
        del dtype
        if isinstance(values, FakeArray):
            return values
        return FakeArray(values)

    class linalg:
        @staticmethod
        def norm(values: FakeArray) -> float:
            return math.sqrt(sum(float(value) ** 2 for value in values))


class FakeFrame:
    shape = (100, 80, 3)


class FakeDetector:
    def __init__(self) -> None:
        self.input_size: tuple[int, int] | None = None

    def setInputSize(self, size: tuple[int, int]) -> None:
        self.input_size = size

    def detect(self, _frame: object) -> tuple[int, list[list[float]]]:
        return (
            1,
            [
                [
                    -2,
                    5,
                    30,
                    20,
                    10,
                    11,
                    20,
                    11,
                    15,
                    16,
                    10,
                    22,
                    20,
                    22,
                    0.97,
                ]
            ],
        )


class FakeRecognizer:
    def __init__(self) -> None:
        self.alignment_row: FakeArray | None = None

    def alignCrop(self, _frame: object, row: FakeArray) -> str:
        self.alignment_row = row
        return "synthetic-aligned-face"

    def feature(self, _face: object) -> list[float]:
        return [3.0, 4.0]


class FakeFaceDetectorYN:
    instance: FakeDetector | None = None
    arguments: tuple[Any, ...] | None = None

    @classmethod
    def create(cls, *arguments: Any) -> FakeDetector:
        cls.arguments = arguments
        cls.instance = FakeDetector()
        return cls.instance


class FakeFaceRecognizerSF:
    instance: FakeRecognizer | None = None
    arguments: tuple[Any, ...] | None = None

    @classmethod
    def create(cls, *arguments: Any) -> FakeRecognizer:
        cls.arguments = arguments
        cls.instance = FakeRecognizer()
        return cls.instance


class FakeCV2:
    FaceDetectorYN = FakeFaceDetectorYN
    FaceRecognizerSF = FakeFaceRecognizerSF


@pytest.fixture
def model_files(tmp_path: Path) -> tuple[Path, Path]:
    yunet_path = tmp_path / "synthetic-yunet.onnx"
    sface_path = tmp_path / "synthetic-sface.onnx"
    yunet_path.write_bytes(b"synthetic test model marker")
    sface_path.write_bytes(b"synthetic test model marker")
    return yunet_path, sface_path


def test_yunet_adapter_returns_box_landmarks_and_configured_model_path(
    monkeypatch: pytest.MonkeyPatch, model_files: tuple[Path, Path]
) -> None:
    import recognition_core.opencv_models as adapters

    monkeypatch.setattr(adapters, "_load_cv2", lambda: FakeCV2)
    monkeypatch.setattr(adapters, "_load_numpy", lambda: FakeNumpy)
    yunet_path, _ = model_files
    detector = YuNetFaceDetector(
        yunet_path,
        YuNetConfig(score_threshold=0.4, nms_threshold=0.5, top_k=25),
    )

    detections = detector.detect(FakeFrame())

    assert FakeFaceDetectorYN.arguments is not None
    assert FakeFaceDetectorYN.arguments[0] == str(yunet_path.resolve())
    assert FakeFaceDetectorYN.arguments[-3:] == (0.4, 0.5, 25)
    assert FakeFaceDetectorYN.instance is not None
    assert FakeFaceDetectorYN.instance.input_size == (80, 100)
    assert len(detections) == 1
    assert detections[0].box.x == 0
    assert detections[0].box.width == 28
    assert detections[0].confidence == pytest.approx(0.97)
    assert detections[0].landmarks == (
        (10.0, 11.0),
        (20.0, 11.0),
        (15.0, 16.0),
        (10.0, 22.0),
        (20.0, 22.0),
    )


def test_sface_aligns_using_all_five_landmarks_and_l2_normalizes_embedding(
    monkeypatch: pytest.MonkeyPatch, model_files: tuple[Path, Path]
) -> None:
    import recognition_core.opencv_models as adapters

    monkeypatch.setattr(adapters, "_load_cv2", lambda: FakeCV2)
    monkeypatch.setattr(adapters, "_load_numpy", lambda: FakeNumpy)
    yunet_path, sface_path = model_files
    detector = YuNetFaceDetector(yunet_path)
    detection = detector.detect(FakeFrame())[0]
    recognizer = SFaceModel(sface_path, model_version="synthetic-sface-v1")

    aligned = recognizer.align(FakeFrame(), detection)
    embedding = recognizer.embed(aligned)

    assert FakeFaceRecognizerSF.arguments == (str(sface_path.resolve()), "")
    assert aligned == "synthetic-aligned-face"
    assert FakeFaceRecognizerSF.instance is not None
    assert FakeFaceRecognizerSF.instance.alignment_row is not None
    assert len(FakeFaceRecognizerSF.instance.alignment_row) == 15
    assert embedding.model_name == "opencv-zoo-sface"
    assert embedding.model_version == "synthetic-sface-v1"
    assert embedding.normalized is True
    assert embedding.values == pytest.approx((0.6, 0.8))


def test_models_require_existing_paths_and_sface_model_version(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError, match="Model file does not exist"):
        YuNetFaceDetector(tmp_path / "missing.onnx")
    with pytest.raises(ValueError, match="model_version is required"):
        SFaceModel(tmp_path / "missing.onnx", model_version=" ")


def test_optional_opencv_dependency_error_is_clear(
    monkeypatch: pytest.MonkeyPatch, model_files: tuple[Path, Path]
) -> None:
    import recognition_core.opencv_models as adapters

    def missing_dependency() -> Any:
        raise OpenCVDependencyError("Install the opencv extra.")

    monkeypatch.setattr(adapters, "_load_cv2", missing_dependency)
    with pytest.raises(OpenCVDependencyError, match="opencv extra"):
        YuNetFaceDetector(model_files[0])
