"""Tests for BaseGandiClient httpx exception → GandiError mapping."""

from __future__ import annotations

import httpx
import pytest
import respx

from gandi_mcp.clients.base import BaseGandiClient
from gandi_mcp.errors import GandiConnectionError


class TestHttpxErrorMapping:
    """Non-timeout/non-connect httpx errors must map to GandiConnectionError.

    Previously only TimeoutException and ConnectError were mapped. Real-world
    networks produce ReadError, RemoteProtocolError, PoolTimeout, etc. —
    those used to bubble up as raw httpx types and surface as "Unexpected
    error" through handle_client_error, hiding the real cause.
    """

    @pytest.mark.asyncio
    async def test_remote_protocol_error_maps_to_connection_error(self) -> None:
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=1)
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.get("/v5/organization/user-info").mock(side_effect=httpx.RemoteProtocolError("server hung up"))
            with pytest.raises(GandiConnectionError, match="server hung up"):
                await client.get("/v5/organization/user-info")
        await client.close()

    @pytest.mark.asyncio
    async def test_read_error_maps_to_connection_error(self) -> None:
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=1)
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.get("/v5/organization/user-info").mock(side_effect=httpx.ReadError("reset by peer"))
            with pytest.raises(GandiConnectionError, match="reset by peer"):
                await client.get("/v5/organization/user-info")
        await client.close()
