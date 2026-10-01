from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import httpx

from presensi_ai_service.gallery_cache import (
    SessionGallery,
    normalized_embedding,
)
from recognition_core.domain import GalleryEntry


class GalleryProviderError(RuntimeError):
    def __init__(self, status_code: int | None) -> None:
        self.status_code = status_code
        super().__init__("Core API gallery provider request failed.")


class CoreApiGalleryProvider:
    """Fetches session-scoped templates through the device-authenticated Core API."""

    def __init__(
        self,
        base_url: str,
        *,
        model_name: str,
        model_version: str,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.model_version = model_version
        self.timeout_seconds = timeout_seconds

    async def validate_device(
        self, device_id: UUID, *, device_token: str | None
    ) -> bool:
        response = await self._get(
            f"/api/v1/devices/{device_id}/device-status",
            device_id=device_id,
            device_token=device_token,
        )
        if response.status_code != 200:
            return False
        payload = response.json()
        return (
            isinstance(payload, dict)
            and payload.get("device_id") == str(device_id)
            and payload.get("active") is True
        )

    async def validate_device_session(
        self,
        device_id: UUID,
        session_id: UUID,
        *,
        device_token: str | None,
    ) -> bool:
        response = await self._get(
            f"/api/v1/devices/{device_id}/active-sessions",
            device_id=device_id,
            device_token=device_token,
        )
        if response.status_code != 200:
            return False
        payload = response.json()
        return isinstance(payload, list) and any(
            isinstance(row, dict)
            and row.get("session_id") == str(session_id)
            and row.get("session_status") == "active"
            for row in payload
        )

    async def fetch_active_session_gallery(
        self,
        device_id: UUID,
        session_id: UUID,
        *,
        device_token: str | None = None,
    ) -> SessionGallery | None:
        response = await self._get(
            f"/api/v1/devices/{device_id}/active-session-cache",
            device_id=device_id,
            device_token=device_token,
            params={
                "session_id": str(session_id),
                "model_name": self.model_name,
                "model_version": self.model_version,
            },
        )
        if response.status_code in {404, 409}:
            return None
        if response.status_code != 200:
            raise GalleryProviderError(response.status_code)
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Provider response must be an object.")
            if (
                payload.get("device_id") != str(device_id)
                or payload.get("session_id") != str(session_id)
                or payload.get("session_status") != "active"
                or payload.get("model_name") != self.model_name
                or payload.get("model_version") != self.model_version
            ):
                raise ValueError("Provider response scope is invalid.")
            entries = []
            roster = payload["roster"]
            if not isinstance(roster, list):
                raise ValueError("Provider response roster is invalid.")
            for student in roster:
                student_id = UUID(str(student["student_id"]))
                templates = student["templates"]
                if not isinstance(templates, list):
                    raise ValueError("Provider response templates are invalid.")
                for template in templates:
                    if (
                        template.get("model_name") != self.model_name
                        or template.get("model_version") != self.model_version
                        or template.get("normalized") is not True
                    ):
                        raise ValueError("Provider response model is invalid.")
                    values = tuple(float(value) for value in template["values"])
                    entries.append(
                        _gallery_entry(
                            student_id,
                            values,
                            self.model_name,
                            self.model_version,
                        )
                    )
            return SessionGallery(
                device_id=device_id,
                session_id=session_id,
                status="active",
                generated_at=_datetime(payload["generated_at"]),
                session_ends_at=_datetime(payload["session_ends_at"]),
                expires_at=_datetime(payload["expires_at"]),
                model_name=self.model_name,
                model_version=self.model_version,
                entries=tuple(entries),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GalleryProviderError(502) from exc

    async def _get(
        self,
        path: str,
        *,
        device_id: UUID,
        device_token: str | None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        if not device_token or len(device_token) < 32 or not device_token.isascii():
            raise GalleryProviderError(401)
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    path,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {device_token}",
                        "X-Device-ID": str(device_id),
                    },
                )
        except httpx.RequestError as exc:
            raise GalleryProviderError(None) from exc
        if response.status_code == 401:
            raise GalleryProviderError(401)
        if response.status_code >= 500:
            raise GalleryProviderError(response.status_code)
        return response


def _gallery_entry(
    student_id: UUID,
    values: tuple[float, ...],
    model_name: str,
    model_version: str,
) -> GalleryEntry:
    return GalleryEntry(
        student_id=student_id,
        embedding=normalized_embedding(
            values=values,
            model_name=model_name,
            model_version=model_version,
        ),
    )


def _datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Provider timestamp is missing.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Provider timestamp must include a timezone.")
    return parsed.astimezone(UTC)
