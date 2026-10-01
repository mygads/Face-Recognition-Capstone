"""Local CLI for image-pair comparison and labelled-folder score benchmarks."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from recognition_core.domain import FaceEmbedding
from recognition_core.evaluation import BenchmarkSummary, ScoreSummary, evaluate_pairs
from recognition_core.matching import cosine_similarity
from recognition_core.opencv_models import (
    OpenCVDependencyError,
    SFaceModel,
    YuNetConfig,
    YuNetFaceDetector,
    model_version_from_path,
    read_color_image,
)

_IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".webp"}


def _cosine_threshold(value: str) -> float:
    threshold = float(value)
    if not math.isfinite(threshold) or not -1 <= threshold <= 1:
        raise argparse.ArgumentTypeError("threshold must be between -1 and 1")
    return threshold


def _add_model_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--yunet-model",
        required=True,
        type=Path,
        help="Path to the locally provisioned YuNet ONNX model.",
    )
    parser.add_argument(
        "--sface-model",
        required=True,
        type=Path,
        help="Path to the locally provisioned SFace ONNX model.",
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=0.9,
        help="YuNet detector score filter; this is not the recognition threshold.",
    )
    parser.add_argument("--nms-threshold", type=float, default=0.3)
    parser.add_argument("--top-k", type=int, default=5000)
    parser.add_argument(
        "--threshold",
        type=_cosine_threshold,
        help=(
            "Optional cosine threshold for score reporting; "
            "no calibrated default is used."
        ),
    )


def _build_models(args: argparse.Namespace) -> tuple[YuNetFaceDetector, SFaceModel]:
    detector = YuNetFaceDetector(
        args.yunet_model,
        YuNetConfig(
            score_threshold=args.score_threshold,
            nms_threshold=args.nms_threshold,
            top_k=args.top_k,
        ),
    )
    recognizer = SFaceModel(
        args.sface_model,
        model_version=model_version_from_path(args.sface_model),
    )
    return detector, recognizer


def _embedding_for_image(
    image_path: Path,
    detector: YuNetFaceDetector,
    recognizer: SFaceModel,
) -> FaceEmbedding:
    image = read_color_image(image_path)
    detections = detector.detect(image)
    if len(detections) != 1:
        raise ValueError(
            f"Expected exactly one detectable face in {image_path.name}; "
            f"found {len(detections)}."
        )
    aligned = recognizer.align(image, detections[0])
    return recognizer.embed(aligned)


def _summary_json(summary: ScoreSummary) -> dict[str, int | float | None]:
    return {
        "pair_count": summary.count,
        "mean_cosine": summary.mean,
        "minimum_cosine": summary.minimum,
        "maximum_cosine": summary.maximum,
        "accepted_count_at_configured_threshold": summary.accepted_count,
        "acceptance_rate_at_configured_threshold": summary.acceptance_rate,
    }


def _compare(args: argparse.Namespace) -> int:
    detector, recognizer = _build_models(args)
    left = _embedding_for_image(args.image_a, detector, recognizer)
    right = _embedding_for_image(args.image_b, detector, recognizer)
    score = cosine_similarity(left, right)
    result: dict[str, Any] = {
        "cosine_similarity": score,
        "configured_threshold": args.threshold,
        "passes_configured_threshold": (
            score >= args.threshold if args.threshold is not None else None
        ),
        "model_name": left.model_name,
        "model_version": left.model_version,
    }
    print(json.dumps(result, indent=2))
    return 0


def _load_benchmark_groups(
    root: Path,
    detector: YuNetFaceDetector,
    recognizer: SFaceModel,
) -> dict[str, list[FaceEmbedding]]:
    if not root.is_dir():
        raise NotADirectoryError(f"Benchmark folder does not exist: {root}")
    groups: dict[str, list[FaceEmbedding]] = {}
    for identity_folder in sorted(path for path in root.iterdir() if path.is_dir()):
        images = sorted(
            path
            for path in identity_folder.iterdir()
            if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES
        )
        if not images:
            continue
        groups[identity_folder.name] = [
            _embedding_for_image(image, detector, recognizer) for image in images
        ]
    if not groups:
        raise ValueError(
            "Benchmark folder must contain identity subfolders with image files."
        )
    return groups


def _benchmark(args: argparse.Namespace) -> int:
    detector, recognizer = _build_models(args)
    groups = _load_benchmark_groups(args.folder, detector, recognizer)
    summary: BenchmarkSummary = evaluate_pairs(groups, threshold=args.threshold)
    output = {
        "identity_group_count": len(groups),
        "threshold": summary.threshold,
        "same_identity_pairs": _summary_json(summary.same_identity),
        "different_identity_pairs": _summary_json(summary.different_identity),
        "note": (
            "Pair statistics describe this local dataset only; a threshold must be "
            "calibrated on representative, lawfully collected data."
        ),
    }
    print(json.dumps(output, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="recognition-core",
        description="Compare SFace embeddings or summarize a labelled image folder.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    compare_parser = commands.add_parser(
        "compare", help="Compare two images, each containing exactly one face."
    )
    compare_parser.add_argument("image_a", type=Path)
    compare_parser.add_argument("image_b", type=Path)
    _add_model_options(compare_parser)
    compare_parser.set_defaults(handler=_compare)

    benchmark_parser = commands.add_parser(
        "benchmark", help="Summarize all pair scores in identity subfolders."
    )
    benchmark_parser.add_argument("folder", type=Path)
    _add_model_options(benchmark_parser)
    benchmark_parser.set_defaults(handler=_benchmark)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = args.handler
    try:
        return int(handler(args))
    except (
        FileNotFoundError,
        NotADirectoryError,
        OpenCVDependencyError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
