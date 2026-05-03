"""Mocked-integration tests for billing tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest
from fastmcp import FastMCP

from gandi_mcp.tools.billing import register_billing_tools

if TYPE_CHECKING:
    from unittest.mock import AsyncMock


async def _get_handler(server: FastMCP, name: str) -> Any:
    """Pull a registered tool's underlying async handler by name.

    FastMCP exposes ``get_tool(name)`` as the public lookup; it returns a
    ``FunctionTool`` whose ``.fn`` attribute is the original async handler.
    Subsequent mocked-tool tasks (1.7+) copy this helper verbatim.
    """
    tool = await server.get_tool(name)
    return tool.fn


@pytest.mark.mocked
class TestBillingGetInfo:
    async def test_calls_correct_endpoint_and_returns_payload(self, ctx: AsyncMock, respx_mock: Any) -> None:
        payload = {"prepaid": {"amount": "100.00", "currency": "USD"}, "annual_business_costs": "0"}
        route = respx_mock.get("/v5/billing/info").mock(return_value=httpx.Response(200, json=payload))

        server = FastMCP(name="t")
        register_billing_tools(server)
        handler = await _get_handler(server, "billing_get_info")
        result = await handler(ctx)

        assert route.called
        assert result == payload


@pytest.mark.mocked
class TestBillingGetInfoForOrg:
    async def test_passes_sharing_id_in_path(self, ctx: AsyncMock, respx_mock: Any) -> None:
        payload = {"sharing_id": "org-uuid", "prepaid": {"amount": "0", "currency": "USD"}}
        route = respx_mock.get("/v5/billing/info/org-uuid").mock(return_value=httpx.Response(200, json=payload))

        server = FastMCP(name="t")
        register_billing_tools(server)
        handler = await _get_handler(server, "billing_get_info_for_org")
        result = await handler(ctx, sharing_id="org-uuid")

        assert route.called
        assert result == payload

    async def test_url_encodes_sharing_id(self, ctx: AsyncMock, respx_mock: Any) -> None:
        # Sharing IDs are UUIDs in practice but the encoder must handle reserved chars.
        route = respx_mock.get("/v5/billing/info/org%2Fweird").mock(return_value=httpx.Response(200, json={}))
        server = FastMCP(name="t")
        register_billing_tools(server)
        handler = await _get_handler(server, "billing_get_info_for_org")
        await handler(ctx, sharing_id="org/weird")
        assert route.called


@pytest.mark.mocked
class TestBillingGetPriceCatalog:
    async def test_passes_product_type_in_path_and_filters_none_params(self, ctx: AsyncMock, respx_mock: Any) -> None:
        payload = {"products": [{"name": "com", "prices": []}]}
        route = respx_mock.get(
            "/v5/billing/price/domain",
            params={"currency": "USD"},
        ).mock(return_value=httpx.Response(200, json=payload))

        server = FastMCP(name="t")
        register_billing_tools(server)
        handler = await _get_handler(server, "billing_get_price_catalog")
        result = await handler(ctx, product_type="domain", currency="USD", country=None, grid=None)

        assert route.called
        assert result == payload
