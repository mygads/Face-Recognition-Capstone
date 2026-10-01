"""Local YuNet/SFace verification benchmark harness.

This tool evaluates one-to-one genuine and impostor comparisons. It does not
create attendance decisions or select a production threshold.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import importlib
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from recognition_core.domain import FaceEmbedding
from recognition_core.matching import cosine_similarity
from recognition_core.opencv_models import (
    SFaceModel,
    YuNetConfig,
    YuNetFaceDetector,
    model_version_from_path,
    read_color_image,
)

PairType = Literal["genuine", "impostor"]
EmbeddingFunction = Callable[[Path], tuple[FaceEmbedding, Mapping[str, float]]]


@dataclass(frozen=True, slots=True)
class ManifestItem:
    path: Path
    person_id: str
    condition: str
    row_number: int


@dataclass(frozen=True, slots=True)
class EmbeddedItem:
    person_id: str
    condition: str
    embedding: FaceEmbedding


@dataclass(frozen=True, slots=True)
class PairScore:
    pair_type: PairType
    similarity: float
    condition_a: str
    condition_b: str


def load_manifest(manifest_path: Path) -> tuple[list[ManifestItem], str]:
    """Read a CSV manifest and resolve relative image paths beside that file."""
    resolved_manifest = manifest_path.expanduser().resolve(strict=True)
    manifest_bytes = resolved_manifest.read_bytes()
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    items: list[ManifestItem] = []
    seen_paths: set[Path] = set()

    with resolved_manifest.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required_columns = {"path", "person_id", "condition"}
        columns = set(reader.fieldnames or ())
        missing = sorted(required_columns - columns)
        if missing:
            raise ValueError(
                "Manifest must have path, person_id, condition columns; missing: "
                + ", ".join(missing)
            )

        for row_number, row in enumerate(reader, start=2):
            path_value = (row.get("path") or "").strip()
            person_id = (row.get("person_id") or "").strip()
            condition = (row.get("condition") or "").strip()
            if not path_value or not person_id or not condition:
                raise ValueError(
                    f"Manifest row {row_number} needs non-empty path, person_id, "
                    "and condition values."
                )

            image_path = Path(path_value).expanduser()
            if not image_path.is_absolute():
                image_path = resolved_manifest.parent / image_path
            image_path = image_path.resolve(strict=True)
            if not image_path.is_file():
                raise ValueError(f"Manifest row {row_number} path is not a file.")
            if image_path in seen_paths:
                raise ValueError(f"Manifest row {row_number} repeats an image path.")
            seen_paths.add(image_path)
            items.append(
                ManifestItem(
                    path=image_path,
                    person_id=person_id,
                    condition=condition,
                    row_number=row_number,
                )
            )

    if len(items) < 2:
        raise ValueError("Manifest must contain at least two image rows.")
    return items, manifest_hash


def make_threshold_grid(
    minimum: float = -1.0,
    maximum: float = 1.0,
    steps: int = 201,
) -> tuple[float, ...]:
    if not math.isfinite(minimum) or not math.isfinite(maximum):
        raise ValueError("Threshold bounds must be finite.")
    if not -1 <= minimum < maximum <= 1:
        raise ValueError("Threshold bounds must satisfy -1 <= min < max <= 1.")
    if steps < 2:
        raise ValueError("Threshold grid must contain at least two values.")
    interval = maximum - minimum
    return tuple(
        round(minimum + interval * index / (steps - 1), 8) for index in range(steps)
    )


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _latency_summary(values: Sequence[float]) -> dict[str, int | float | None]:
    return {
        "count": len(values),
        "mean_ms": statistics.fmean(values) if values else None,
        "p50_ms": _percentile(values, 0.50),
        "p95_ms": _percentile(values, 0.95),
    }


def _similarity_distribution(values: Sequence[float]) -> dict[str, Any]:
    histogram_bins = 20
    counts = [0] * histogram_bins
    for value in values:
        index = min(histogram_bins - 1, int((value + 1) * histogram_bins / 2))
        counts[index] += 1
    histogram = [
        {
            "lower_inclusive": -1 + 2 * index / histogram_bins,
            "upper_exclusive": -1 + 2 * (index + 1) / histogram_bins,
            "count": count,
        }
        for index, count in enumerate(counts)
    ]
    if histogram:
        histogram[-1]["upper_exclusive"] = 1.0
    return {
        "count": len(values),
        "mean": statistics.fmean(values) if values else None,
        "stddev": statistics.pstdev(values) if len(values) > 1 else None,
        "minimum": min(values) if values else None,
        "p05": _percentile(values, 0.05),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "maximum": max(values) if values else None,
        "histogram": histogram,
    }


def _make_pairs(items: Sequence[EmbeddedItem]) -> list[PairScore]:
    pairs: list[PairScore] = []
    for index, left in enumerate(items):
        for right in items[index + 1 :]:
            pairs.append(
                PairScore(
                    pair_type=(
                        "genuine" if left.person_id == right.person_id else "impostor"
                    ),
                    similarity=cosine_similarity(left.embedding, right.embedding),
                    condition_a=left.condition,
                    condition_b=right.condition,
                )
            )
    return pairs


def _scope_key(condition_a: str, condition_b: str) -> str:
    return "condition_pair:" + json.dumps(
        sorted((condition_a, condition_b)), ensure_ascii=False, separators=(",", ":")
    )


def _threshold_row(
    *,
    scope: str,
    threshold: float,
    genuine_scores: Sequence[float],
    impostor_scores: Sequence[float],
    max_fmr: float | None,
) -> dict[str, int | float | bool | str | None]:
    false_accepts = len(impostor_scores) - bisect.bisect_left(
        impostor_scores, threshold
    )
    false_rejects = bisect.bisect_left(genuine_scores, threshold)
    fmr = false_accepts / len(impostor_scores) if impostor_scores else None
    fnmr = false_rejects / len(genuine_scores) if genuine_scores else None
    meets_target = fmr <= max_fmr if fmr is not None and max_fmr is not None else None
    return {
        "scope": scope,
        "threshold": threshold,
        "genuine_pairs": len(genuine_scores),
        "impostor_pairs": len(impostor_scores),
        "false_accepts": false_accepts,
        "far": fmr,
        "fmr": fmr,
        "false_rejects": false_rejects,
        "frr": fnmr,
        "fnmr": fnmr,
        "max_fmr_target": max_fmr,
        "meets_max_fmr": meets_target,
    }


def build_report(
    *,
    manifest_items: Sequence[ManifestItem],
    embedded_items: Sequence[EmbeddedItem],
    latency_samples: Mapping[str, Sequence[float]],
    thresholds: Sequence[float],
    manifest_sha256: str,
    max_fmr: float | None,
    detector_model: str,
    recognizer_model: str,
    recognizer_version: str,
    opencv_version: str,
) -> tuple[dict[str, Any], list[PairScore]]:
    if max_fmr is not None and (not math.isfinite(max_fmr) or not 0 <= max_fmr <= 1):
        raise ValueError("max_fmr must be between 0 and 1.")
    if len(manifest_items) != len(embedded_items):
        raise ValueError("Each manifest row must have exactly one embedding.")
    if not thresholds:
        raise ValueError("At least one threshold is required.")

    pairs = _make_pairs(embedded_items)
    scoped_pairs: dict[str, list[PairScore]] = {"overall": pairs}
    for pair in pairs:
        scope = _scope_key(pair.condition_a, pair.condition_b)
        scoped_pairs.setdefault(scope, []).append(pair)

    distributions: dict[str, dict[str, Any]] = {}
    threshold_metrics: list[dict[str, int | float | bool | str | None]] = []
    for scope, scope_pairs in sorted(scoped_pairs.items()):
        genuine_scores = sorted(
            pair.similarity for pair in scope_pairs if pair.pair_type == "genuine"
        )
        impostor_scores = sorted(
            pair.similarity for pair in scope_pairs if pair.pair_type == "impostor"
        )
        distributions[scope] = {
            "genuine": _similarity_distribution(genuine_scores),
            "impostor": _similarity_distribution(impostor_scores),
        }
        threshold_metrics.extend(
            _threshold_row(
                scope=scope,
                threshold=threshold,
                genuine_scores=genuine_scores,
                impostor_scores=impostor_scores,
                max_fmr=max_fmr,
            )
            for threshold in thresholds
        )

    overall_metrics = [row for row in threshold_metrics if row["scope"] == "overall"]
    eligible_thresholds = [
        {"threshold": row["threshold"], "fmr": row["fmr"], "fnmr": row["fnmr"]}
        for row in overall_metrics
        if row["meets_max_fmr"] is True
    ]
    condition_counts = Counter(item.condition for item in manifest_items)
    report = {
        "schema_version": 1,
        "manifest_sha256": manifest_sha256,
        "models": {
            "detector": detector_model,
            "recognizer": recognizer_model,
            "recognizer_version": recognizer_version,
            "opencv_version": opencv_version,
        },
        "dataset_summary": {
            "image_count": len(manifest_items),
            "identity_count": len({item.person_id for item in manifest_items}),
            "condition_counts": dict(sorted(condition_counts.items())),
            "genuine_pair_count": sum(pair.pair_type == "genuine" for pair in pairs),
            "impostor_pair_count": sum(pair.pair_type == "impostor" for pair in pairs),
        },
        "similarity_distributions": distributions,
        "threshold_metrics": threshold_metrics,
        "threshold_guidance": {
            "acceptance_rule": "accept when cosine_similarity >= threshold",
            "max_fmr_constraint": max_fmr,
            "overall_thresholds_meeting_max_fmr": eligible_thresholds,
            "threshold_selected": None,
            "interpretation": (
                "FAR/FMR are pair-level impostor false accepts; FRR/FNMR are "
                "genuine false rejects. No total-accuracy score is used to choose "
                "a threshold. Review support counts and FRR at an acceptable low "
                "FMR, then validate the candidate on a separate representative set."
            ),
        },
        "latency_ms": {
            stage: _latency_summary(samples)
            for stage, samples in sorted(latency_samples.items())
        },
        "latency_scope": (
            "Measured baseline stages are image_read, detect, align, embed, "
            "cosine_match, and per_image_total. Quality, liveness, and temporal "
            "decision are not implemented by this YuNet/SFace verification harness."
        ),
    }
    return report, pairs


class OpenCVEmbeddingRunner:
    """Extract one normalized SFace embedding and time each executed stage."""

    def __init__(
        self,
        yunet_model: Path,
        sface_model: Path,
        *,
        score_threshold: float = 0.9,
    ) -> None:
        self.detector = YuNetFaceDetector(
            yunet_model,
            YuNetConfig(score_threshold=score_threshold),
        )
        self.recognizer = SFaceModel(
            sface_model,
            model_version=model_version_from_path(sface_model),
        )

    def __call__(self, image_path: Path) -> tuple[FaceEmbedding, Mapping[str, float]]:
        stage_times: dict[str, float] = {}
        total_start = time.perf_counter()

        started = time.perf_counter()
        image = read_color_image(image_path)
        stage_times["image_read"] = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        detections = self.detector.detect(image)
        stage_times["detect"] = (time.perf_counter() - started) * 1000
        if len(detections) != 1:
            raise ValueError(
                "Expected exactly one face in manifest row image; "
                f"found {len(detections)}."
            )

        started = time.perf_counter()
        aligned = self.recognizer.align(image, detections[0])
        stage_times["align"] = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        embedding = self.recognizer.embed(aligned)
        stage_times["embed"] = (time.perf_counter() - started) * 1000
        stage_times["per_image_total"] = (time.perf_counter() - total_start) * 1000
        return embedding, stage_times


def run_embeddings(
    manifest_items: Sequence[ManifestItem],
    embed_image: EmbeddingFunction,
) -> tuple[list[EmbeddedItem], dict[str, list[float]]]:
    embedded: list[EmbeddedItem] = []
    latencies: dict[str, list[float]] = defaultdict(list)
    for item in manifest_items:
        embedding, stage_times = embed_image(item.path)
        for stage, duration in stage_times.items():
            if not math.isfinite(duration) or duration < 0:
                raise ValueError(f"Stage {stage} returned an invalid duration.")
            latencies[stage].append(duration)
        embedded.append(
            EmbeddedItem(
                person_id=item.person_id,
                condition=item.condition,
                embedding=embedding,
            )
        )

    match_latencies: list[float] = []
    for index, left in enumerate(embedded):
        for right in embedded[index + 1 :]:
            started = time.perf_counter()
            cosine_similarity(left.embedding, right.embedding)
            match_latencies.append((time.perf_counter() - started) * 1000)
    latencies["cosine_match"].extend(match_latencies)
    return embedded, dict(latencies)


def _write_threshold_csv(
    output_path: Path,
    rows: Sequence[Mapping[str, int | float | bool | str | None]],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    columns = (
        "scope",
        "threshold",
        "genuine_pairs",
        "impostor_pairs",
        "false_accepts",
        "far",
        "fmr",
        "false_rejects",
        "frr",
        "fnmr",
        "max_fmr_target",
        "meets_max_fmr",
    )
    with output_path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _write_pair_csv(output_path: Path, pairs: Sequence[PairScore]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(
            target,
            fieldnames=("pair_type", "similarity", "condition_a", "condition_b"),
        )
        writer.writeheader()
        writer.writerows(
            {
                "pair_type": pair.pair_type,
                "similarity": pair.similarity,
                "condition_a": pair.condition_a,
                "condition_b": pair.condition_b,
            }
            for pair in pairs
        )


def _write_plot(
    output_path: Path, report: Mapping[str, Any], pairs: Sequence[PairScore]
) -> None:
    try:
        plt = importlib.import_module("matplotlib.pyplot")
    except ImportError as exc:
        raise RuntimeError(
            "Plot output requires matplotlib. Install it with: "
            "python -m pip install matplotlib"
        ) from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    genuine = [pair.similarity for pair in pairs if pair.pair_type == "genuine"]
    impostor = [pair.similarity for pair in pairs if pair.pair_type == "impostor"]
    metrics = [row for row in report["threshold_metrics"] if row["scope"] == "overall"]
    thresholds = [row["threshold"] for row in metrics]
    far_values = [row["far"] for row in metrics]
    frr_values = [row["frr"] for row in metrics]

    figure, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    axes[0].hist(genuine, bins=30, range=(-1, 1), alpha=0.65, label="Genuine")
    axes[0].hist(impostor, bins=30, range=(-1, 1), alpha=0.65, label="Impostor")
    axes[0].set(
        title="Cosine similarity distributions",
        xlabel="Cosine similarity",
        ylabel="Pair count",
    )
    axes[0].legend()
    axes[1].plot(thresholds, far_values, label="FAR / FMR")
    axes[1].plot(thresholds, frr_values, label="FRR / FNMR")
    axes[1].set(
        title="Pair error rates by threshold",
        xlabel="Cosine threshold (accept >=)",
        ylabel="Rate",
        ylim=(0, 1),
    )
    axes[1].legend()
    figure.tight_layout()
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _unit_interval(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or not 0 <= parsed <= 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark local YuNet/SFace verification scores and latency."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--yunet-model", required=True, type=Path)
    parser.add_argument("--sface-model", required=True, type=Path)
    parser.add_argument("--score-threshold", type=float, default=0.9)
    parser.add_argument("--threshold-min", type=float, default=-1.0)
    parser.add_argument("--threshold-max", type=float, default=1.0)
    parser.add_argument("--threshold-steps", type=_positive_integer, default=201)
    parser.add_argument(
        "--max-fmr",
        type=_unit_interval,
        help=(
            "Optional low-FMR constraint; report eligible thresholds without "
            "selecting one."
        ),
    )
    parser.add_argument("--max-pairs", type=_positive_integer, default=1_000_000)
    parser.add_argument("--json-out", required=True, type=Path)
    parser.add_argument("--csv-out", required=True, type=Path)
    parser.add_argument("--pair-csv-out", type=Path)
    parser.add_argument("--plot-out", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest_items, manifest_hash = load_manifest(args.manifest)
        possible_pairs = len(manifest_items) * (len(manifest_items) - 1) // 2
        if possible_pairs > args.max_pairs:
            raise ValueError(
                f"Manifest creates {possible_pairs} pairs; limit is {args.max_pairs}."
            )
        thresholds = make_threshold_grid(
            args.threshold_min,
            args.threshold_max,
            args.threshold_steps,
        )
        runner = OpenCVEmbeddingRunner(
            args.yunet_model,
            args.sface_model,
            score_threshold=args.score_threshold,
        )
        embedded_items, latency_samples = run_embeddings(manifest_items, runner)

        cv2 = importlib.import_module("cv2")

        report, pairs = build_report(
            manifest_items=manifest_items,
            embedded_items=embedded_items,
            latency_samples=latency_samples,
            thresholds=thresholds,
            manifest_sha256=manifest_hash,
            max_fmr=args.max_fmr,
            detector_model="OpenCV Zoo YuNet",
            recognizer_model="OpenCV Zoo SFace",
            recognizer_version=model_version_from_path(args.sface_model),
            opencv_version=str(cv2.__version__),
        )

        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        _write_threshold_csv(args.csv_out, report["threshold_metrics"])
        if args.pair_csv_out is not None:
            _write_pair_csv(args.pair_csv_out, pairs)
        if args.plot_out is not None:
            _write_plot(args.plot_out, report, pairs)
        print(
            json.dumps(
                {
                    "image_count": len(manifest_items),
                    "genuine_pair_count": report["dataset_summary"][
                        "genuine_pair_count"
                    ],
                    "impostor_pair_count": report["dataset_summary"][
                        "impostor_pair_count"
                    ],
                    "json_report": str(args.json_out),
                    "threshold_csv": str(args.csv_out),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (FileNotFoundError, NotADirectoryError, RuntimeError, ValueError) as exc:
        print(f"benchmark error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
