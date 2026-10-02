"""Transient camera framing and image-quality feedback for the local preview."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from presensi_edge_agent.config import EdgeConfig
from recognition_core.domain import FaceDetection, FaceQuality
from recognition_core.opencv_models import YuNetConfig, YuNetFaceDetector
from recognition_core.opencv_quality import OpenCVFaceQualityAssessor
from recognition_core.protocols import FaceDetector, FaceQualityAssessor, ImageFrame


@dataclass(frozen=True, slots=True)
class CameraFrameDiagnostics:
    state: str
    message: str
    frame_width: int
    frame_height: int
    face_count: int
    faces: tuple[dict[str, object], ...]

    def as_payload(self) -> dict[str, object]:
        return {
            "state": self.state,
            "message": self.message,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "face_count": self.face_count,
            "faces": list(self.faces),
        }


class CameraFrameInspector:
    """Run detection and quality only; never computes or exposes identity scores."""

    def __init__(
        self,
        detector: FaceDetector,
        quality_assessor: FaceQualityAssessor,
    ) -> None:
        self.detector = detector
        self.quality_assessor = quality_assessor

    def inspect(self, frame: ImageFrame) -> CameraFrameDiagnostics:
        image = cast(Any, frame)
        height, width = int(image.shape[0]), int(image.shape[1])
        detections = tuple(self.detector.detect(frame))[:10]
        if not detections:
            return CameraFrameDiagnostics(
                state="no_face",
                message=(
                    "Wajah belum tertangkap. Arahkan kamera ke siswa dan posisikan "
                    "wajah di tengah frame."
                ),
                frame_width=width,
                frame_height=height,
                face_count=0,
                faces=(),
            )

        single_face = len(detections) == 1
        faces = tuple(
            self._face_payload(detection, width, height, frame, single_face)
            for detection in detections
        )
        if not single_face:
            state = "multiple_faces"
            message = (
                "Ada beberapa wajah di frame. Pastikan satu siswa di depan kamera."
            )
        elif bool(faces[0]["acceptable"]):
            state = "ready"
            message = (
                "Frame siap diperiksa. Indikator ini belum memastikan identitas "
                "atau mencatat presensi."
            )
        else:
            reasons = cast(list[str], faces[0]["reason_codes"])
            state, message = self._quality_message(reasons)
        return CameraFrameDiagnostics(
            state=state,
            message=message,
            frame_width=width,
            frame_height=height,
            face_count=len(detections),
            faces=faces,
        )

    def _face_payload(
        self,
        detection: FaceDetection,
        frame_width: int,
        frame_height: int,
        frame: ImageFrame,
        assess_quality: bool,
    ) -> dict[str, object]:
        box = detection.box
        quality = (
            self.quality_assessor.assess(frame, detection)
            if assess_quality
            else FaceQuality(
                score=0.0,
                acceptable=False,
                reason_codes=("multiple_faces",),
            )
        )
        signals = dict(quality.signals)
        return {
            "x": min(1.0, box.x / frame_width),
            "y": min(1.0, box.y / frame_height),
            "width": min(1.0, box.width / frame_width),
            "height": min(1.0, box.height / frame_height),
            "acceptable": quality.acceptable,
            "quality_score": quality.score,
            "reason_codes": list(quality.reason_codes),
            "face_pixels": signals.get("face_size_px"),
            "sharpness": signals.get("sharpness"),
            "brightness": signals.get("brightness"),
        }

    @staticmethod
    def _quality_message(reasons: list[str]) -> tuple[str, str]:
        if "face_too_small" in reasons:
            return (
                "adjust",
                "Wajah terdeteksi, tetapi terlalu kecil. Dekatkan siswa ke kamera.",
            )
        if "frame_blurry" in reasons:
            return (
                "adjust",
                "Wajah terdeteksi, tetapi gambar buram. "
                "Tahan posisi dan fokuskan kamera.",
            )
        if "lighting_out_of_range" in reasons:
            return (
                "adjust",
                "Pencahayaan wajah belum cukup. Tambahkan lampu dari arah depan.",
            )
        return (
            "adjust",
            "Wajah terdeteksi, tetapi kualitas frame belum cukup. "
            "Atur posisi lalu coba lagi.",
        )


def build_camera_frame_inspector(config: EdgeConfig) -> CameraFrameInspector:
    model_path = config.models.yunet_path
    if model_path is None or not model_path.is_file():
        raise FileNotFoundError("YuNet model is not available for camera preview.")
    return CameraFrameInspector(
        detector=YuNetFaceDetector(model_path, YuNetConfig()),
        quality_assessor=OpenCVFaceQualityAssessor(
            min_face_pixels=config.quality.min_face_pixels,
            min_laplacian_variance=config.quality.min_laplacian_variance,
            min_brightness=config.quality.min_brightness,
            max_brightness=config.quality.max_brightness,
        ),
    )


__all__ = [
    "CameraFrameDiagnostics",
    "CameraFrameInspector",
    "build_camera_frame_inspector",
]
