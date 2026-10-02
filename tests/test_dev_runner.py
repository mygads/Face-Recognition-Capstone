from __future__ import annotations

import importlib.util
from pathlib import Path

from pytest import MonkeyPatch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dev.py"
SPEC = importlib.util.spec_from_file_location("presensi_dev_runner", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
dev_runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dev_runner)


def test_dev_up_runs_migrations_roles_and_bootstrap_after_compose(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(dev_runner, "ensure_env_file", lambda: None)
    monkeypatch.setattr(dev_runner, "run", lambda command: calls.append(command) or 0)
    monkeypatch.setattr("sys.argv", ["scripts/dev.py", "dev-up"])

    assert dev_runner.main() == 0
    assert calls[0] == ["docker", "compose", "up", "--build", "--detach"]
    assert calls[1] == [
        "docker",
        "compose",
        "run",
        "--rm",
        "api",
        "alembic",
        "upgrade",
        "head",
    ]
    assert calls[2][-1] == "presensi_api.db.seed_roles"
    assert calls[3][-1] == "presensi_api.auth.bootstrap_admin"
