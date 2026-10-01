from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import httpx

from presensi_edge_agent.config import ApiSettings


class ApiCallError(RuntimeError):
    """Transport failure without request, response body, or credential content."""

    def __init__(self, status_code: int | None, *, retryable: bool) -> None:
        self.status_code = status_code
        self.retryable = retryable
        label = "network error" if status_code is None else f"HTTP {status_code}"
        super().__init__(label)


@dataclass(frozen=True, slots=True)
class ApiHealth:
    reachable: bool
    status_code: int | None


class CoreApiClient:
    def __init__(
        self,
        settings: ApiSettings,
        device_id: UUID,
        token_provider: Callable[[], str | None],
        *,
        session_cache_path: str | None = None,
        heartbeat_metadata: dict[str, object] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self.device_id = device_id
        self._token_provider = token_provider
        self._cache_path = session_cache_path or settings.cache_path
        self._heartbeat_metadata = heartbeat_metadata or {}
        self._last_heartbeat_expiry: datetime | None = None
        self._camera_status_provider: Callable[[], str] | None = None
        self._client = client or httpx.Client(
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
            follow_redirects=False,
        )
        self._owns_client = client is None
        self._can_rotate_credential = (
            settings.token_file is not None
            and not os.environ.get("PRESENSI_EDGE_API_TOKEN", "").strip()
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        authenticated: bool = True,
    ) -> httpx.Response:
        headers: dict[str, str] = {}
        if authenticated:
            token = self._token_provider()
            if not token:
                raise ApiCallError(401, retryable=True)
            headers["Authorization"] = f"Bearer {token}"
            headers["X-Device-ID"] = str(self.device_id)
        try:
            response = self._client.request(
                method,
                path,
                json=payload,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise ApiCallError(None, retryable=True) from exc
        except httpx.RequestError as exc:
            raise ApiCallError(None, retryable=True) from exc
        if response.status_code >= 400:
            status_code = response.status_code
            retryable = status_code in {401, 403, 408, 425, 429} or status_code >= 500
            raise ApiCallError(status_code, retryable=retryable)
        return response

    def health(self) -> ApiHealth:
        try:
            response = self._request("GET", "/health", authenticated=False)
        except ApiCallError as exc:
            return ApiHealth(reachable=False, status_code=exc.status_code)
        return ApiHealth(reachable=True, status_code=response.status_code)

    def heartbeat(self) -> None:
        payload = dict(self._heartbeat_metadata)
        if self._camera_status_provider is not None:
            payload["camera_status"] = self._camera_status_provider()
        response = self._request(
            "POST",
            f"/api/v1/devices/{self.device_id}/device-heartbeat",
            payload=payload or None,
        )
        expiry: datetime | None = None
        try:
            response_payload = response.json()
            raw_expiry = (
                response_payload.get("credential_expires_at")
                if isinstance(response_payload, dict)
                else None
            )
            if isinstance(raw_expiry, str):
                parsed = datetime.fromisoformat(raw_expiry.replace("Z", "+00:00"))
                if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                    expiry = parsed.astimezone(UTC)
        except (ValueError, TypeError):
            expiry = None
        self._last_heartbeat_expiry = expiry
        # Renew automatically while the current device credential is still valid.
        # The previous credential remains accepted briefly if writing the new file
        # succeeds but a retry is needed.
        if (
            self._can_rotate_credential
            and expiry is not None
            and expiry <= datetime.now(UTC) + timedelta(days=7)
        ):
            response = self._request(
                "POST", f"/api/v1/devices/{self.device_id}/credentials/renew"
            )
            self._persist_rotated_credential(response.json())

    def set_camera_status_provider(self, provider: Callable[[], str]) -> None:
        self._camera_status_provider = provider

    def fetch_active_session_cache(self) -> dict[str, Any]:
        version = str(self._heartbeat_metadata.get("model_version", ""))
        path = self._cache_path.format(
            device_id=self.device_id,
            model_name="opencv-zoo-sface",
            model_version=version,
        )
        if "model_name=" not in path or "model_version=" not in path:
            separator = "&" if "?" in path else "?"
            path = (
                f"{path}{separator}model_name=opencv-zoo-sface&model_version={version}"
            )
        response = self._request("GET", path)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiCallError(response.status_code, retryable=False) from exc
        if not isinstance(payload, dict):
            raise ApiCallError(response.status_code, retryable=False)
        return payload

    def discover_active_sessions(self) -> list[dict[str, Any]]:
        response = self._request(
            "GET", f"/api/v1/devices/{self.device_id}/active-sessions"
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiCallError(response.status_code, retryable=False) from exc
        if not isinstance(payload, list) or not all(
            isinstance(item, dict) for item in payload
        ):
            raise ApiCallError(response.status_code, retryable=False)
        return cast(list[dict[str, Any]], payload)

    def submit_recognition_event(self, payload: dict[str, object]) -> None:
        self._request(
            "POST",
            f"/api/v1/devices/{self.device_id}/recognition-events",
            payload=payload,
        )

    def _persist_rotated_credential(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        token = payload.get("token")
        expires_at = payload.get("expires_at")
        if not isinstance(token, str) or not token or not isinstance(expires_at, str):
            return
        if not token or not expires_at:
            return
        path = self.settings.token_file
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as output:
                output.write(token + "\n")
                output.flush()
                os.fsync(output.fileno())
                temporary_path = Path(output.name)
            if os.name != "nt":
                temporary_path.chmod(0o600)
            os.replace(temporary_path, path)
        except OSError:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise ApiCallError(None, retryable=True)


def cache_provider_for(client: CoreApiClient) -> Callable[[], dict[str, Any]]:
    """Expose the edge cache endpoint as an injectable source for service tests."""
    return client.fetch_active_session_cache
