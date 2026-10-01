from __future__ import annotations

import base64
import binascii
import json
import math
import os
import struct
from dataclasses import dataclass
from typing import Mapping
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from presensi_api.api.errors import ApiProblem


class BiometricCryptographyError(ValueError):
    """Encrypted face-template material cannot be safely used."""


@dataclass(frozen=True, slots=True)
class EncryptedEmbedding:
    ciphertext: bytes
    key_id: str
    dimension: int


@dataclass(frozen=True, slots=True)
class FaceTemplateKeyring:
    active_key_id: str
    keys: Mapping[str, bytes]

    @classmethod
    def from_environment(cls) -> FaceTemplateKeyring:
        raw_keys = os.getenv("PRESENSI_FACE_TEMPLATE_KEYS", "").strip()
        active_key_id = os.getenv("PRESENSI_FACE_TEMPLATE_ACTIVE_KEY_ID", "").strip()
        if not raw_keys or not active_key_id:
            raise BiometricCryptographyError(
                "Face-template encryption is not configured."
            )
        try:
            payload = json.loads(raw_keys)
        except json.JSONDecodeError as exc:
            raise BiometricCryptographyError(
                "Face-template key configuration is invalid."
            ) from exc
        if not isinstance(payload, dict):
            raise BiometricCryptographyError(
                "Face-template key configuration is invalid."
            )
        keys: dict[str, bytes] = {}
        for key_id, encoded in payload.items():
            if (
                not isinstance(key_id, str)
                or not key_id
                or not isinstance(encoded, str)
            ):
                raise BiometricCryptographyError(
                    "Face-template key configuration is invalid."
                )
            try:
                decoded = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise BiometricCryptographyError(
                    "Face-template key configuration is invalid."
                ) from exc
            if len(decoded) != 32:
                raise BiometricCryptographyError(
                    "Each face-template encryption key must be 32 bytes."
                )
            keys[key_id] = decoded
        if active_key_id not in keys:
            raise BiometricCryptographyError(
                "The active face-template encryption key is unavailable."
            )
        return cls(active_key_id=active_key_id, keys=keys)

    def encrypt(
        self,
        values: tuple[float, ...],
        *,
        template_id: UUID,
        student_id: UUID,
        model_name: str,
        model_version: str,
    ) -> EncryptedEmbedding:
        _validate_vector(values)
        key_id = self.active_key_id
        nonce = os.urandom(12)
        associated_data = _associated_data(
            template_id, student_id, model_name, model_version
        )
        packed = struct.pack(f"<{len(values)}f", *values)
        encrypted = AESGCM(self.keys[key_id]).encrypt(nonce, packed, associated_data)
        return EncryptedEmbedding(
            ciphertext=nonce + encrypted,
            key_id=key_id,
            dimension=len(values),
        )

    def decrypt(
        self,
        ciphertext: bytes,
        *,
        dimension: int,
        key_id: str,
        template_id: UUID,
        student_id: UUID,
        model_name: str,
        model_version: str,
    ) -> tuple[float, ...]:
        key = self.keys.get(key_id)
        if key is None or dimension < 1 or len(ciphertext) < 12 + 16:
            raise BiometricCryptographyError("Face template cannot be decrypted.")
        nonce, body = ciphertext[:12], ciphertext[12:]
        try:
            decoded = AESGCM(key).decrypt(
                nonce,
                body,
                _associated_data(template_id, student_id, model_name, model_version),
            )
        except (InvalidTag, ValueError) as exc:
            raise BiometricCryptographyError(
                "Face template cannot be decrypted."
            ) from exc
        if len(decoded) != dimension * 4:
            raise BiometricCryptographyError("Face template has invalid dimensions.")
        values = struct.unpack(f"<{dimension}f", decoded)
        try:
            _validate_vector(values)
        except ValueError as exc:
            raise BiometricCryptographyError("Face template is invalid.") from exc
        return tuple(float(value) for value in values)


def require_face_template_keyring() -> FaceTemplateKeyring:
    try:
        return FaceTemplateKeyring.from_environment()
    except BiometricCryptographyError as exc:
        raise ApiProblem(
            503,
            "face_template_encryption_unavailable",
            "Template processing is temporarily unavailable.",
        ) from exc


def cosine_similarity(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    if len(first) != len(second) or not first:
        return -1.0
    _validate_vector(first)
    _validate_vector(second)
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(first, second))))


def _validate_vector(values: tuple[float, ...]) -> None:
    if not values or any(not math.isfinite(value) for value in values):
        raise ValueError("Embedding values must be finite and non-empty.")
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or not math.isclose(norm, 1.0, abs_tol=1e-3):
        raise ValueError("Embedding must be L2 normalized.")


def _associated_data(
    template_id: UUID,
    student_id: UUID,
    model_name: str,
    model_version: str,
) -> bytes:
    return (
        f"presensi-face-template:v1:{template_id}:{student_id}:"
        f"{model_name}:{model_version}"
    ).encode("utf-8")
