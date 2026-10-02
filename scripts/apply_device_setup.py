from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_TEMPLATES = {
    "AI_EDGE": ROOT / "apps" / "edge-agent" / "config" / "edge-agent.example.yaml",
    "STB_GATEWAY": ROOT / "apps" / "edge-agent" / "config" / "stb-gateway.example.yaml",
}


def _url(value: object, field: str, *, required: bool) -> str | None:
    if value is None or value == "":
        if required:
            raise ValueError(f"{field} is required in the device setup bundle.")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a URL string.")
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            f"{field} must be an HTTP(S) origin, such as https://server.school.edu."
        )
    return f"{parsed.scheme}://{parsed.netloc}"


def _read_bundle(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Could not read the device setup bundle JSON.") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("Unsupported device setup bundle format.")
    try:
        value["device_id"] = str(uuid.UUID(str(value.get("device_id"))))
    except ValueError as exc:
        raise ValueError("The bundle does not contain a valid device UUID.") from exc
    if value.get("deployment_profile") not in CONFIG_TEMPLATES:
        raise ValueError(
            "The bundle deployment profile must be AI_EDGE or STB_GATEWAY."
        )
    token = value.get("token")
    if not isinstance(token, str) or len(token) < 40 or not token.isascii():
        raise ValueError("The bundle does not contain a valid device credential.")
    value["core_api_url"] = _url(
        value.get("core_api_url"), "core_api_url", required=True
    )
    value["central_ai_url"] = _url(
        value.get("central_ai_url"),
        "central_ai_url",
        required=value["deployment_profile"] == "STB_GATEWAY",
    )
    return value


def _write_token(path: Path, token: str, *, replace: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        current = path.read_text(encoding="ascii").strip()
        if current == token:
            return
        if not replace:
            raise FileExistsError(
                "A different token file already exists. Confirm replacement "
                "before retrying."
            )
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as token_file:
        token_file.write(token + "\n")
    if os.name != "nt":
        path.chmod(0o600)


def _configure(
    bundle: dict[str, Any], config_path: Path, token_path: Path, state_dir: Path
) -> None:
    profile = bundle["deployment_profile"]
    template_path = CONFIG_TEMPLATES[profile]
    config_path.parent.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    try:
        config = yaml.safe_load(template_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(
            "Could not load the checked-in edge-agent config template."
        ) from exc
    if not isinstance(config, dict):
        raise ValueError("The edge-agent config template is invalid.")

    config["mode"] = profile
    config["device_id"] = bundle["device_id"]
    api = config.setdefault("api", {})
    api["base_url"] = bundle["core_api_url"]
    api["token_file"] = str(token_path.resolve())
    runtime = config.setdefault("runtime", {})
    runtime["outbox_path"] = str((state_dir / "edge-events.sqlite3").resolve())

    camera = config.setdefault("camera", {})
    camera["backend"] = "auto" if os.name == "nt" else "v4l2"

    if profile == "AI_EDGE":
        models = config.setdefault("models", {})
        models["yunet_path"] = str(
            (
                ROOT / "models" / "weights" / "face_detection_yunet_2023mar.onnx"
            ).resolve()
        )
        models["sface_path"] = str(
            (
                ROOT / "models" / "weights" / "face_recognition_sface_2021dec.onnx"
            ).resolve()
        )
        requested_model_version = bundle.get("model_version")
        if requested_model_version:
            if (
                not isinstance(requested_model_version, str)
                or len(requested_model_version) > 128
            ):
                raise ValueError("model_version in the setup bundle is invalid.")
            models["version"] = requested_model_version
    else:
        central_ai = config.setdefault("central_ai", {})
        central_ai["base_url"] = bundle["central_ai_url"]
        central_ai["token_file"] = str(token_path.resolve())
        runtime["outbox_path"] = str((state_dir / "edge-events.sqlite3").resolve())

    config_path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply a one-time Presensi device setup bundle."
    )
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--replace-token", action="store_true")
    args = parser.parse_args()

    try:
        bundle = _read_bundle(args.bundle.expanduser().resolve())
        profile = bundle["deployment_profile"]
        expected_config_name = (
            "edge-agent.yaml" if profile == "AI_EDGE" else "stb-gateway.yaml"
        )
        if args.config.name != expected_config_name:
            raise ValueError(
                f"{profile} setup expects config file {expected_config_name}."
            )
        _write_token(
            args.token_file.expanduser().resolve(),
            bundle["token"],
            replace=args.replace_token,
        )
        _configure(
            bundle,
            args.config.expanduser().resolve(),
            args.token_file.expanduser().resolve(),
            args.state_dir.expanduser().resolve(),
        )
    except (FileExistsError, OSError, ValueError) as exc:
        print(f"Device setup failed: {exc}", file=sys.stderr)
        return 2

    print(
        f"Configured device {bundle['device_id']} for {bundle['deployment_profile']}."
    )
    print(f"Core API: {bundle['core_api_url']}")
    if profile == "STB_GATEWAY":
        print(f"Central AI: {bundle['central_ai_url']}")
    if profile == "AI_EDGE":
        print(
            "AI_EDGE still requires local YuNet/SFace files and calibrated "
            "recognition thresholds."
        )
    print(
        "The setup bundle contains a device secret. Remove it from Downloads "
        "after setup."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
