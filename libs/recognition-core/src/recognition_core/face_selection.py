"""Conservative foreground-face selection shared by edge and central inference.

Apparent face size is only a rough distance cue for a monocular RGB camera.
This policy can ignore a clearly smaller background face, but deliberately
fails closed when two faces are similarly sized and both meet the configured
minimum face size.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
from typing import Literal

from recognition_core.domain import FaceDetection

FaceRole = Literal["primary", "background", "ambiguous"]


@dataclass(frozen=True, slots=True)
class FaceSelection:
    selected_index: int | None
    roles: tuple[FaceRole, ...]
    reason_code: str | None = None


class FaceTargetTracker:
    """Bounded, geometry-only continuity guard for a selected camera target.

    A large sudden movement or scale change starts a fresh temporal track.
    This is intentionally conservative: it may ask a moving student to hold
    still for another consensus window, but it cannot combine old evidence
    with a clearly different target.
    """

    def __init__(
        self,
        *,
        max_tracks: int = 1024,
        max_center_shift: float = 0.18,
        max_size_change_ratio: float = 1.6,
    ) -> None:
        if max_tracks < 1:
            raise ValueError("max_tracks must be positive.")
        if not 0 < max_center_shift <= 1:
            raise ValueError("max_center_shift must be in (0, 1].")
        if not math.isfinite(max_size_change_ratio) or max_size_change_ratio <= 1:
            raise ValueError("max_size_change_ratio must be finite and greater than 1.")
        self.max_tracks = max_tracks
        self.max_center_shift = max_center_shift
        self.max_size_change_ratio = max_size_change_ratio
        self._boxes: OrderedDict[str, tuple[float, float, float, float]] = OrderedDict()
        self._lock = RLock()

    def update(
        self,
        track_id: str,
        detection: FaceDetection,
        *,
        frame_width: int,
        frame_height: int,
    ) -> bool:
        """Remember the selected box; return True when continuity is doubtful."""
        with self._lock:
            if frame_width < 1 or frame_height < 1:
                self._boxes.pop(track_id, None)
                return False
            box = detection.box
            current = (
                box.x / frame_width,
                box.y / frame_height,
                box.width / frame_width,
                box.height / frame_height,
            )
            previous = self._boxes.get(track_id)
            switched = False
            if previous is not None:
                previous_center = (
                    previous[0] + previous[2] / 2,
                    previous[1] + previous[3] / 2,
                )
                current_center = (
                    current[0] + current[2] / 2,
                    current[1] + current[3] / 2,
                )
                center_shift = math.dist(previous_center, current_center) / math.sqrt(2)
                size_ratio = max(
                    current[3] / max(previous[3], 1e-9),
                    previous[3] / max(current[3], 1e-9),
                )
                switched = (
                    center_shift > self.max_center_shift
                    or size_ratio > self.max_size_change_ratio
                )
            self._boxes[track_id] = current
            self._boxes.move_to_end(track_id)
            while len(self._boxes) > self.max_tracks:
                self._boxes.popitem(last=False)
            return switched

    def clear(self, track_id: str) -> None:
        with self._lock:
            self._boxes.pop(track_id, None)


def select_primary_face(
    detections: tuple[FaceDetection, ...],
    *,
    min_face_pixels: float = 0.0,
    dominance_ratio: float = 1.8,
) -> FaceSelection:
    """Select one clearly dominant face, or return an explicit ambiguous state.

    ``dominance_ratio`` compares the short side of the face boxes. Its default
    is a conservative starting heuristic, not a physical-distance estimate or
    an identity threshold; deployments should validate it at camera placement.
    """
    if not math.isfinite(min_face_pixels) or min_face_pixels < 0:
        raise ValueError("min_face_pixels must be finite and non-negative.")
    if not math.isfinite(dominance_ratio) or dominance_ratio <= 1:
        raise ValueError("dominance_ratio must be finite and greater than 1.")
    if not detections:
        return FaceSelection(None, ())
    if len(detections) == 1:
        return FaceSelection(0, ("primary",))

    sizes = tuple(min(face.box.width, face.box.height) for face in detections)
    viable = [index for index, size in enumerate(sizes) if size >= min_face_pixels]
    if not viable:
        # Let the normal quality gate explain that the largest visible face is
        # too small; no embedding or identity matching occurs until it passes.
        largest = max(range(len(sizes)), key=sizes.__getitem__)
        roles: list[FaceRole] = ["background"] * len(detections)
        roles[largest] = "primary"
        return FaceSelection(largest, tuple(roles), "face_too_small")

    ranked = sorted(viable, key=lambda index: (-sizes[index], index))
    if len(ranked) == 1:
        selected = ranked[0]
        roles = ["background"] * len(detections)
        roles[selected] = "primary"
        return FaceSelection(selected, tuple(roles))

    largest, runner_up = ranked[:2]
    if sizes[largest] >= sizes[runner_up] * dominance_ratio:
        roles = ["background"] * len(detections)
        roles[largest] = "primary"
        return FaceSelection(largest, tuple(roles))

    roles = ["background"] * len(detections)
    for index in viable:
        roles[index] = "ambiguous"
    return FaceSelection(None, tuple(roles), "multiple_faces")


__all__ = [
    "FaceRole",
    "FaceSelection",
    "FaceTargetTracker",
    "select_primary_face",
]
