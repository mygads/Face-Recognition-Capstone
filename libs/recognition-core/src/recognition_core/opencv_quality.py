"""Optional OpenCV image-quality assessor shared by edge and central profiles."""

from __future__ import annotations

import importlib
from typing import Any, cast

from recognition_core.domain import FaceDetection, FaceQuality
from recognition_core.protocols import ImageFrame


class OpenCVFaceQualityAssessor:
    def __init__(
        self,
        *,
        min_face_pixels: int,
        min_laplacian_variance: float,
        min_brightness: float,
        max_brightness: float,
    ) -> None:
        self._cv2 = importlib.import_module("cv2")
        self._numpy = importlib.import_module("numpy")
        self.min_face_pixels = min_face_pixels
        self.min_laplacian_variance = min_laplacian_variance
        self.min_brightness = min_brightness
        self.max_brightness = max_brightness

    def assess(self, frame: ImageFrame, detection: FaceDetection) -> FaceQuality:
        image = cast(Any, frame)
        height, width = int(image.shape[0]), int(image.shape[1])
        box = detection.box
        left = max(0, int(box.x))
        top = max(0, int(box.y))
        right = min(width, int(box.x + box.width))
        bottom = min(height, int(box.y + box.height))
        crop = image[top:bottom, left:right]
        if crop.size == 0:
            return FaceQuality(
                score=0.0,
                acceptable=False,
                reason_codes=("face_crop_empty",),
            )

        gray = self._cv2.cvtColor(crop, self._cv2.COLOR_BGR2GRAY)
        brightness = float(self._numpy.mean(gray))
        sharpness = float(self._cv2.Laplacian(gray, self._cv2.CV_64F).var())
        face_size = min(right - left, bottom - top)
        reasons: list[str] = []
        if face_size < self.min_face_pixels:
            reasons.append("face_too_small")
        if sharpness < self.min_laplacian_variance:
            reasons.append("frame_blurry")
        if not self.min_brightness <= brightness <= self.max_brightness:
            reasons.append("lighting_out_of_range")
        size_score = min(1.0, face_size / self.min_face_pixels)
        sharpness_score = (
            1.0
            if self.min_laplacian_variance == 0
            else min(1.0, sharpness / self.min_laplacian_variance)
        )
        if brightness < self.min_brightness:
            lighting_score = brightness / max(self.min_brightness, 1.0)
        elif brightness > self.max_brightness:
            lighting_score = self.max_brightness / max(brightness, 1.0)
        else:
            lighting_score = 1.0
        return FaceQuality(
            score=min(size_score, sharpness_score, lighting_score),
            acceptable=not reasons,
            signals=(
                ("face_size_px", float(face_size)),
                ("sharpness", sharpness),
                ("brightness", brightness),
            ),
            reason_codes=tuple(reasons),
        )
