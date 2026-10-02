from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "apply_device_setup.py"
SPEC = importlib.util.spec_from_file_location("presensi_apply_device_setup", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
device_setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(device_setup)


@pytest.mark.parametrize(
    "url",
    ("http://127.0.0.1:8000", "http://localhost:8001", "https://presensi.internal"),
)
def test_device_setup_accepts_localhost_or_https_origins(url: str) -> None:
    assert device_setup._url(url, "core_api_url", required=True) == url


def test_device_setup_rejects_unencrypted_remote_origin() -> None:
    with pytest.raises(ValueError, match="HTTP\\(S\\) origin"):
        device_setup._url("http://192.168.10.20:8000", "core_api_url", required=True)
