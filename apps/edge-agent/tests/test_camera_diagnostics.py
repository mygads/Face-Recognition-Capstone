from __future__ import annotations

from types import SimpleNamespace

from presensi_edge_agent.camera_diagnostics import CameraFrameInspector
from recognition_core.domain import BoundingBox, FaceDetection, FaceQuality


class FakeDetector:
    def __init__(self, faces: tuple[FaceDetection, ...]) -> None:
        self.faces = faces

    def detect(self, _frame: object) -> tuple[FaceDetection, ...]:
        return self.faces


class FakeQualityAssessor:
    def __init__(self, result: FaceQuality) -> None:
        self.result = result

    def assess(self, _frame: object, _detection: FaceDetection) -> FaceQuality:
        return self.result


def _face(x: float = 640, y: float = 180) -> FaceDetection:
    return FaceDetection(
        box=BoundingBox(x=x, y=y, width=200, height=240),
        confidence=0.98,
    )


def _frame() -> SimpleNamespace:
    return SimpleNamespace(shape=(720, 1280, 3))


def test_ready_face_gets_normalized_green_ring_payload_without_identity_data() -> None:
    inspector = CameraFrameInspector(
        FakeDetector((_face(),)),
        FakeQualityAssessor(
            FaceQuality(
                score=0.91,
                acceptable=True,
                signals=(
                    ("face_size_px", 200.0),
                    ("sharpness", 72.0),
                    ("brightness", 96.0),
                ),
            )
        ),
    )

    result = inspector.inspect(_frame())
    payload = result.as_payload()

    assert result.state == "ready"
    assert result.face_count == 1
    assert result.message.startswith("Frame siap diperiksa")
    assert result.faces[0]["x"] == 0.5
    assert result.faces[0]["y"] == 0.25
    assert result.faces[0]["width"] == 200 / 1280
    assert result.faces[0]["height"] == 240 / 720
    assert result.faces[0]["acceptable"] is True
    assert "embedding" not in str(payload).lower()
    assert "student" not in str(payload).lower()


def test_poor_light_or_blur_guides_reposition_without_marking_frame_ready() -> None:
    inspector = CameraFrameInspector(
        FakeDetector((_face(),)),
        FakeQualityAssessor(
            FaceQuality(
                score=0.42,
                acceptable=False,
                signals=(("brightness", 18.0), ("sharpness", 18.0)),
                reason_codes=("lighting_out_of_range",),
            )
        ),
    )

    result = inspector.inspect(_frame())

    assert result.state == "adjust"
    assert "Tambahkan lampu" in result.message
    assert result.faces[0]["acceptable"] is False


def test_no_face_and_multiple_faces_have_distinct_guidance() -> None:
    quality = FakeQualityAssessor(FaceQuality(score=0.8, acceptable=True))
    no_face = CameraFrameInspector(FakeDetector(()), quality).inspect(_frame())
    multiple = CameraFrameInspector(
        FakeDetector((_face(), _face(x=200))), quality
    ).inspect(_frame())

    assert no_face.state == "no_face"
    assert no_face.face_count == 0
    assert "tengah frame" in no_face.message
    assert multiple.state == "multiple_faces"
    assert multiple.face_count == 2
    assert all(face["acceptable"] is False for face in multiple.faces)
