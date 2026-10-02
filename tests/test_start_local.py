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
