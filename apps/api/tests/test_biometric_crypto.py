from __future__ import annotations

import base64
import json
from uuid import uuid4

import pytest

from presensi_api.biometric_crypto import (
    BiometricCryptographyError,
    FaceTemplateKeyring,
)


def _keyring() -> FaceTemplateKeyring:
    return FaceTemplateKeyring(
        active_key_id="test-v1",
        keys={"test-v1": b"k" * 32},
    )


def test_embedding_round_trip_is_bound_to_template_metadata() -> None:
    keyring = _keyring()
    template_id = uuid4()
    student_id = uuid4()
    encrypted = keyring.encrypt(
        (1.0, 0.0, 0.0),
        template_id=template_id,
        student_id=student_id,
        model_name="synthetic-model",
        model_version="v1",
    )

    assert encrypted.ciphertext != b"\x00\x00\x80?\x00\x00\x00\x00\x00\x00\x00\x00"
    assert keyring.decrypt(
        encrypted.ciphertext,
        dimension=encrypted.dimension,
        key_id=encrypted.key_id,
        template_id=template_id,
        student_id=student_id,
        model_name="synthetic-model",
        model_version="v1",
    ) == pytest.approx((1.0, 0.0, 0.0))

    with pytest.raises(BiometricCryptographyError):
        keyring.decrypt(
            encrypted.ciphertext,
            dimension=encrypted.dimension,
            key_id=encrypted.key_id,
            template_id=template_id,
            student_id=uuid4(),
            model_name="synthetic-model",
            model_version="v1",
        )


def test_keyring_configuration_loads_key_ids_for_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = base64.b64encode(b"o" * 32).decode("ascii")
    active = base64.b64encode(b"a" * 32).decode("ascii")
    monkeypatch.setenv(
        "PRESENSI_FACE_TEMPLATE_KEYS",
        json.dumps({"old-v1": old, "active-v2": active}),
    )
    monkeypatch.setenv("PRESENSI_FACE_TEMPLATE_ACTIVE_KEY_ID", "active-v2")

    keyring = FaceTemplateKeyring.from_environment()

    assert keyring.active_key_id == "active-v2"
    assert keyring.keys["old-v1"] == b"o" * 32
