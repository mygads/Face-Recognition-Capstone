from __future__ import annotations

import ipaddress
import math
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, cast
from urllib.parse import urlsplit
from uuid import UUID

import yaml


class EdgeConfigError(ValueError):
    """Raised when the edge agent configuration is incomplete or invalid."""


@dataclass(frozen=True, slots=True)
class ApiSettings:
    base_url: str
    timeout_seconds: float
    heartbeat_interval_seconds: float
    cache_refresh_seconds: float
    cache_path: str
    token_file: Path | None
    cache_max_offline_seconds: float = 300.0


@dataclass(frozen=True, slots=True)
class CameraSettings:
    index: int
    width: int
    height: int
    fps: int
    backend: str
    scan_max_index: int
    reconnect_seconds: float


@dataclass(frozen=True, slots=True)
class ModelSettings:
    yunet_path: Path | None
    sface_path: Path | None
    version: str
    liveness_path: Path | None
    liveness_version: str | None


@dataclass(frozen=True, slots=True)
class QualitySettings:
    min_face_pixels: int
    min_laplacian_variance: float
    min_brightness: float
    max_brightness: float


@dataclass(frozen=True, slots=True)
class RecognitionSettings:
    min_top1_similarity: float | None
    min_top1_top2_margin: float | None
    minimum_agreeing_frames: int
    sample_every_n_frames: int
    best_frame_count: int
    max_history_frames: int
    track_ttl_seconds: float


@dataclass(frozen=True, slots=True)
class LivenessSettings:
    enabled: bool
    required: bool
    min_live_score: float | None


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    outbox_path: Path
    max_outbox_events: int
    max_retry_seconds: float
    log_level: str


@dataclass(frozen=True, slots=True)
class CentralAISettings:
    base_url: str
    token_file: Path | None
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class GatewaySettings:
    session_id: UUID | None
    session_starts_at: datetime | None
    session_ends_at: datetime | None
    motion_threshold: float
    periodic_burst_seconds: float
    minimum_burst_interval_seconds: float
    burst_frame_count: int
    burst_frame_interval_seconds: float
    jpeg_quality: int
    min_brightness: float
    max_brightness: float
    min_sharpness: float


@dataclass(frozen=True, slots=True)
class PreviewSettings:
    enabled: bool
    bind_host: str
    port: int
    allowed_origins: tuple[str, ...]
    max_width: int
    jpeg_quality: int


@dataclass(frozen=True, slots=True)
class EdgeConfig:
    config_path: Path
    device_id: UUID | None
    api: ApiSettings
    camera: CameraSettings
    models: ModelSettings
    quality: QualitySettings
    recognition: RecognitionSettings
    liveness: LivenessSettings
    runtime: RuntimeSettings
    mode: str = "AI_EDGE"
    runtime_config_revision: int = 0
    central_ai: CentralAISettings = field(
        default_factory=lambda: CentralAISettings("http://127.0.0.1:8001", None, 8.0)
    )
    gateway: GatewaySettings = field(
        default_factory=lambda: GatewaySettings(
            None, None, None, 7.0, 30.0, 5.0, 3, 0.2, 75, 20.0, 240.0, 8.0
        )
    )
    preview: PreviewSettings = field(
        default_factory=lambda: PreviewSettings(
            True,
            "127.0.0.1",
            8765,
            ("http://127.0.0.1:5173", "http://localhost:5173"),
            640,
            70,
        )
    )

    def require_runtime(
        self,
        *,
        api_token: str | None,
        ai_token: str | None = None,
        allow_unconfigured_thresholds: bool = False,
    ) -> None:
        if self.device_id is None:
            raise EdgeConfigError("PRESENSI_EDGE_DEVICE_ID is required.")
        if self.mode not in {"AI_EDGE", "STB_GATEWAY"}:
            raise EdgeConfigError("mode must be AI_EDGE or STB_GATEWAY.")
        if not self.api.base_url.startswith(("http://", "https://")):
            raise EdgeConfigError("api.base_url must use http:// or https://.")
        if not api_token:
            raise EdgeConfigError(
                "Set PRESENSI_EDGE_API_TOKEN or configure api.token_file."
            )
        if self.mode == "STB_GATEWAY":
            if not self.central_ai.base_url.startswith(("http://", "https://")):
                raise EdgeConfigError(
                    "central_ai.base_url must use http:// or https://."
                )
            if not ai_token:
                raise EdgeConfigError(
                    "Set PRESENSI_EDGE_AI_TOKEN or configure central_ai.token_file."
                )
            starts_at = self.gateway.session_starts_at
            ends_at = self.gateway.session_ends_at
            if (starts_at is None) != (ends_at is None) or (
                starts_at is not None and ends_at is not None and starts_at >= ends_at
            ):
                raise EdgeConfigError(
                    "Optional gateway session window must define valid start/end times."
                )
            if self.camera.width > 1280 or self.camera.height > 720:
                raise EdgeConfigError(
                    "STB_GATEWAY capture is limited to at most 1280x720."
                )
            if self.camera.fps > 15:
                raise EdgeConfigError("STB_GATEWAY capture is limited to 15 FPS.")
            return
        if self.models.yunet_path is None or not self.models.yunet_path.is_file():
            raise EdgeConfigError("models.yunet_path must point to a local model file.")
        if self.models.sface_path is None or not self.models.sface_path.is_file():
            raise EdgeConfigError("models.sface_path must point to a local model file.")
        if not self.models.version.strip():
            raise EdgeConfigError("models.version is required.")
        if not allow_unconfigured_thresholds and (
            self.recognition.min_top1_similarity is None
            or self.recognition.min_top1_top2_margin is None
        ):
            raise EdgeConfigError(
                "Recognition thresholds must be explicitly calibrated in config."
            )
        if self.liveness.required and not self.liveness.enabled:
            raise EdgeConfigError("Required liveness must be enabled.")
        if self.liveness.enabled:
            if (
                self.models.liveness_path is None
                or not self.models.liveness_path.is_file()
            ):
                raise EdgeConfigError(
                    "Enabled liveness needs a locally provisioned model file."
                )
            if not self.models.liveness_version:
                raise EdgeConfigError("models.liveness_version is required.")
            if self.liveness.min_live_score is None:
                raise EdgeConfigError(
                    "Enabled liveness needs a locally calibrated min_live_score."
                )


_ENVIRONMENT_OVERRIDES: dict[
    str, tuple[str, str, type[str] | type[int] | type[float]]
] = {
    "PRESENSI_EDGE_DEVICE_ID": ("", "device_id", str),
    "PRESENSI_EDGE_MODE": ("", "mode", str),
    "PRESENSI_EDGE_API_BASE_URL": ("api", "base_url", str),
    "PRESENSI_EDGE_API_TOKEN_FILE": ("api", "token_file", str),
    "PRESENSI_EDGE_AI_BASE_URL": ("central_ai", "base_url", str),
    "PRESENSI_EDGE_AI_TOKEN_FILE": ("central_ai", "token_file", str),
    "PRESENSI_EDGE_CACHE_MAX_OFFLINE_SECONDS": (
        "api",
        "cache_max_offline_seconds",
        float,
    ),
    "PRESENSI_EDGE_CAMERA_INDEX": ("camera", "index", int),
    "PRESENSI_EDGE_CAMERA_WIDTH": ("camera", "width", int),
    "PRESENSI_EDGE_CAMERA_HEIGHT": ("camera", "height", int),
    "PRESENSI_EDGE_CAMERA_FPS": ("camera", "fps", int),
    "PRESENSI_EDGE_SESSION_ID": ("gateway", "session_id", str),
    "PRESENSI_EDGE_SESSION_STARTS_AT": ("gateway", "session_starts_at", str),
    "PRESENSI_EDGE_SESSION_ENDS_AT": ("gateway", "session_ends_at", str),
    "PRESENSI_EDGE_SAMPLE_EVERY_N_FRAMES": (
        "recognition",
        "sample_every_n_frames",
        int,
    ),
    "PRESENSI_EDGE_YUNET_MODEL_PATH": ("models", "yunet_path", str),
    "PRESENSI_EDGE_SFACE_MODEL_PATH": ("models", "sface_path", str),
    "PRESENSI_EDGE_MODEL_VERSION": ("models", "version", str),
    "PRESENSI_EDGE_MIN_TOP1_SIMILARITY": (
        "recognition",
        "min_top1_similarity",
        float,
    ),
    "PRESENSI_EDGE_MIN_TOP1_TOP2_MARGIN": (
        "recognition",
        "min_top1_top2_margin",
        float,
    ),
    "PRESENSI_EDGE_LOG_LEVEL": ("runtime", "log_level", str),
}


def _mapping(value: object, name: str) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise EdgeConfigError(f"{name} must be a mapping.")
    return cast(dict[str, object], value)


def _set_override(
    data: dict[str, object], name: str, value: str, *, section: str, key: str
) -> None:
    parsed: object = value
    try:
        if section:
            target = _mapping(data.get(section), section)
            data[section] = target
        else:
            target = data
        converter = _ENVIRONMENT_OVERRIDES[name][2]
        parsed = converter(value)
        target[key] = parsed
    except (TypeError, ValueError) as exc:
        raise EdgeConfigError(f"Invalid value for {name}.") from exc


def _path(base: Path, value: object, field_name: str) -> Path | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise EdgeConfigError(f"{field_name} must be a path string.")
    result = Path(value).expanduser()
    return (base / result).resolve() if not result.is_absolute() else result.resolve()


def _optional_float(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    try:
        result = float(cast(str | int | float, value))
    except (TypeError, ValueError) as exc:
        raise EdgeConfigError(f"{field_name} must be a number or null.") from exc
    if not math.isfinite(result):
        raise EdgeConfigError(f"{field_name} must be finite.")
    return result


def _positive_number(
    value: object, field_name: str, *, allow_zero: bool = False
) -> float:
    try:
        result = float(cast(str | int | float, value))
    except (TypeError, ValueError) as exc:
        raise EdgeConfigError(f"{field_name} must be numeric.") from exc
    if not math.isfinite(result) or (result < 0 if allow_zero else result <= 0):
        raise EdgeConfigError(f"{field_name} must be positive.")
    return result


def _boolean(data: Mapping[str, object], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    raise EdgeConfigError(f"{key} must be a boolean.")


def _integer(
    data: Mapping[str, object], key: str, default: int, *, minimum: int = 1
) -> int:
    raw = data.get(key, default)
    try:
        result = int(cast(str | int, raw))
    except (TypeError, ValueError) as exc:
        raise EdgeConfigError(f"{key} must be an integer.") from exc
    if result < minimum:
        raise EdgeConfigError(f"{key} must be at least {minimum}.")
    return result


def load_config(
    path: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> EdgeConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise EdgeConfigError(f"Configuration file does not exist: {config_path}")
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise EdgeConfigError("Could not read the YAML configuration file.") from exc
    data = _mapping(loaded, "configuration")
    variables = os.environ if environ is None else environ
    for name, (section, key, _) in _ENVIRONMENT_OVERRIDES.items():
        if name in variables and variables[name] != "":
            _set_override(data, name, variables[name], section=section, key=key)

    base = config_path.parent
    api_raw = _mapping(data.get("api"), "api")
    camera_raw = _mapping(data.get("camera"), "camera")
    models_raw = _mapping(data.get("models"), "models")
    quality_raw = _mapping(data.get("quality"), "quality")
    recognition_raw = _mapping(data.get("recognition"), "recognition")
    liveness_raw = _mapping(data.get("liveness"), "liveness")
    runtime_raw = _mapping(data.get("runtime"), "runtime")
    central_ai_raw = _mapping(data.get("central_ai"), "central_ai")
    gateway_raw = _mapping(data.get("gateway"), "gateway")
    preview_raw = _mapping(data.get("preview"), "preview")

    mode = str(data.get("mode", "AI_EDGE")).upper()
    if mode not in {"AI_EDGE", "STB_GATEWAY"}:
        raise EdgeConfigError("mode must be AI_EDGE or STB_GATEWAY.")

    raw_device_id = data.get("device_id")
    try:
        device_id = UUID(str(raw_device_id)) if raw_device_id else None
    except ValueError as exc:
        raise EdgeConfigError("device_id must be a UUID.") from exc

    api_base_url = str(api_raw.get("base_url", "http://127.0.0.1:8000")).rstrip("/")
    cache_path = str(
        api_raw.get(
            "cache_path",
            "/api/v1/devices/{device_id}/active-session-cache",
        )
    )
    if not cache_path.startswith("/api/v1/") or "{device_id}" not in cache_path:
        raise EdgeConfigError(
            "api.cache_path must be a /api/v1 path containing {device_id}."
        )
    api = ApiSettings(
        base_url=api_base_url,
        timeout_seconds=_positive_number(
            api_raw.get("timeout_seconds", 4), "api.timeout_seconds"
        ),
        heartbeat_interval_seconds=_positive_number(
            api_raw.get("heartbeat_interval_seconds", 15),
            "api.heartbeat_interval_seconds",
        ),
        cache_refresh_seconds=_positive_number(
            api_raw.get("cache_refresh_seconds", 3), "api.cache_refresh_seconds"
        ),
        cache_path=cache_path,
        token_file=_path(base, api_raw.get("token_file"), "api.token_file"),
        cache_max_offline_seconds=_positive_number(
            api_raw.get("cache_max_offline_seconds", 300),
            "api.cache_max_offline_seconds",
        ),
    )
    if api.cache_max_offline_seconds > 86400:
        raise EdgeConfigError("api.cache_max_offline_seconds must not exceed 86400.")

    central_ai = CentralAISettings(
        base_url=str(central_ai_raw.get("base_url", "http://127.0.0.1:8001")).rstrip(
            "/"
        ),
        token_file=_path(
            base, central_ai_raw.get("token_file"), "central_ai.token_file"
        ),
        timeout_seconds=_positive_number(
            central_ai_raw.get("timeout_seconds", 8), "central_ai.timeout_seconds"
        ),
    )

    camera_index_raw = camera_raw.get("index", 0)
    try:
        camera_index = int(cast(str | int, camera_index_raw))
    except (TypeError, ValueError) as exc:
        raise EdgeConfigError("camera.index must be an integer.") from exc
    if camera_index < 0:
        raise EdgeConfigError("camera.index must not be negative.")
    camera = CameraSettings(
        index=camera_index,
        width=_integer(camera_raw, "width", 1920),
        height=_integer(camera_raw, "height", 1080),
        fps=_integer(camera_raw, "fps", 30),
        backend=str(camera_raw.get("backend", "auto")).lower(),
        scan_max_index=_integer(camera_raw, "scan_max_index", 8, minimum=0),
        reconnect_seconds=_positive_number(
            camera_raw.get("reconnect_seconds", 2), "camera.reconnect_seconds"
        ),
    )
    if camera.backend not in {"auto", "dshow", "msmf", "v4l2"}:
        raise EdgeConfigError("camera.backend must be auto, dshow, msmf, or v4l2.")

    raw_session_id = gateway_raw.get("session_id")
    try:
        session_id = UUID(str(raw_session_id)) if raw_session_id else None
    except ValueError as exc:
        raise EdgeConfigError("gateway.session_id must be a UUID.") from exc

    def _aware_datetime(key: str) -> datetime | None:
        raw = gateway_raw.get(key)
        if raw in (None, ""):
            return None
        if not isinstance(raw, str):
            raise EdgeConfigError(f"gateway.{key} must be an ISO datetime string.")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise EdgeConfigError(
                f"gateway.{key} must be an ISO datetime string."
            ) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise EdgeConfigError(f"gateway.{key} must include a timezone.")
        return parsed.astimezone(UTC)

    gateway = GatewaySettings(
        session_id=session_id,
        session_starts_at=_aware_datetime("session_starts_at"),
        session_ends_at=_aware_datetime("session_ends_at"),
        motion_threshold=_positive_number(
            gateway_raw.get("motion_threshold", 7),
            "gateway.motion_threshold",
            allow_zero=True,
        ),
        periodic_burst_seconds=_positive_number(
            gateway_raw.get("periodic_burst_seconds", 30),
            "gateway.periodic_burst_seconds",
        ),
        minimum_burst_interval_seconds=_positive_number(
            gateway_raw.get("minimum_burst_interval_seconds", 5),
            "gateway.minimum_burst_interval_seconds",
        ),
        burst_frame_count=_integer(gateway_raw, "burst_frame_count", 3),
        burst_frame_interval_seconds=_positive_number(
            gateway_raw.get("burst_frame_interval_seconds", 0.2),
            "gateway.burst_frame_interval_seconds",
        ),
        jpeg_quality=_integer(gateway_raw, "jpeg_quality", 75),
        min_brightness=_positive_number(
            gateway_raw.get("min_brightness", 20),
            "gateway.min_brightness",
            allow_zero=True,
        ),
        max_brightness=_positive_number(
            gateway_raw.get("max_brightness", 240), "gateway.max_brightness"
        ),
        min_sharpness=_positive_number(
            gateway_raw.get("min_sharpness", 8),
            "gateway.min_sharpness",
            allow_zero=True,
        ),
    )
    if gateway.burst_frame_count > 5:
        raise EdgeConfigError("gateway.burst_frame_count must not exceed 5.")
    if gateway.jpeg_quality > 100:
        raise EdgeConfigError("gateway.jpeg_quality must not exceed 100.")
    if gateway.min_brightness >= gateway.max_brightness:
        raise EdgeConfigError("gateway.min_brightness must be below max_brightness.")

    preview_host = str(preview_raw.get("bind_host", "127.0.0.1"))
    try:
        parsed_host = ipaddress.ip_address(preview_host)
    except ValueError as exc:
        raise EdgeConfigError(
            "preview.bind_host must be a loopback IP address."
        ) from exc
    if not parsed_host.is_loopback:
        raise EdgeConfigError("preview.bind_host must be a loopback IP address.")
    origins_raw = preview_raw.get(
        "allowed_origins",
        ["http://127.0.0.1:5173", "http://localhost:5173"],
    )
    if not isinstance(origins_raw, list) or not origins_raw:
        raise EdgeConfigError("preview.allowed_origins must be a non-empty list.")
    allowed_origins: list[str] = []
    for origin in origins_raw:
        if not isinstance(origin, str):
            raise EdgeConfigError("preview.allowed_origins entries must be URLs.")
        parsed_origin = urlsplit(origin)
        if (
            parsed_origin.scheme not in {"http", "https"}
            or parsed_origin.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed_origin.path
            or parsed_origin.query
            or parsed_origin.fragment
            or parsed_origin.username
            or parsed_origin.password
        ):
            raise EdgeConfigError(
                "preview.allowed_origins may contain only exact localhost origins."
            )
        normalized = f"{parsed_origin.scheme}://{parsed_origin.netloc}"
        if normalized != origin.rstrip("/"):
            raise EdgeConfigError("preview.allowed_origins must be canonical origins.")
        allowed_origins.append(normalized)
    preview = PreviewSettings(
        enabled=_boolean(preview_raw, "enabled", mode == "AI_EDGE"),
        bind_host=preview_host,
        port=_integer(preview_raw, "port", 8765),
        allowed_origins=tuple(allowed_origins),
        max_width=_integer(preview_raw, "max_width", 640, minimum=160),
        jpeg_quality=_integer(preview_raw, "jpeg_quality", 70),
    )
    if preview.port > 65535 or preview.jpeg_quality > 95:
        raise EdgeConfigError("preview.port or preview.jpeg_quality is out of range.")

    models = ModelSettings(
        yunet_path=_path(base, models_raw.get("yunet_path"), "models.yunet_path"),
        sface_path=_path(base, models_raw.get("sface_path"), "models.sface_path"),
        version=str(models_raw.get("version", "")),
        liveness_path=_path(
            base, models_raw.get("liveness_path"), "models.liveness_path"
        ),
        liveness_version=(
            str(models_raw["liveness_version"])
            if models_raw.get("liveness_version")
            else None
        ),
    )
    quality = QualitySettings(
        min_face_pixels=_integer(quality_raw, "min_face_pixels", 80),
        min_laplacian_variance=_positive_number(
            quality_raw.get("min_laplacian_variance", 45),
            "quality.min_laplacian_variance",
            allow_zero=True,
        ),
        min_brightness=_positive_number(
            quality_raw.get("min_brightness", 25),
            "quality.min_brightness",
            allow_zero=True,
        ),
        max_brightness=_positive_number(
            quality_raw.get("max_brightness", 235),
            "quality.max_brightness",
        ),
    )
    if quality.min_brightness >= quality.max_brightness:
        raise EdgeConfigError("quality.min_brightness must be below max_brightness.")

    minimum_frames = _integer(recognition_raw, "minimum_agreeing_frames", 3)
    best_frames = _integer(recognition_raw, "best_frame_count", minimum_frames)
    history_frames = _integer(
        recognition_raw, "max_history_frames", max(10, best_frames)
    )
    recognition = RecognitionSettings(
        min_top1_similarity=_optional_float(
            recognition_raw.get("min_top1_similarity"),
            "recognition.min_top1_similarity",
        ),
        min_top1_top2_margin=_optional_float(
            recognition_raw.get("min_top1_top2_margin"),
            "recognition.min_top1_top2_margin",
        ),
        minimum_agreeing_frames=minimum_frames,
        sample_every_n_frames=_integer(recognition_raw, "sample_every_n_frames", 5),
        best_frame_count=best_frames,
        max_history_frames=history_frames,
        track_ttl_seconds=_positive_number(
            recognition_raw.get("track_ttl_seconds", 3),
            "recognition.track_ttl_seconds",
        ),
    )
    if best_frames < minimum_frames or history_frames < best_frames:
        raise EdgeConfigError(
            "Recognition frame history must cover agreeing and best-frame counts."
        )
    if recognition.min_top1_similarity is not None and not (
        -1 <= recognition.min_top1_similarity <= 1
    ):
        raise EdgeConfigError("recognition.min_top1_similarity must be in [-1, 1].")
    if recognition.min_top1_top2_margin is not None and not (
        0 <= recognition.min_top1_top2_margin <= 2
    ):
        raise EdgeConfigError("recognition.min_top1_top2_margin must be in [0, 2].")
    liveness = LivenessSettings(
        enabled=_boolean(liveness_raw, "enabled", False),
        required=_boolean(liveness_raw, "required", False),
        min_live_score=_optional_float(
            liveness_raw.get("min_live_score"), "liveness.min_live_score"
        ),
    )
    if liveness.required and not liveness.enabled:
        raise EdgeConfigError("Required liveness must be enabled.")
    if liveness.min_live_score is not None and not 0 <= liveness.min_live_score <= 1:
        raise EdgeConfigError("liveness.min_live_score must be in [0, 1].")
    runtime = RuntimeSettings(
        outbox_path=(
            _path(
                base,
                runtime_raw.get("outbox_path", "data/camera-queue/edge-events.sqlite3"),
                "runtime.outbox_path",
            )
            or base / "data/camera-queue/edge-events.sqlite3"
        ),
        max_outbox_events=_integer(runtime_raw, "max_outbox_events", 50000),
        max_retry_seconds=_positive_number(
            runtime_raw.get("max_retry_seconds", 60), "runtime.max_retry_seconds"
        ),
        log_level=str(runtime_raw.get("log_level", "INFO")).upper(),
    )
    if runtime.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise EdgeConfigError(
            "runtime.log_level must be DEBUG, INFO, WARNING, or ERROR."
        )

    return EdgeConfig(
        config_path=config_path,
        mode=mode,
        device_id=device_id,
        api=api,
        central_ai=central_ai,
        camera=camera,
        models=models,
        quality=quality,
        recognition=recognition,
        liveness=liveness,
        runtime=runtime,
        gateway=gateway,
        preview=preview,
    )


def resolve_api_token(
    config: EdgeConfig, *, environ: Mapping[str, str] | None = None
) -> str | None:
    variables = os.environ if environ is None else environ
    env_token = variables.get("PRESENSI_EDGE_API_TOKEN", "").strip()
    if env_token:
        return env_token
    if config.api.token_file is None:
        return None
    try:
        token = config.api.token_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def resolve_ai_token(
    config: EdgeConfig, *, environ: Mapping[str, str] | None = None
) -> str | None:
    variables = os.environ if environ is None else environ
    env_token = variables.get("PRESENSI_EDGE_AI_TOKEN", "").strip()
    if env_token:
        return env_token
    if config.central_ai.token_file is None:
        return resolve_api_token(config, environ=variables)
    try:
        token = config.central_ai.token_file.read_text(encoding="utf-8").strip()
    except OSError:
        return resolve_api_token(config, environ=variables)
    return token or resolve_api_token(config, environ=variables)
