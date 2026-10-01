from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import recognition_core.onnx_liveness as liveness_module
from recognition_core.onnx_liveness import ONNXRuntimeAntiSpoofMN3


class FakeArray:
    def __init__(
        self, shape: tuple[int, ...], values: list[float] | None = None
    ) -> None:
        self.shape = shape
        self.ndim = len(shape)
        self.dtype = "uint8"
        self._values = values or []
        self.size = len(self._values)

    def astype(self, _dtype: object) -> FakeArray:
        return self

    def reshape(self, *shape: Any) -> FakeArray:
        new_shape = (
            shape[0] if len(shape) == 1 and isinstance(shape[0], tuple) else shape
        )
        if new_shape == (-1,):
            new_shape = (len(self._values),)
        return FakeArray(new_shape, self._values)

    def tolist(self) -> list[float]:
        return self._values

    def __getitem__(self, key: object) -> FakeArray:
        del key
        return FakeArray((1, *self.shape), self._values)

    def __sub__(self, _other: FakeArray) -> FakeArray:
        return self

    def __truediv__(self, _other: FakeArray) -> FakeArray:
        return self


class FakeNumpy:
    float32 = "float32"

    @staticmethod
    def asarray(value: Any, dtype: object | None = None) -> FakeArray:
        del dtype
        if isinstance(value, FakeArray):
            return value
        if isinstance(value, (list, tuple)):
            values: list[float] = []

            def flatten(items: list[Any] | tuple[Any, ...]) -> None:
                for item in items:
                    if isinstance(item, (list, tuple)):
                        flatten(item)
                    else:
                        values.append(float(item))

            flatten(value)
            return FakeArray((len(values),), values)
        raise TypeError("Unexpected fake array input")

    @staticmethod
    def transpose(value: FakeArray, axes: tuple[int, ...]) -> FakeArray:
        return FakeArray(tuple(value.shape[index] for index in axes), value._values)


class FakeInferenceSession:
    def __init__(
        self,
        model_path: str,
        *,
        providers: list[str],
        probabilities: list[float],
    ) -> None:
        self.model_path = model_path
        self.providers = providers
        self.probabilities = probabilities
        self.feed: dict[str, Any] | None = None

    def get_inputs(self) -> list[Any]:
        return [type("Node", (), {"name": "data"})()]

    def get_outputs(self) -> list[Any]:
        return [type("Node", (), {"name": "probs"})()]

    def run(
        self,
        output_names: list[str],
        feed: dict[str, Any],
    ) -> list[list[list[float]]]:
        assert output_names == ["probs"]
        self.feed = feed
        return [[self.probabilities]]


class FakeOpenCV:
    COLOR_BGR2RGB = 4

    @staticmethod
    def cvtColor(image: FakeArray, code: int) -> FakeArray:
        assert code == FakeOpenCV.COLOR_BGR2RGB
        return image

    @staticmethod
    def resize(_image: FakeArray, size: tuple[int, int]) -> FakeArray:
        assert size == (128, 128)
        return FakeArray((128, 128, 3))


@pytest.mark.parametrize(
    ("probabilities", "expected_state", "expected_live_score"),
    [([0.9, 0.1], "live", 0.9), ([0.2, 0.8], "spoof", 0.2)],
)
def test_local_anti_spoof_inference_returns_score_without_face_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    probabilities: list[float],
    expected_state: str,
    expected_live_score: float,
) -> None:
    model_path = tmp_path / "anti-spoof-mn3.onnx"
    model_path.write_text("placeholder ONNX model file", encoding="utf-8")
    sessions: list[FakeInferenceSession] = []

    def load_session_factory() -> Any:
        def create_session(path: str, *, providers: list[str]) -> FakeInferenceSession:
            session = FakeInferenceSession(
                path,
                providers=providers,
                probabilities=probabilities,
            )
            sessions.append(session)
            return session

        return create_session

    monkeypatch.setattr(
        liveness_module,
        "_load_inference_session",
        load_session_factory,
    )
    monkeypatch.setattr(liveness_module, "_load_cv2", lambda: FakeOpenCV())
    monkeypatch.setattr(liveness_module, "_load_numpy", lambda: FakeNumpy())

    model = ONNXRuntimeAntiSpoofMN3(
        model_path,
        model_version="local-test",
    )
    decision = model.evaluate(FakeArray((112, 112, 3)))
    session = sessions[0]

    assert session.model_path == str(model_path)
    assert session.providers == ["CPUExecutionProvider"]
    assert decision.state == expected_state
    assert decision.live_score == pytest.approx(expected_live_score)
    assert session.feed is not None
    assert session.feed["data"].shape == (1, 3, 128, 128)


def test_adapter_rejects_invalid_probability_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_path = tmp_path / "anti-spoof-mn3.onnx"
    model_path.write_text("placeholder ONNX model file", encoding="utf-8")
    sessions: list[FakeInferenceSession] = []

    def load_session_factory() -> Any:
        def create_session(path: str, *, providers: list[str]) -> FakeInferenceSession:
            session = FakeInferenceSession(
                path,
                providers=providers,
                probabilities=[1.2, -0.2],
            )
            sessions.append(session)
            return session

        return create_session

    monkeypatch.setattr(
        liveness_module,
        "_load_inference_session",
        load_session_factory,
    )
    monkeypatch.setattr(liveness_module, "_load_cv2", lambda: FakeOpenCV())
    monkeypatch.setattr(liveness_module, "_load_numpy", lambda: FakeNumpy())
    model = ONNXRuntimeAntiSpoofMN3(model_path, model_version="local-test")

    with pytest.raises(ValueError, match="invalid class probabilities"):
        model.evaluate(FakeArray((112, 112, 3)))
