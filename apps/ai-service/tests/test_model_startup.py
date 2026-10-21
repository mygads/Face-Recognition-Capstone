from __future__ import annotations

from pathlib import Path

import pytest

from presensi_ai_service.config import AIServiceConfigError, AISettings
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


def test_ai_thresholds_must_be_configured_as_a_pair() -> None:
    with pytest.raises(AIServiceConfigError, match="together"):
        AISettings(min_top1_similarity=0.7)
    with pytest.raises(AIServiceConfigError, match="together"):
        AISettings(min_top1_top2_margin=0.1)
    paired = AISettings(min_top1_similarity=0.7, min_top1_top2_margin=0.1)
    assert paired.min_top1_similarity == 0.7
    assert paired.min_top1_top2_margin == 0.1
