from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

from recognition_core import cli
from recognition_core.domain import BoundingBox, FaceDetection, FaceEmbedding


class FakeDetector:
    def detect(self, _frame: object) -> tuple[FaceDetection, ...]:
        return (
            FaceDetection(
                BoundingBox(0, 0, 10, 10),
                1.0,
                ((1, 1), (2, 1), (1.5, 2), (1, 3), (2, 3)),
            ),
        )


class FakeRecognizer:
    model_name = "synthetic-sface"
    model_version = "fixture-v1"

    def align(self, frame: object, _detection: FaceDetection) -> object:
        return frame

    def embed(self, face: object) -> FaceEmbedding:
        sample = bytes(face).decode("ascii")
        values = (1.0, 0.0) if sample.startswith("same") else (0.0, 1.0)
        return FaceEmbedding(values, self.model_name, self.model_version, True)


def _patch_models(monkeypatch: object) -> None:
    monkeypatch.setattr(
        cli, "_build_models", lambda _args: (FakeDetector(), FakeRecognizer())
    )
    monkeypatch.setattr(
        cli, "read_color_image", lambda path: Path(path).stem.encode("ascii")
    )


def _synthetic_png() -> bytes:
    """Return a valid 1x1 generated color swatch; it contains no person/face."""

    def chunk(kind: bytes, content: bytes) -> bytes:
        payload = kind + content
        return (
            struct.pack(">I", len(content))
            + payload
            + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
        )

    scanline = b"\x00\x36\x78\x90"
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanline))
        + chunk(b"IEND", b"")
    )


def test_compare_cli_reports_score_and_only_applies_explicit_threshold(
    monkeypatch: object, tmp_path: Path, capsys: object
) -> None:
    _patch_models(monkeypatch)
    first = tmp_path / "same-a.png"
    second = tmp_path / "same-b.png"
    first.write_bytes(_synthetic_png())
    second.write_bytes(_synthetic_png())

    result = cli.main(
        [
            "compare",
            str(first),
            str(second),
            "--yunet-model",
            "configured-yunet.onnx",
            "--sface-model",
            "configured-sface.onnx",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["cosine_similarity"] == 1.0
    assert payload["configured_threshold"] is None
    assert payload["passes_configured_threshold"] is None
    assert "embedding" not in payload


def test_benchmark_cli_uses_identity_subfolders_and_outputs_aggregate_only(
    monkeypatch: object, tmp_path: Path, capsys: object
) -> None:
    _patch_models(monkeypatch)
    benchmark = tmp_path / "benchmark"
    for identity, images in {
        "synthetic-a": {"same-a.png", "same-b.png"},
        "synthetic-b": {"other-a.png"},
    }.items():
        identity_folder = benchmark / identity
        identity_folder.mkdir(parents=True)
        for filename in images:
            (identity_folder / filename).write_bytes(_synthetic_png())

    result = cli.main(
        [
            "benchmark",
            str(benchmark),
            "--yunet-model",
            "configured-yunet.onnx",
            "--sface-model",
            "configured-sface.onnx",
            "--threshold",
            "0.8",
        ]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert result == 0
    assert payload["identity_group_count"] == 2
    assert payload["same_identity_pairs"]["pair_count"] == 1
    assert (
        payload["same_identity_pairs"]["acceptance_rate_at_configured_threshold"] == 1
    )
    assert payload["different_identity_pairs"]["pair_count"] == 2
    assert "synthetic-a" not in output
    assert "embedding" not in output
