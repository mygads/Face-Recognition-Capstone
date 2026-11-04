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


def test_yunet_operating_point_is_calibrated_config_with_sane_defaults() -> None:
    defaults = AISettings()
    assert defaults.yunet_score_threshold == 0.9
    assert defaults.yunet_nms_threshold == 0.3
    with pytest.raises(AIServiceConfigError, match="yunet_score_threshold"):
        AISettings(yunet_score_threshold=1.5)
    with pytest.raises(AIServiceConfigError, match="yunet_nms_threshold"):
        AISettings(yunet_nms_threshold=-0.1)


def test_central_default_samples_every_burst_frame() -> None:
    """Central bursts are isolated single tracks: the default stride must be 1.

    The STB gateway mints a fresh track id per burst, so consensus has to be
    reachable inside one burst. A default stride > 1 would silently leave
    every burst in "collecting" (fail-always, no attendance, no error).
    """
    assert AISettings().sample_every_n_frames == 1
    assert AISettings.from_env({}).sample_every_n_frames == 1


def test_unreachable_burst_consensus_fails_fast() -> None:
    # 5-frame bursts with stride 3 evaluate at most ceil(5/3) = 2 frames,
    # so requiring 3 agreeing frames could never accept.
    with pytest.raises(AIServiceConfigError, match="unreachable"):
        AISettings(
            max_frames_per_burst=5,
            minimum_agreeing_frames=3,
            sample_every_n_frames=3,
        )


def test_reachable_burst_consensus_is_accepted() -> None:
    # Borderline but reachable: ceil(5/2) = 3 evaluated frames for 3 required.
    settings = AISettings(
        max_frames_per_burst=5,
        minimum_agreeing_frames=3,
        sample_every_n_frames=2,
    )
    assert settings.sample_every_n_frames == 2
    # Tightening the burst without loosening the minimum must fail fast.
    with pytest.raises(AIServiceConfigError, match="unreachable"):
        AISettings(
            max_frames_per_burst=2,
            minimum_agreeing_frames=3,
            sample_every_n_frames=1,
        )


def test_ai_payload_and_quality_guards_honor_environment() -> None:
    """AI payload/quality env vars must actually move the service guards.

    These nine vars were forwarded nowhere (compose/examples), so operators
    tuned invisible code defaults. Defaults mirror the documented examples.
    """
    defaults = AISettings.from_env({})
    assert defaults.max_request_bytes == 20 * 1024 * 1024
    assert defaults.max_frame_bytes == 3 * 1024 * 1024
    assert defaults.max_image_width == 4096
    assert defaults.max_image_height == 4096
    assert defaults.max_image_pixels == 16_000_000
    assert defaults.min_face_pixels == 80
    assert defaults.min_laplacian_variance == 45.0
    assert defaults.min_brightness == 25.0
    assert defaults.max_brightness == 235.0
    tuned = AISettings.from_env(
        {
            "PRESENSI_AI_MAX_REQUEST_BYTES": "1048576",
            "PRESENSI_AI_MAX_FRAME_BYTES": "524288",
            "PRESENSI_AI_MAX_IMAGE_WIDTH": "1920",
            "PRESENSI_AI_MAX_IMAGE_HEIGHT": "1080",
            "PRESENSI_AI_MAX_IMAGE_PIXELS": "2000000",
            "PRESENSI_AI_MIN_FACE_PIXELS": "100",
            "PRESENSI_AI_MIN_LAPLACIAN_VARIANCE": "50.0",
            "PRESENSI_AI_MIN_BRIGHTNESS": "30.0",
            "PRESENSI_AI_MAX_BRIGHTNESS": "220.0",
        }
    )
    assert tuned.max_request_bytes == 1048576
    assert tuned.max_frame_bytes == 524288
    assert tuned.max_image_width == 1920
    assert tuned.max_image_height == 1080
    assert tuned.max_image_pixels == 2000000
    assert tuned.min_face_pixels == 100
    assert tuned.min_laplacian_variance == 50.0
    assert tuned.min_brightness == 30.0
    assert tuned.max_brightness == 220.0
