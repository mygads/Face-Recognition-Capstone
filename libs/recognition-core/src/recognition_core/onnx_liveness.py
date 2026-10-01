"""Optional ONNX Runtime adapter for the anti-spoof-mn3 ONNX artifact."""

from __future__ import annotations

import importlib
import math
from pathlib import Path
from typing import Any, cast

from recognition_core.domain import LivenessDecision
from recognition_core.opencv_models import (
    _load_cv2,
    _load_numpy,
    _required_model_path,
)
from recognition_core.protocols import AlignedFace


class ONNXRuntimeUnavailableError(RuntimeError):
    """Raised when the optional ONNX Runtime inference dependency is missing."""


def _load_inference_session() -> Any:
    try:
        onnxruntime = importlib.import_module("onnxruntime")
    except ImportError as error:
        raise ONNXRuntimeUnavailableError(
            "ONNX Runtime is required for anti-spoof-mn3. Install "
            "libs/recognition-core[antispoof]."
        ) from error
    return onnxruntime.InferenceSession


class ONNXRuntimeAntiSpoofMN3:
    """Run locally provisioned anti-spoof-mn3 ONNX weights; no downloads occur.

    The model expects an RGB 128x128 NCHW tensor normalized with the published
    per-channel mean/scale and returns class probabilities in ``[live, spoof]``
    order.
    """

    model_name = "open-model-zoo-anti-spoof-mn3"
    _mean = (151.2405, 119.5950, 107.8395)
    _scale = (63.0105, 56.4570, 55.0035)

    def __init__(
        self,
        model_path: str | Path,
        *,
        model_version: str,
        providers: tuple[str, ...] = ("CPUExecutionProvider",),
    ) -> None:
        path = _required_model_path(model_path)
        if path.suffix.lower() != ".onnx":
            raise ValueError("anti-spoof-mn3 requires a local ONNX model path.")
        if not model_version.strip():
            raise ValueError("model_version is required.")
        if not providers or any(not provider.strip() for provider in providers):
            raise ValueError(
                "At least one ONNX Runtime execution provider is required."
            )

        self.model_version = model_version
        self._cv2 = _load_cv2()
        self._numpy = _load_numpy()
        inference_session = _load_inference_session()
        self._session = inference_session(str(path), providers=list(providers))
        inputs = self._session.get_inputs()
        outputs = self._session.get_outputs()
        if not inputs or not outputs:
            raise ValueError(
                "anti-spoof-mn3 ONNX model needs input and output tensors."
            )
        self._input_name = inputs[0].name
        self._output_name = outputs[0].name

    def evaluate(self, face: AlignedFace) -> LivenessDecision:
        image = self._numpy.asarray(cast(Any, face))
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("Aligned anti-spoof input must be a color HxWx3 image.")
        rgb = self._cv2.cvtColor(image, self._cv2.COLOR_BGR2RGB)
        resized = self._cv2.resize(rgb, (128, 128))
        pixels = self._numpy.asarray(resized, dtype=self._numpy.float32)
        mean = self._numpy.asarray(self._mean, dtype=self._numpy.float32).reshape(
            (1, 1, 3)
        )
        scale = self._numpy.asarray(self._scale, dtype=self._numpy.float32).reshape(
            (1, 1, 3)
        )
        normalized = (pixels - mean) / scale
        tensor = self._numpy.transpose(normalized, (2, 0, 1))[None, ...]
        output = self._session.run([self._output_name], {self._input_name: tensor})[0]
        probabilities = self._numpy.asarray(output).reshape(-1)
        if probabilities.size != 2:
            raise ValueError("anti-spoof-mn3 must return [live, spoof] probabilities.")
        live_score, spoof_score = (float(value) for value in probabilities.tolist())
        if not all(
            math.isfinite(value) and 0 <= value <= 1
            for value in (live_score, spoof_score)
        ):
            raise ValueError("anti-spoof-mn3 returned invalid class probabilities.")
        return LivenessDecision(
            state="live" if live_score >= spoof_score else "spoof",
            live_score=live_score,
        )
