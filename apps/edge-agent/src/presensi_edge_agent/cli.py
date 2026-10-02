from __future__ import annotations

import argparse
import json
import logging
import os
import signal
from pathlib import Path
from types import FrameType
from typing import Sequence
from uuid import UUID

from presensi_edge_agent import __version__
from presensi_edge_agent.api import CoreApiClient
from presensi_edge_agent.camera import (
    CameraUnavailableError,
    OpenCVCamera,
    enumerate_cameras,
)
from presensi_edge_agent.central_ai import CentralAIClient
from presensi_edge_agent.config import (
    EdgeConfig,
    EdgeConfigError,
    load_config,
    resolve_ai_token,
    resolve_api_token,
)
from presensi_edge_agent.gateway import OpenCVFrameProcessor, StbGatewayService
from presensi_edge_agent.logging import configure_logging, log_event
from presensi_edge_agent.outbox import EventOutbox

DEFAULT_CONFIG = Path("apps/edge-agent/config/edge-agent.yaml")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="presensi-edge-agent")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(os.environ.get("PRESENSI_EDGE_CONFIG", str(DEFAULT_CONFIG))),
        help="YAML config file (default: apps/edge-agent/config/edge-agent.yaml)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("cameras", help="Enumerate accessible UVC camera indices")
    commands.add_parser(
        "configure-camera",
        help="Interactively select and save camera index, resolution and FPS",
    )
    commands.add_parser("health", help="Check Core API process health")
    commands.add_parser("status", help="Report config, camera and API status")
    commands.add_parser("run", help="Run the AI_EDGE camera service")
    return parser


def _api_client(config: EdgeConfig) -> CoreApiClient:
    return CoreApiClient(
        config.api,
        config.device_id or UUID(int=0),
        lambda: resolve_api_token(config),
        heartbeat_metadata={
            "deployment_profile": config.mode,
            "app_version": __version__,
            **(
                {"model_version": config.models.version}
                if config.models.version
                else {}
            ),
        },
    )


def _write_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _camera_indices(config: EdgeConfig) -> list[int]:
    return [
        camera.index
        for camera in enumerate_cameras(
            config.camera.scan_max_index,
            backend=config.camera.backend,
        )
    ]


def _diagnostics(config: EdgeConfig, *, include_cameras: bool) -> int:
    api = _api_client(config)
    try:
        health = api.health()
    finally:
        api.close()
    cameras: list[int] | None = None
    camera_error: str | None = None
    if include_cameras:
        try:
            cameras = _camera_indices(config)
        except CameraUnavailableError as exc:
            camera_error = str(exc)
            cameras = []
    token = resolve_api_token(config)
    ai_token = resolve_ai_token(config)
    try:
        config.require_runtime(api_token=token, ai_token=ai_token)
        runtime_ready = True
        configuration_error = None
    except EdgeConfigError as exc:
        runtime_ready = False
        configuration_error = str(exc)
    selected_camera_available = (
        None if cameras is None else config.camera.index in cameras
    )
    # Core API exposes this device-authenticated route and the client has a
    # corresponding fetch method. Actual session/gallery readiness is checked
    # by the running service when a session is active.
    cache_provider_ready = callable(api.fetch_active_session_cache)
    ai_reachable: bool | None = None
    if config.mode == "STB_GATEWAY":
        ai = CentralAIClient(
            config.central_ai,
            config.device_id or UUID(int=0),
            lambda: resolve_ai_token(config),
        )
        try:
            ai_reachable = ai.health()
        finally:
            ai.close()
    agent_ready = (
        runtime_ready
        and cache_provider_ready
        and (config.mode != "STB_GATEWAY" or ai_reachable is True)
        and (not include_cameras or selected_camera_available is True)
    )
    dependencies_reachable = health.reachable and (
        config.mode != "STB_GATEWAY" or ai_reachable is True
    )
    result = {
        "service": "presensi-edge-agent",
        "profile": config.mode,
        "status": (
            "ok"
            if dependencies_reachable and (agent_ready or not include_cameras)
            else "degraded"
        ),
        "api_reachable": health.reachable,
        "api_status_code": health.status_code,
        "central_ai_reachable": ai_reachable,
        "device_id_configured": config.device_id is not None,
        "api_token_configured": bool(token),
        "central_ai_token_configured": bool(ai_token),
        "central_session_gallery_available": False
        if config.mode == "STB_GATEWAY"
        else None,
        "camera_indices": cameras,
        "selected_camera_index": config.camera.index,
        "selected_camera_available": selected_camera_available,
        "camera_error": camera_error,
        "runtime_ready": runtime_ready,
        "configuration_error": configuration_error,
        "cache_endpoint": config.api.cache_path,
        "cache_endpoint_implemented_by_core_api": cache_provider_ready,
    }
    _write_json(result)
    return 0 if dependencies_reachable and (agent_ready or not include_cameras) else 1


def _run_service(config: EdgeConfig) -> int:
    token = resolve_api_token(config)
    ai_token = resolve_ai_token(config)
    config.require_runtime(api_token=token, ai_token=ai_token)
    assert config.device_id is not None
    configure_logging(config.runtime.log_level)
    if config.mode == "STB_GATEWAY":
        client = _api_client(config)
        ai_client = CentralAIClient(
            config.central_ai,
            config.device_id,
            lambda: resolve_ai_token(config),
        )
        outbox = EventOutbox(
            config.runtime.outbox_path,
            max_pending=config.runtime.max_outbox_events,
        )
        gateway_service = StbGatewayService(
            config=config,
            camera=OpenCVCamera(
                config.camera,
                max_frame_size=(config.camera.width, config.camera.height),
            ),
            api=client,
            ai=ai_client,
            outbox=outbox,
            processor=OpenCVFrameProcessor(),
        )

        def request_gateway_stop(_signum: int, _frame: FrameType | None) -> None:
            gateway_service.stop()

        signal.signal(signal.SIGINT, request_gateway_stop)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, request_gateway_stop)
        gateway_service.run()
        return 0

    if config.mode == "AI_EDGE":
        if not config.liveness.enabled:
            log_event(
                logging.getLogger("presensi_edge_agent"),
                logging.WARNING,
                "liveness_disabled_physical_control_required",
            )
        else:
            log_event(
                logging.getLogger("presensi_edge_agent"),
                logging.WARNING,
                "liveness_model_candidate_requires_license_clearance",
                model="anti-spoof-mn3",
            )
    client = _api_client(config)
    outbox = EventOutbox(
        config.runtime.outbox_path,
        max_pending=config.runtime.max_outbox_events,
    )
    from presensi_edge_agent.recognition import LocalRecognizer, build_pipeline
    from presensi_edge_agent.service import EdgeService

    pipeline = build_pipeline(config)
    edge_service = EdgeService(
        config=config,
        camera=OpenCVCamera(config.camera),
        api=client,
        outbox=outbox,
        recognizer=LocalRecognizer(pipeline, config.device_id),
        cache_fetch=client.fetch_active_session_cache,
    )

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        edge_service.stop()

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)
    edge_service.run()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "cameras":
            _write_json({"camera_indices": _camera_indices(config)})
            return 0
        if args.command == "configure-camera":
            from presensi_edge_agent.camera_setup import configure_camera_interactively

            configure_camera_interactively(config)
            return 0
        if args.command == "health":
            return _diagnostics(config, include_cameras=False)
        if args.command == "status":
            return _diagnostics(config, include_cameras=True)
        if args.command == "run":
            return _run_service(config)
    except (EdgeConfigError, CameraUnavailableError, OSError, ValueError) as exc:
        _write_json(
            {
                "service": "presensi-edge-agent",
                "status": "error",
                "error": str(exc),
            }
        )
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
