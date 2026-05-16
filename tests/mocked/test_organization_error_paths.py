"""Error-path coverage for organization tools.

One test per ``gandi_org_*`` tool that exercises the
``except Exception as e: handle_client_error(e)`` line by mocking the HTTP
boundary to return a non-2xx status. The body's specific shape doesn't matter —
``handle_client_error`` will translate any ``GandiError`` into a ``ToolError``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools.function_tool import FunctionTool

from gandi_mcp.tools.organization import register_organization_tools

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
    register_organization_tools(s)
    return s


@pytest.mark.mocked
class TestOrgErrorPaths:
    async def test_get_user_info_maps_5xx_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.get("/v5/organization/user-info").mock(return_value=httpx.Response(500, text="boom"))
        handler = await _get_handler(server, "gandi_org_get_user_info")
        with pytest.raises(ToolError):
            await handler(ctx)

    async def test_list_organizations_maps_401_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.get("/v5/organization/organizations").mock(
            return_value=httpx.Response(401, json={"cause": "Unauthorized"}),
        )
        handler = await _get_handler(server, "gandi_org_list_organizations")
        with pytest.raises(ToolError):
            await handler(ctx)

    async def test_get_organization_maps_404_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.get("/v5/organization/organizations/org-uuid").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_org_get_organization")
        with pytest.raises(ToolError):
            await handler(ctx, org_id="org-uuid")

    async def test_list_customers_maps_403_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.get("/v5/organization/organizations/org-uuid/customers").mock(
            return_value=httpx.Response(403, json={"cause": "forbidden"}),
        )
        handler = await _get_handler(server, "gandi_org_list_customers")
        with pytest.raises(ToolError):
            await handler(ctx, org_id="org-uuid")

    async def test_get_customer_maps_404_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.get("/v5/organization/organizations/org-uuid/customers/cust-uuid").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_org_get_customer")
        with pytest.raises(ToolError):
            await handler(ctx, org_id="org-uuid", customer_id="cust-uuid")
