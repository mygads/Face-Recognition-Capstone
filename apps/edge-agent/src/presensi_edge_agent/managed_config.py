from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from presensi_edge_agent.config import EdgeConfig, EdgeConfigError

_RECOGNITION_KEYS = {
    "min_top1_similarity",
    "min_top1_top2_margin",
    "minimum_agreeing_frames",
    "sample_every_n_frames",
    "best_frame_count",
    "max_history_frames",
    "min_face_pixels",
    "min_laplacian_variance",
    "min_brightness",
    "max_brightness",
    "calibration_reference",
}
_GATEWAY_KEYS = {
    "motion_threshold",
    "periodic_burst_seconds",
    "minimum_burst_interval_seconds",
    "burst_frame_count",
    "burst_frame_interval_seconds",
    "jpeg_quality",
    "min_brightness",
    "max_brightness",
    "min_sharpness",
}


def managed_config_path(config: EdgeConfig) -> Path:
    device = str(config.device_id or "unassigned")
    return config.runtime.outbox_path.with_name(f"managed-config-{device}.json")


def apply_managed_configuration(
    config: EdgeConfig, *, revision: int, settings: object
) -> EdgeConfig:
    if not isinstance(settings, dict) or revision < 1:
        raise EdgeConfigError("The managed configuration response is invalid.")
    if config.mode == "AI_EDGE":
        if set(settings) != _RECOGNITION_KEYS:
            raise EdgeConfigError("The managed AI_EDGE settings are incomplete.")
        recognition = replace(
            config.recognition,
            min_top1_similarity=_optional_number(settings, "min_top1_similarity"),
            min_top1_top2_margin=_optional_number(settings, "min_top1_top2_margin"),
            minimum_agreeing_frames=_integer(
                settings, "minimum_agreeing_frames", 1, 10
            ),
            sample_every_n_frames=_integer(settings, "sample_every_n_frames", 1, 60),
            best_frame_count=_integer(settings, "best_frame_count", 1, 20),
            max_history_frames=_integer(settings, "max_history_frames", 1, 60),
        )
        quality = replace(
            config.quality,
            min_face_pixels=_integer(settings, "min_face_pixels", 16, 2048),
            min_laplacian_variance=_number(
                settings, "min_laplacian_variance", 0, 100_000
            ),
            min_brightness=_number(settings, "min_brightness", 0, 254),
            max_brightness=_number(settings, "max_brightness", 1, 255),
        )
        if (
            recognition.min_top1_similarity is None
            or recognition.min_top1_top2_margin is None
            or recognition.best_frame_count < recognition.minimum_agreeing_frames
            or recognition.max_history_frames < recognition.best_frame_count
            or quality.min_brightness >= quality.max_brightness
        ):
            raise EdgeConfigError("The managed AI_EDGE policy is not usable.")
        return replace(
            config,
            quality=quality,
            recognition=recognition,
            runtime_config_revision=revision,
        )

    if config.mode == "STB_GATEWAY":
        if set(settings) != _GATEWAY_KEYS:
            raise EdgeConfigError("The managed STB_GATEWAY settings are incomplete.")
        gateway = replace(
            config.gateway,
            motion_threshold=_number(settings, "motion_threshold", 0, 255),
            periodic_burst_seconds=_number(
                settings, "periodic_burst_seconds", 0.01, 3600
            ),
            minimum_burst_interval_seconds=_number(
                settings, "minimum_burst_interval_seconds", 0.01, 3600
            ),
            burst_frame_count=_integer(settings, "burst_frame_count", 1, 5),
            burst_frame_interval_seconds=_number(
                settings, "burst_frame_interval_seconds", 0, 10
            ),
            jpeg_quality=_integer(settings, "jpeg_quality", 20, 100),
            min_brightness=_number(settings, "min_brightness", 0, 254),
            max_brightness=_number(settings, "max_brightness", 1, 255),
            min_sharpness=_number(settings, "min_sharpness", 0, 100_000),
        )
        if gateway.min_brightness >= gateway.max_brightness:
            raise EdgeConfigError("The managed STB brightness range is invalid.")
        return replace(
            config,
            gateway=gateway,
            runtime_config_revision=revision,
        )

    raise EdgeConfigError("This deployment profile cannot receive managed settings.")


def load_cached_configuration(config: EdgeConfig) -> EdgeConfig:
    path = managed_config_path(config)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError
        revision = payload.get("revision")
        if type(revision) is not int:
            raise ValueError
        return apply_managed_configuration(
            config, revision=revision, settings=payload.get("settings")
        )
    except FileNotFoundError:
        return config
    except (OSError, ValueError, TypeError, EdgeConfigError):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return config


def persist_managed_configuration(
    config: EdgeConfig, *, revision: int, settings: dict[str, object]
) -> None:
    path = managed_config_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as output:
            json.dump({"revision": revision, "settings": settings}, output)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
            temporary_path = Path(output.name)
        if os.name != "nt":
            temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _integer(settings: dict[str, Any], name: str, low: int, high: int) -> int:
    value = settings.get(name)
    if type(value) is not int or not low <= value <= high:
        raise EdgeConfigError(f"Managed setting {name} is invalid.")
    return value


def _number(settings: dict[str, Any], name: str, low: float, high: float) -> float:
    value = settings.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EdgeConfigError(f"Managed setting {name} is invalid.")
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise EdgeConfigError(f"Managed setting {name} is invalid.")
    return number


def _optional_number(settings: dict[str, Any], name: str) -> float | None:
    value = settings.get(name)
    if value is None:
        return None
    high = 1 if name == "min_top1_similarity" else 2
    return _number(settings, name, -1 if name == "min_top1_similarity" else 0, high)
