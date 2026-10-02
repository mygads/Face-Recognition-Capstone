from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx


class ConfigurationSyncError(RuntimeError):
    """A managed configuration could not be fetched or safely decoded."""


class CoreApiConfigurationClient:
    def __init__(self, base_url: str, token: str, *, timeout_seconds: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    async def fetch(self) -> tuple[int, dict[str, object]]:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    "/api/v1/internal/ai-central-configuration",
                    headers={"Authorization": f"Bearer {self.token}"},
                )
        except httpx.RequestError as exc:
            raise ConfigurationSyncError("Core API is unreachable.") from exc
        if response.status_code != 200:
            raise ConfigurationSyncError("Core API rejected configuration sync.")
        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise ConfigurationSyncError(
                "Core API returned invalid configuration."
            ) from exc
        if not isinstance(payload, Mapping):
            raise ConfigurationSyncError("Core API returned invalid configuration.")
        revision = payload.get("revision")
        settings = payload.get("settings")
        if type(revision) is not int or revision < 0 or not isinstance(settings, dict):
            raise ConfigurationSyncError("Core API returned invalid configuration.")
        return revision, settings
