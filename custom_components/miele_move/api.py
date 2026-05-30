"""Client for the Miele MOVE REST API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession, ClientTimeout
from yarl import URL

from .errors import (
    MieleMoveApiError,
    MieleMoveAuthError,
    MieleMoveRateLimitError,
    classify_response,
)

REQUEST_TIMEOUT = ClientTimeout(total=30)

__all__ = [
    "MieleMoveApiClient",
    "MieleMoveApiError",
    "MieleMoveAuthError",
    "MieleMoveRateLimitError",
]


@dataclass(slots=True)
class MieleMoveApiClient:
    """Small async client for Miele MOVE."""

    session: ClientSession
    api_key: str
    base_url: str
    accept_language: str

    async def async_get_devices(self) -> Any:
        """Return all devices visible to the API key."""
        return await self._request("/api/move/v1/devices")

    async def async_get_device(self, device_id: str) -> Any:
        """Return details for one device."""
        return await self._request(f"/api/move/v1/devices/{device_id}")

    async def async_get_executions(self, fab_nr: str) -> Any:
        """Return program executions for one device."""
        return await self._request(f"/api/move/v1/devices/{fab_nr}/executions")

    async def async_get_execution_detail(self, fab_nr: str, execution_id: str) -> Any:
        """Return one program execution detail."""
        return await self._request(
            f"/api/move/v1/devices/{fab_nr}/executions/{execution_id}"
        )

    async def _request(self, path: str) -> Any:
        """Perform one authenticated JSON request."""
        url = URL(self.base_url).with_path(path)
        headers = {
            "Accept": "application/json",
            "Accept-Language": self.accept_language,
            "X-Api-Key": self.api_key,
        }

        try:
            async with self.session.get(
                url, headers=headers, timeout=REQUEST_TIMEOUT
            ) as response:
                exc = classify_response(
                    response.status, response.headers.get("Retry-After")
                )
                if exc is not None:
                    raise exc
                if response.content_type == "application/json":
                    return await response.json()
                return await response.text()
        except MieleMoveApiError:
            raise
        except ClientResponseError as err:
            raise MieleMoveApiError(
                f"Miele MOVE API returned HTTP {err.status} for {path}"
            ) from err
        except ClientError as err:
            raise MieleMoveApiError(f"Could not reach Miele MOVE API: {err}") from err
