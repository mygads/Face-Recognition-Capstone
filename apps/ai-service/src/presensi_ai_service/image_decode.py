from __future__ import annotations

import base64
import binascii
import importlib
import io
import warnings
from typing import Any, cast

from PIL import Image, ImageOps, UnidentifiedImageError


class ImageDecodeError(ValueError):
    """An image was corrupt, oversized, or did not match its declared type."""


_MIME_FORMATS = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}


def decode_image(
    encoded: str,
    content_type: str,
    *,
    max_encoded_bytes: int,
    max_width: int,
    max_height: int,
    max_pixels: int,
) -> object:
    """Decode bounded base64 image bytes to an in-memory OpenCV BGR array.

    The payload is never written to disk. Pillow verifies the stream before
    decoding, applies EXIF orientation, and enforces dimensions before pixel
    allocation; OpenCV is only used for the final RGB-to-BGR array conversion.
    """
    image_format = _MIME_FORMATS.get(content_type)
    if image_format is None:
        raise ImageDecodeError("Unsupported image media type.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImageDecodeError("Image payload is not valid base64.") from exc
    if not raw or len(raw) > max_encoded_bytes:
        raise ImageDecodeError("Image payload is empty or exceeds the frame limit.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as probe:
                if probe.format != image_format:
                    raise ImageDecodeError(
                        "Image bytes do not match the declared media type."
                    )
                width, height = probe.size
                if (
                    width < 1
                    or height < 1
                    or width > max_width
                    or height > max_height
                    or width * height > max_pixels
                ):
                    raise ImageDecodeError("Decoded image dimensions exceed limits.")
                if getattr(probe, "n_frames", 1) != 1:
                    raise ImageDecodeError("Animated images are not supported.")
                probe.verify()

            with Image.open(io.BytesIO(raw)) as image:
                oriented = ImageOps.exif_transpose(image)
                oriented.load()
                rgb_image = oriented.convert("RGB")
                np = importlib.import_module("numpy")
                cv2 = importlib.import_module("cv2")
                rgb_array = np.asarray(rgb_image)
                return cv2.cvtColor(cast(Any, rgb_array), cv2.COLOR_RGB2BGR)
    except ImageDecodeError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        EOFError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise ImageDecodeError("Image payload is corrupt or unsafe to decode.") from exc
    except ImportError as exc:
        raise RuntimeError(
            "Image decoding needs NumPy and OpenCV; install the AI service "
            "inference extra."
        ) from exc
