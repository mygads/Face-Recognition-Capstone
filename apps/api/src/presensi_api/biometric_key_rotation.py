from __future__ import annotations

import argparse
from uuid import UUID

from sqlalchemy import select

from presensi_api.biometric_crypto import require_face_template_keyring
from presensi_api.db.models import FaceTemplate
from presensi_api.db.session import get_session_factory

DEFAULT_BATCH_SIZE = 100


def rotate_active_template_keys(*, batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    if batch_size < 1 or batch_size > 10_000:
        raise ValueError("batch_size must be between 1 and 10000.")
    keyring = require_face_template_keyring()
    session_factory = get_session_factory()
    rotated = 0
    last_id: UUID | None = None
    with session_factory() as session:
        while True:
            statement = (
                select(FaceTemplate)
                .where(
                    FaceTemplate.revoked_at.is_(None),
                    FaceTemplate.encryption_key_id != keyring.active_key_id,
                    FaceTemplate.embedding_ciphertext.is_not(None),
                )
                .order_by(FaceTemplate.id)
                .limit(batch_size)
            )
            if last_id is not None:
                statement = statement.where(FaceTemplate.id > last_id)
            templates = session.scalars(statement).all()
            if not templates:
                break
            for template in templates:
                if (
                    template.embedding_ciphertext is None
                    or template.encryption_key_id is None
                    or template.embedding_dimension is None
                ):
                    raise RuntimeError(
                        "An active face template is missing encrypted payload metadata."
                    )
                values = keyring.decrypt(
                    template.embedding_ciphertext,
                    dimension=template.embedding_dimension,
                    key_id=template.encryption_key_id,
                    template_id=template.id,
                    student_id=template.student_id,
                    model_name=template.model_name,
                    model_version=template.model_version,
                )
                encrypted = keyring.encrypt(
                    values,
                    template_id=template.id,
                    student_id=template.student_id,
                    model_name=template.model_name,
                    model_version=template.model_version,
                )
                template.embedding_ciphertext = encrypted.ciphertext
                template.encryption_key_id = encrypted.key_id
                template.embedding_dimension = encrypted.dimension
                rotated += 1
            last_id = templates[-1].id
            session.commit()
    return rotated


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-encrypt active face templates with the configured active key."
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args()
    count = rotate_active_template_keys(batch_size=args.batch_size)
    print(f"Re-encrypted {count} active face template vectors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
