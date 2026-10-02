from __future__ import annotations

import importlib.util
from pathlib import Path

from pytest import MonkeyPatch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "start-local.py"
SPEC = importlib.util.spec_from_file_location("presensi_start_local", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
start_local = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(start_local)


class InteractiveInput:
    def isatty(self) -> bool:
        return True


def test_first_start_prompts_and_persists_central_profile(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_example = tmp_path / ".env.example"
    env_example.write_text("POSTGRES_PASSWORD=\n", encoding="utf-8")
    monkeypatch.setattr(start_local, "ENV_FILE", env_file)
    monkeypatch.setattr(start_local, "ENV_EXAMPLE", env_example)
    monkeypatch.setattr(start_local.sys, "stdin", InteractiveInput())
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")

    assert start_local.choose_local_ai_profile(None) == "central"
    assert "POSTGRES_PASSWORD=\n" in env_file.read_text(encoding="utf-8")
    assert start_local.read_local_ai_profile() == "central"


def test_explicit_edge_profile_overwrites_saved_choice(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POSTGRES_PASSWORD=local-secret\nPRESENSI_LOCAL_AI_PROFILE=central\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(start_local, "ENV_FILE", env_file)

    assert start_local.choose_local_ai_profile("edge") == "edge"
    saved_env = env_file.read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD=local-secret" in saved_env
    assert "PRESENSI_LOCAL_AI_PROFILE=edge" in saved_env
    assert "PRESENSI_LOCAL_AI_PROFILE=central" not in saved_env


def test_first_start_can_download_models_and_configures_central_paths(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "PRESENSI_AI_YUNET_MODEL_PATH=\n"
        "PRESENSI_AI_SFACE_MODEL_PATH=\n"
        "PRESENSI_AI_MODEL_VERSION=\n"
        "PRESENSI_AI_MIN_TOP1_SIMILARITY=\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(start_local, "ENV_FILE", env_file)
    monkeypatch.setattr(start_local, "ENV_EXAMPLE", env_example)
    monkeypatch.setattr(start_local, "local_models_are_verified", lambda: False)
    monkeypatch.setattr(start_local, "download_local_models", lambda: True)
    monkeypatch.setattr(start_local.sys, "stdin", InteractiveInput())
    monkeypatch.setattr("builtins.input", lambda _prompt: "1")

    assert start_local.setup_local_models("central", None) is True
    saved_env = env_file.read_text(encoding="utf-8")
    assert "PRESENSI_LOCAL_MODEL_SETUP=downloaded" in saved_env
    assert (
        "PRESENSI_AI_YUNET_MODEL_PATH=/models/face_detection_yunet_2023mar.onnx"
        in saved_env
    )
    assert (
        "PRESENSI_AI_SFACE_MODEL_PATH=/models/face_recognition_sface_2021dec.onnx"
        in saved_env
    )
    assert "PRESENSI_AI_MODEL_VERSION=opencv-zoo-sface-2021dec" in saved_env
    assert "PRESENSI_AI_MIN_TOP1_SIMILARITY=" in saved_env


def test_skipping_model_download_is_persisted(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_example = tmp_path / ".env.example"
    env_example.write_text("PRESENSI_LOCAL_MODEL_SETUP=\n", encoding="utf-8")
    monkeypatch.setattr(start_local, "ENV_FILE", env_file)
    monkeypatch.setattr(start_local, "ENV_EXAMPLE", env_example)
    monkeypatch.setattr(start_local, "local_models_are_verified", lambda: False)
    monkeypatch.setattr(start_local.sys, "stdin", InteractiveInput())
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")

    assert start_local.setup_local_models("edge", None) is False
    assert start_local.read_local_env_setting("PRESENSI_LOCAL_MODEL_SETUP") == "skipped"
