from __future__ import annotations

import math
import os
import secrets
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from presensi_api.api.errors import ApiProblem
from presensi_api.api.security.roles import AuthenticatedUser
from presensi_api.db.models import AuditLog, RuntimeConfigurationVersion

SESSION_OPENING_POLICY_SCOPE = "attendance-session-policy"
DEFAULT_SESSION_OPENING_POLICY: dict[str, object] = {
    "mode": "manual",
    "auto_open_minutes_before": 0,
    "auto_open_minutes_after": 15,
    "default_grace_period_minutes": 15,
}


def device_scope_key(device_id: UUID) -> str:
    return f"device:{device_id}"


def latest_configuration(
    session: Session, scope_key: str
) -> RuntimeConfigurationVersion | None:
    return session.scalars(
        select(RuntimeConfigurationVersion)
        .where(RuntimeConfigurationVersion.scope_key == scope_key)
        .order_by(RuntimeConfigurationVersion.revision.desc())
        .limit(1)
    ).first()


def configuration_values(
    session: Session, scope_key: str
) -> tuple[int, dict[str, object], datetime | None]:
    version = latest_configuration(session, scope_key)
    if version is None:
        return 0, {}, None
    return version.revision, dict(version.settings), version.created_at


def session_opening_policy(
    session: Session,
) -> tuple[int, dict[str, object], datetime | None]:
    revision, stored, updated_at = configuration_values(
        session, SESSION_OPENING_POLICY_SCOPE
    )
    values = {**DEFAULT_SESSION_OPENING_POLICY, **stored}
    if values.get("mode") not in {"manual", "automatic"}:
        values["mode"] = "manual"
    for key, default, maximum in (
        ("auto_open_minutes_before", 0, 15),
        ("auto_open_minutes_after", 15, 15),
        ("default_grace_period_minutes", 15, 1440),
    ):
        value = values.get(key)
        if type(value) is not int or not 0 <= value <= maximum:
            values[key] = default
    return revision, values, updated_at


def save_configuration(
    session: Session,
    *,
    scope_key: str,
    settings: dict[str, object],
    actor: AuthenticatedUser,
) -> RuntimeConfigurationVersion:
    previous = session.scalars(
        select(RuntimeConfigurationVersion)
        .where(RuntimeConfigurationVersion.scope_key == scope_key)
        .order_by(RuntimeConfigurationVersion.revision.desc())
        .limit(1)
        .with_for_update()
    ).first()
    revision = 1 if previous is None else previous.revision + 1
    version = RuntimeConfigurationVersion(
        scope_key=scope_key,
        revision=revision,
        settings=settings,
        actor_user_id=actor.id,
    )
    session.add(version)
    try:
        session.flush()
        session.add(
            AuditLog(
                actor_user_id=actor.id,
                action="runtime_configuration.published",
                entity_type="runtime_configuration",
                entity_id=version.id,
                before_state={"scope_key": scope_key, "revision": revision - 1},
                after_state={
                    "scope_key": scope_key,
                    "revision": revision,
                    "settings": settings,
                },
            )
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiProblem(
            409,
            "configuration_conflict",
            "Konfigurasi berubah bersamaan. Muat ulang lalu coba lagi.",
        ) from exc
    session.refresh(version)
    return version


def enrollment_quality_from_environment() -> dict[str, object]:
    return {
        "min_face_pixels": _int_env("PRESENSI_ENROLLMENT_MIN_FACE_PIXELS", 80),
        "min_sharpness": _float_env("PRESENSI_ENROLLMENT_MIN_SHARPNESS", 45.0),
        "min_brightness": _float_env("PRESENSI_ENROLLMENT_MIN_BRIGHTNESS", 25.0),
        "max_brightness": _float_env("PRESENSI_ENROLLMENT_MAX_BRIGHTNESS", 235.0),
    }


def central_configuration_from_environment() -> dict[str, object]:
    return {
        "min_top1_similarity": _optional_float_env("PRESENSI_AI_MIN_TOP1_SIMILARITY"),
        "min_top1_top2_margin": _optional_float_env("PRESENSI_AI_MIN_TOP1_TOP2_MARGIN"),
        "minimum_agreeing_frames": _int_env("PRESENSI_AI_MINIMUM_AGREEING_FRAMES", 3),
        "sample_every_n_frames": _int_env("PRESENSI_AI_SAMPLE_EVERY_N_FRAMES", 1),
        "best_frame_count": _int_env("PRESENSI_AI_BEST_FRAME_COUNT", 5),
        "max_history_frames": _int_env("PRESENSI_AI_MAX_HISTORY_FRAMES", 10),
        "min_face_pixels": _int_env("PRESENSI_AI_MIN_FACE_PIXELS", 80),
        "min_laplacian_variance": _float_env(
            "PRESENSI_AI_MIN_LAPLACIAN_VARIANCE", 45.0
        ),
        "min_brightness": _float_env("PRESENSI_AI_MIN_BRIGHTNESS", 25.0),
        "max_brightness": _float_env("PRESENSI_AI_MAX_BRIGHTNESS", 235.0),
        "calibration_reference": None,
    }


def managed_ai_sync_token_matches(candidate: str | None) -> bool:
    configured = os.getenv("PRESENSI_AI_CONFIG_SYNC_TOKEN", "").strip()
    if len(configured) < 32 or not candidate:
        return False
    return secrets.compare_digest(configured.encode(), candidate.encode())


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if math.isfinite(value) else default


def _optional_float_env(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) else None
