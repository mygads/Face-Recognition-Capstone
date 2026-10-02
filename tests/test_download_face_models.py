from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

from pytest import MonkeyPatch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "download_face_models.py"
SPEC = importlib.util.spec_from_file_location("presensi_download_face_models", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
download_models = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = download_models
SPEC.loader.exec_module(download_models)


def test_model_check_requires_matching_size_and_checksum(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    payload = b"synthetic model bytes"
    asset = download_models.ModelAsset(
        filename="model.onnx",
        url="https://models.example.test/model.onnx",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )
    monkeypatch.setattr(download_models, "ASSETS", (asset,))

    assert download_models.assets_are_verified(tmp_path) is False
    (tmp_path / asset.filename).write_bytes(payload)
    assert download_models.assets_are_verified(tmp_path) is True
    (tmp_path / asset.filename).write_bytes(b"corrupt")
    assert download_models.assets_are_verified(tmp_path) is False
