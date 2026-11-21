from __future__ import annotations

import pytest

from recognition_core.domain import BoundingBox, FaceDetection
from recognition_core.face_selection import FaceTargetTracker, select_primary_face


def _face(x: float, y: float, width: float, height: float) -> FaceDetection:
    return FaceDetection(
        box=BoundingBox(x=x, y=y, width=width, height=height),
        confidence=0.98,
    )


def test_single_face_is_primary_and_keeps_existing_quality_gate() -> None:
    selection = select_primary_face((_face(50, 30, 90, 110),), min_face_pixels=80)

    assert selection.selected_index == 0
    assert selection.roles == ("primary",)
    assert selection.reason_code is None


def test_one_viable_face_is_selected_and_smaller_background_is_ignored() -> None:
    selection = select_primary_face(
        (_face(200, 100, 210, 250), _face(700, 80, 50, 65)),
        min_face_pixels=80,
    )

    assert selection.selected_index == 0
    assert selection.roles == ("primary", "background")


def test_clearly_dominant_face_is_selected_without_matching_background() -> None:
    selection = select_primary_face(
        (_face(50, 50, 220, 260), _face(700, 60, 110, 125)),
        min_face_pixels=80,
        dominance_ratio=1.8,
    )

    assert selection.selected_index == 0
    assert selection.roles == ("primary", "background")


def test_two_similar_near_faces_fail_closed_as_ambiguous() -> None:
    selection = select_primary_face(
        (_face(50, 50, 210, 250), _face(400, 60, 195, 230)),
        min_face_pixels=80,
    )

    assert selection.selected_index is None
    assert selection.roles == ("ambiguous", "ambiguous")
    assert selection.reason_code == "multiple_faces"


def test_when_all_faces_are_small_largest_reaches_existing_quality_check() -> None:
    selection = select_primary_face(
        (_face(50, 50, 42, 50), _face(400, 60, 55, 65)),
        min_face_pixels=80,
    )

    assert selection.selected_index == 1
    assert selection.roles == ("background", "primary")
    assert selection.reason_code == "face_too_small"


def test_target_tracker_keeps_small_motion_but_resets_on_clear_target_switch() -> None:
    tracker = FaceTargetTracker()
    first = _face(100, 100, 180, 220)

    assert not tracker.update("camera-1", first, frame_width=1000, frame_height=800)
    assert not tracker.update(
        "camera-1", _face(118, 110, 178, 220), frame_width=1000, frame_height=800
    )
    assert tracker.update(
        "camera-1", _face(650, 100, 180, 220), frame_width=1000, frame_height=800
    )


def test_target_tracker_resets_after_selected_target_disappears() -> None:
    tracker = FaceTargetTracker()
    face = _face(100, 100, 180, 220)

    tracker.update("camera-1", face, frame_width=1000, frame_height=800)
    tracker.clear("camera-1")

    assert not tracker.update("camera-1", face, frame_width=1000, frame_height=800)


@pytest.mark.parametrize("ratio", [1.0, 0.5, float("nan"), float("inf")])
def test_invalid_dominance_ratio_is_rejected(ratio: float) -> None:
    with pytest.raises(ValueError):
        select_primary_face((_face(20, 20, 100, 100),), dominance_ratio=ratio)
