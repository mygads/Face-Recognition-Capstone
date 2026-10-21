from __future__ import annotations

import numpy

from recognition_core.domain import BoundingBox, FaceDetection
from recognition_core.opencv_quality import OpenCVFaceQualityAssessor


def _assessor() -> OpenCVFaceQualityAssessor:
    return OpenCVFaceQualityAssessor(
        min_face_pixels=80,
        min_laplacian_variance=45.0,
        min_brightness=25.0,
        max_brightness=235.0,
    )


def _frame() -> numpy.ndarray:
    return numpy.zeros((120, 120, 3), dtype=numpy.uint8)


def _detection() -> FaceDetection:
    return FaceDetection(
        box=BoundingBox(x=10.0, y=10.0, width=100.0, height=100.0),
        confidence=0.9,
    )


class _NanLaplacian:
    def var(self) -> float:
        return float("nan")


class _FakeCV2:
    COLOR_BGR2GRAY = 6
    CV_64F = 6

    @staticmethod
    def cvtColor(crop: object, _code: int) -> object:
        return crop

    @staticmethod
    def Laplacian(_gray: object, _depth: int) -> _NanLaplacian:
        return _NanLaplacian()


class _FakeNumpy:
    @staticmethod
    def mean(_gray: object) -> float:
        return 128.0


def test_quality_assessor_fails_closed_on_non_finite_sharpness() -> None:
    assessor = _assessor()
    assessor._cv2 = _FakeCV2()  # type: ignore[assignment]
    assessor._numpy = _FakeNumpy()  # type: ignore[assignment]

    quality = assessor.assess(_frame(), _detection())

    assert quality.score == 0.0
    assert quality.acceptable is False
    assert quality.reason_codes == ("quality_unavailable",)
