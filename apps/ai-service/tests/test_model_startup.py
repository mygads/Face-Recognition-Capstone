from __future__ import annotations

from pathlib import Path

from presensi_ai_service.config import AISettings
from presensi_ai_service.inference import build_model_runner


def test_configured_models_without_thresholds_keep_service_in_degraded_mode(
    tmp_path: Path,
) -> None:
    yunet_path = tmp_path / "yunet.onnx"
    sface_path = tmp_path / "sface.onnx"
    yunet_path.touch()
    sface_path.touch()
    settings = AISettings(
        yunet_model_path=yunet_path,
        sface_model_path=sface_path,
        model_version="test-model-v1",
    )

    assert build_model_runner(settings) is None
