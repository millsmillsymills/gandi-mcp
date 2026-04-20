"""Parameterised tests for BaseGandiClient._raise_for_status.

Closes the coverage gap identified in #13: handle_client_error (the second
half of the error pipeline) was tested but the HTTP-status → typed-exception
dispatch itself wasn't, so a regression reordering status checks or
introducing a wrong mapping would pass CI silently.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from gandi_mcp.clients.base import BaseGandiClient
from gandi_mcp.errors import (
    GandiAuthError,
    GandiBadRequestError,
    GandiConflictError,
    GandiError,
    GandiNotFoundError,
    GandiRateLimitError,
    GandiServerError,
)


@pytest.fixture
def client() -> BaseGandiClient:
    return BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=1)


STATUS_CASES: list[tuple[int, type[GandiError]]] = [
    (400, GandiBadRequestError),
    (401, GandiAuthError),
    (403, GandiAuthError),
    (404, GandiNotFoundError),
    (409, GandiConflictError),
    (429, GandiRateLimitError),
    (500, GandiServerError),
    (502, GandiServerError),
    (503, GandiServerError),
    # Odd status → catch-all GandiError (but not any of the typed subclasses)
    (418, GandiError),
]


class TestStatusCodeMapping:
    @pytest.mark.parametrize(("status", "exc_type"), STATUS_CASES)
    @pytest.mark.asyncio
    async def test_status_maps_to_expected_exception(
        self, client: BaseGandiClient, status: int, exc_type: type[GandiError]
    ) -> None:
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.get("/v5/organization/user-info").mock(
                return_value=httpx.Response(status, text="error body"),
            )
            with pytest.raises(exc_type) as exc_info:
                await client.get("/v5/organization/user-info")
            assert exc_info.value.status_code == status
            # Body is preserved on the message (truncated to 500 chars).
            assert "error body" in str(exc_info.value)
        await client.close()

    @pytest.mark.asyncio
    async def test_418_maps_to_generic_not_server_error(self, client: BaseGandiClient) -> None:
        """A catch-all status must NOT accidentally promote to GandiServerError."""
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.get("/v5/organization/user-info").mock(return_value=httpx.Response(418))
            with pytest.raises(GandiError) as exc_info:
                await client.get("/v5/organization/user-info")
            assert not isinstance(exc_info.value, GandiServerError)
        await client.close()

    @pytest.mark.asyncio
    async def test_2xx_does_not_raise(self, client: BaseGandiClient) -> None:
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.get("/v5/organization/user-info").mock(
                return_value=httpx.Response(200, json={"ok": True}),
            )
            result = await client.get("/v5/organization/user-info")
            assert result == {"ok": True}
        await client.close()
