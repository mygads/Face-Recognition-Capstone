from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from recognition_core.domain import FaceEmbedding, GalleryEntry


class GalleryCacheError(ValueError):
    """Raised when a session gallery is inconsistent with this service."""


@dataclass(frozen=True, slots=True)
class SessionGallery:
    device_id: UUID
    session_id: UUID
    status: str
    generated_at: datetime
    session_ends_at: datetime
    expires_at: datetime
    model_name: str
    model_version: str
    entries: tuple[GalleryEntry, ...] = field(repr=False)

    def __repr__(self) -> str:
        return (
            "SessionGallery("
            f"device_id={self.device_id!r}, session_id={self.session_id!r}, "
            f"status={self.status!r}, entry_count={len(self.entries)}, "
            f"model_name={self.model_name!r}, model_version={self.model_version!r})"
        )


class SessionGalleryCache:
    """Thread-safe, in-memory-only active roster/template snapshots."""

    def __init__(self, *, max_age_seconds: float = 300.0) -> None:
        if not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be finite and positive.")
        self._max_age = timedelta(seconds=max_age_seconds)
        self._entries: dict[tuple[UUID, UUID], SessionGallery] = {}
        self._lock = threading.RLock()

    def install(
        self,
        gallery: SessionGallery,
        *,
        now: datetime | None = None,
    ) -> None:
        current = _utc(now or datetime.now(UTC), "now")
        generated_at = _utc(gallery.generated_at, "generated_at")
        ends_at = _utc(gallery.session_ends_at, "session_ends_at")
        expires_at = _utc(gallery.expires_at, "expires_at")
        if gallery.status != "active":
            raise GalleryCacheError("Only active sessions can enter the AI cache.")
        if not gallery.model_name.strip() or not gallery.model_version.strip():
            raise GalleryCacheError("Gallery model name and version are required.")
        if generated_at > current or ends_at <= current:
            raise GalleryCacheError("Gallery timestamps are expired or in the future.")
        safe_expiry = min(expires_at, ends_at, generated_at + self._max_age)
        if safe_expiry <= current:
            raise GalleryCacheError("Gallery is expired.")
        if not gallery.entries:
            raise GalleryCacheError("An active session gallery cannot be empty.")
        embedding_dimensions: int | None = None
        for entry in gallery.entries:
            embedding = entry.embedding
            if (
                embedding.model_name != gallery.model_name
                or embedding.model_version != gallery.model_version
                or not embedding.normalized
            ):
                raise GalleryCacheError("Gallery contains an incompatible template.")
            if embedding_dimensions is None:
                embedding_dimensions = len(embedding.values)
            elif len(embedding.values) != embedding_dimensions:
                raise GalleryCacheError("Gallery template dimensions do not match.")
            norm = math.sqrt(sum(value * value for value in embedding.values))
            if not math.isfinite(norm) or not math.isclose(norm, 1.0, abs_tol=1e-3):
                raise GalleryCacheError("Gallery templates must be L2 normalized.")
        installed = SessionGallery(
            device_id=gallery.device_id,
            session_id=gallery.session_id,
            status="active",
            generated_at=generated_at,
            session_ends_at=ends_at,
            expires_at=safe_expiry,
            model_name=gallery.model_name,
            model_version=gallery.model_version,
            entries=gallery.entries,
        )
        with self._lock:
            self._entries[(installed.device_id, installed.session_id)] = installed

    def get(
        self,
        device_id: UUID,
        session_id: UUID,
        *,
        now: datetime | None = None,
    ) -> SessionGallery | None:
        current = _utc(now or datetime.now(UTC), "now")
        key = (device_id, session_id)
        with self._lock:
            gallery = self._entries.get(key)
            if gallery is None:
                return None
            if (
                gallery.status != "active"
                or gallery.expires_at <= current
                or gallery.session_ends_at <= current
            ):
                self._entries.pop(key, None)
                return None
            return gallery

    def invalidate(self, device_id: UUID, session_id: UUID) -> bool:
        with self._lock:
            return self._entries.pop((device_id, session_id), None) is not None

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class SessionGalleryProvider(Protocol):
    """Trusted adapter for loading an active roster snapshot on a cache miss."""

    async def fetch_active_session_gallery(
        self,
        device_id: UUID,
        session_id: UUID,
    ) -> SessionGallery | None: ...


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise GalleryCacheError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def normalized_embedding(
    *,
    values: tuple[float, ...],
    model_name: str,
    model_version: str,
) -> FaceEmbedding:
    """Small factory for trusted, already-normalized cache adapters/tests."""
    return FaceEmbedding(
        values=values,
        model_name=model_name,
        model_version=model_version,
        normalized=True,
    )
