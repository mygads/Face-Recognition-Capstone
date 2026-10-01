from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
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
        self._camera_status_provider: Callable[[], str] | None = None
        self._client = client or httpx.Client(
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
            follow_redirects=False,
        )
        self._owns_client = client is None

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
        self._request(
            "POST",
            f"/api/v1/devices/{self.device_id}/heartbeat",
            payload=payload or None,
        )

    def set_camera_status_provider(self, provider: Callable[[], str]) -> None:
        self._camera_status_provider = provider

    def fetch_active_session_cache(self) -> dict[str, Any]:
        path = self._cache_path.format(device_id=self.device_id)
        response = self._request("GET", path)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiCallError(response.status_code, retryable=False) from exc
        if not isinstance(payload, dict):
            raise ApiCallError(response.status_code, retryable=False)
        return payload

    def submit_recognition_event(self, payload: dict[str, object]) -> None:
        self._request(
            "POST",
            "/api/v1/attendance/recognition-events",
            payload=payload,
        )


def cache_provider_for(client: CoreApiClient) -> Callable[[], dict[str, Any]]:
    """Expose the edge cache endpoint as an injectable source for service tests."""
    return client.fetch_active_session_cache
