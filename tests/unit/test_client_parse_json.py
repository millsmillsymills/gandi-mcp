"""Tests for BaseGandiClient._parse_json empty-body handling."""

from __future__ import annotations

import httpx
import pytest
import respx

from gandi_mcp.clients.base import BaseGandiClient
from gandi_mcp.errors import GandiError


class TestEmptyBodyParsing:
    @pytest.mark.asyncio
    async def test_204_empty_returns_empty_dict(self) -> None:
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=1)
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.delete("/v5/livedns/domains/example.com/records").mock(return_value=httpx.Response(204))
            result = await client.delete("/v5/livedns/domains/example.com/records")
            assert result == {}
        await client.close()

    @pytest.mark.asyncio
    async def test_200_empty_raises_instead_of_masking_as_empty(self) -> None:
        """A 200 with no body usually means a proxy stripped it — don't silently
        pretend the API returned an empty object."""
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=1)
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.get("/v5/organization/user-info").mock(return_value=httpx.Response(200))
            with pytest.raises(GandiError, match="Empty response body from HTTP 200"):
                await client.get("/v5/organization/user-info")
        await client.close()

    @pytest.mark.asyncio
    async def test_201_empty_also_raises(self) -> None:
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=1)
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.post("/v5/domain/domains").mock(return_value=httpx.Response(201))
            with pytest.raises(GandiError, match="Empty response body from HTTP 201"):
                await client.post("/v5/domain/domains", json={})
        await client.close()
