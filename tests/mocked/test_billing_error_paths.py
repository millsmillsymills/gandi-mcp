"""Error-path coverage for billing tools.

One test per ``gandi_billing_*`` tool that exercises the
``except Exception as e: handle_client_error(e)`` line by mocking the HTTP
boundary to return a non-2xx status.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools.function_tool import FunctionTool

from gandi_mcp.tools.billing import register_billing_tools

if TYPE_CHECKING:
    from unittest.mock import AsyncMock


async def _get_handler(server: FastMCP, name: str) -> Any:
    tool = await server.get_tool(name)
    assert tool is not None, f"tool {name!r} not registered"
    assert isinstance(tool, FunctionTool), f"tool {name!r} is not a FunctionTool"
    return tool.fn


@pytest.fixture
def server() -> FastMCP:
    s = FastMCP(name="t")
    register_billing_tools(s)
    return s


@pytest.mark.mocked
class TestBillingErrorPaths:
    async def test_get_info_maps_401_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.get("/v5/billing/info").mock(return_value=httpx.Response(401, json={"cause": "Unauthorized"}))
        handler = await _get_handler(server, "gandi_billing_get_info")
        with pytest.raises(ToolError):
            await handler(ctx)

    async def test_get_info_for_org_maps_404_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.get("/v5/billing/info/org-uuid").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_billing_get_info_for_org")
        with pytest.raises(ToolError):
            await handler(ctx, sharing_id="org-uuid")

    async def test_get_price_catalog_maps_429_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.get("/v5/billing/price/domain").mock(
            return_value=httpx.Response(429, text="slow down", headers={"retry-after": "5"}),
        )
        handler = await _get_handler(server, "gandi_billing_get_price_catalog")
        with pytest.raises(ToolError):
            await handler(ctx, product_type="domain")
