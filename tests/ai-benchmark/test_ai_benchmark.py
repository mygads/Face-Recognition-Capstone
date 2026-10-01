from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from ai_benchmark import (
    EmbeddedItem,
    ManifestItem,
    _write_pair_csv,
    _write_threshold_csv,
    build_report,
    load_manifest,
    make_threshold_grid,
    run_embeddings,
)

from recognition_core.domain import FaceEmbedding


def _embedding(values: tuple[float, ...]) -> FaceEmbedding:
    return FaceEmbedding(
        values=values,
        model_name="synthetic-fixture",
        model_version="unit-test-v1",
        normalized=True,
    )


def test_manifest_resolves_local_paths_and_requires_columns(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    for name in ("a.png", "b.png"):
        (images / name).write_bytes(b"synthetic metadata fixture; not an image")
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "path,person_id,condition\nimages/a.png,person-a,frontal\n"
        "images/b.png,person-b,side\n",
        encoding="utf-8",
    )

    rows, digest = load_manifest(manifest)

    assert [row.path for row in rows] == [
        (images / "a.png").resolve(),
        (images / "b.png").resolve(),
    ]
    assert [row.condition for row in rows] == ["frontal", "side"]
    assert len(digest) == 64

    manifest.write_text("path,person_id\na.png,person-a\n", encoding="utf-8")
    with pytest.raises(ValueError, match="condition columns"):
        load_manifest(manifest)


def test_manifest_rejects_duplicate_image_path(tmp_path: Path) -> None:
    image = tmp_path / "one.png"
    image.write_bytes(b"synthetic placeholder")
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "path,person_id,condition\none.png,person-a,frontal\none.png,person-b,side\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="repeats an image path"):
        load_manifest(manifest)


def test_pair_metrics_are_reported_for_many_thresholds_with_low_fmr_constraint() -> (
    None
):
    paths = [Path(f"synthetic-{index}.png") for index in range(4)]
    manifest = [
        ManifestItem(paths[0], "person-a", "frontal", 2),
        ManifestItem(paths[1], "person-a", "low-light", 3),
        ManifestItem(paths[2], "person-b", "frontal", 4),
        ManifestItem(paths[3], "person-c", "profile", 5),
    ]
    embedded = [
        EmbeddedItem("person-a", "frontal", _embedding((1.0, 0.0))),
        EmbeddedItem("person-a", "low-light", _embedding((0.8, 0.6))),
        EmbeddedItem("person-b", "frontal", _embedding((0.0, 1.0))),
        EmbeddedItem("person-c", "profile", _embedding((-1.0, 0.0))),
    ]
    thresholds = (0.5, 0.65, 0.8, 0.85)

    report, pairs = build_report(
        manifest_items=manifest,
        embedded_items=embedded,
        latency_samples={"detect": [1.0, 2.0, 3.0]},
        thresholds=thresholds,
        manifest_sha256="a" * 64,
        max_fmr=0.1,
        detector_model="fake-yunet",
        recognizer_model="fake-sface",
        recognizer_version="fixture-v1",
        opencv_version="test-version",
    )

    overall = [row for row in report["threshold_metrics"] if row["scope"] == "overall"]
    assert len(pairs) == 6
    assert report["dataset_summary"]["genuine_pair_count"] == 1
    assert report["dataset_summary"]["impostor_pair_count"] == 5
    assert [row["fmr"] for row in overall] == pytest.approx([0.2, 0.0, 0.0, 0.0])
    assert [row["fnmr"] for row in overall] == pytest.approx([0.0, 0.0, 0.0, 1.0])
    assert [
        candidate["threshold"]
        for candidate in report["threshold_guidance"][
            "overall_thresholds_meeting_max_fmr"
        ]
    ] == [0.65, 0.8, 0.85]
    assert report["threshold_guidance"]["threshold_selected"] is None
    assert report["latency_ms"]["detect"]["p50_ms"] == pytest.approx(2.0)
    assert report["latency_ms"]["detect"]["p95_ms"] == pytest.approx(2.9)
    assert "condition_pair" in " ".join(report["similarity_distributions"])


def test_threshold_csv_and_pair_csv_omit_identity_and_path_data(tmp_path: Path) -> None:
    manifest = [
        ManifestItem(Path("private/path-a.png"), "private-person-a", "frontal", 2),
        ManifestItem(Path("private/path-b.png"), "private-person-b", "profile", 3),
    ]
    embedded = [
        EmbeddedItem("private-person-a", "frontal", _embedding((1.0, 0.0))),
        EmbeddedItem("private-person-b", "profile", _embedding((0.0, 1.0))),
    ]
    report, pairs = build_report(
        manifest_items=manifest,
        embedded_items=embedded,
        latency_samples={},
        thresholds=(0.5, 0.8),
        manifest_sha256="b" * 64,
        max_fmr=None,
        detector_model="fake-yunet",
        recognizer_model="fake-sface",
        recognizer_version="fixture-v1",
        opencv_version="test-version",
    )
    metrics_path = tmp_path / "out" / "thresholds.csv"
    pairs_path = tmp_path / "out" / "pairs.csv"
    report_path = tmp_path / "out" / "report.json"

    _write_threshold_csv(metrics_path, report["threshold_metrics"])
    _write_pair_csv(pairs_path, pairs)
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with metrics_path.open(encoding="utf-8", newline="") as source:
        metrics = list(csv.DictReader(source))
    pair_csv = pairs_path.read_text(encoding="utf-8")
    report_json = report_path.read_text(encoding="utf-8")
    assert len(metrics) == 4  # two thresholds for overall and one condition pair
    assert "private-person" not in pair_csv + report_json
    assert "private/path" not in pair_csv + report_json
    assert "similarity" in pair_csv


def test_run_embeddings_collects_per_image_and_per_pair_latency() -> None:
    items = [
        ManifestItem(Path("a.png"), "person-a", "frontal", 2),
        ManifestItem(Path("b.png"), "person-b", "frontal", 3),
    ]
    embeddings = {
        "a.png": _embedding((1.0, 0.0)),
        "b.png": _embedding((0.0, 1.0)),
    }

    result, latency = run_embeddings(
        items,
        lambda path: (embeddings[path.name], {"detect": 1.25, "embed": 0.5}),
    )

    assert len(result) == 2
    assert latency["detect"] == [1.25, 1.25]
    assert latency["embed"] == [0.5, 0.5]
    assert len(latency["cosine_match"]) == 1


def test_threshold_grid_covers_cosine_range_and_validates_arguments() -> None:
    thresholds = make_threshold_grid(-1, 1, 5)
    assert thresholds == (-1, -0.5, 0, 0.5, 1)
    with pytest.raises(ValueError, match="at least two"):
        make_threshold_grid(steps=1)
