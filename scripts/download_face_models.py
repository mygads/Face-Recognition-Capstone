from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "models" / "weights"


@dataclass(frozen=True, slots=True)
class ModelAsset:
    filename: str
    url: str
    sha256: str
    size_bytes: int


ASSETS = (
    ModelAsset(
        filename="face_detection_yunet_2023mar.onnx",
        url=(
            "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
            "models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
        ),
        sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        size_bytes=232_589,
    ),
    ModelAsset(
        filename="face_recognition_sface_2021dec.onnx",
        url=(
            "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
            "models/face_recognition_sface/face_recognition_sface_2021dec.onnx"
        ),
        sha256="0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        size_bytes=38_696_353,
    ),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def provision_asset(asset: ModelAsset, directory: Path) -> Path:
    destination = directory / asset.filename
    directory.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and sha256_file(destination) == asset.sha256:
        print(f"Verified existing {destination}")
        return destination

    partial = destination.with_name(destination.name + ".partial")
    digest = hashlib.sha256()
    size = 0
    request = urllib.request.Request(
        asset.url,
        headers={"User-Agent": "presensi-face-recognition-model-provisioner/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            with partial.open("wb") as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
                    digest.update(block)
                    size += len(block)
        if size != asset.size_bytes or digest.hexdigest() != asset.sha256:
            raise ValueError(
                f"Checksum/size mismatch for {asset.filename}; "
                "the partial file will be removed."
            )
        os.replace(partial, destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise

    print(f"Downloaded and verified {destination} ({size:,} bytes)")
    print(f"SHA-256: {asset.sha256}")
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download checksum-pinned OpenCV Zoo YuNet and SFace models."
    )
    parser.add_argument(
        "--directory",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Destination directory (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args(argv)

    try:
        for asset in ASSETS:
            provision_asset(asset, args.directory)
    except (OSError, ValueError) as exc:
        print(f"Model download failed: {exc}", file=sys.stderr)
        return 1

    print(
        "SFace is provisioned for local evaluation. Review docs/models.md and "
        "obtain institutional clearance before production use."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
