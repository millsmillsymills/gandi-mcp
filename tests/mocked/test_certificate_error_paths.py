"""Error-path coverage for certificate tools.

One test per ``gandi_cert_*`` tool that exercises the
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

from gandi_mcp.tools.certificate import register_certificate_tools

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
    register_certificate_tools(s)
    return s


@pytest.mark.mocked
class TestCertErrorPaths:
    async def test_list_maps_401_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.get("/v5/certificate/issued-certs").mock(
            return_value=httpx.Response(401, json={"cause": "Unauthorized"}),
        )
        handler = await _get_handler(server, "gandi_cert_list")
        with pytest.raises(ToolError):
            await handler(ctx)

    async def test_get_maps_404_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.get("/v5/certificate/issued-certs/cert-uuid").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_cert_get")
        with pytest.raises(ToolError):
            await handler(ctx, cert_id="cert-uuid")

    async def test_revoke_maps_409_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.delete("/v5/certificate/issued-certs/cert-uuid").mock(
            return_value=httpx.Response(409, json={"cause": "already revoked"}),
        )
        handler = await _get_handler(server, "gandi_cert_revoke")
        with pytest.raises(ToolError):
            await handler(ctx, cert_id="cert-uuid")

    async def test_issue_maps_402_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.post("/v5/certificate/issued-certs").mock(
            return_value=httpx.Response(402, json={"cause": "payment required"}),
        )
        handler = await _get_handler(server, "gandi_cert_issue")
        with pytest.raises(ToolError):
            await handler(ctx, data={"cn": "example.com", "package": "std", "duration": 1})

    async def test_renew_maps_400_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.post("/v5/certificate/issued-certs/cert-uuid/renew").mock(
            return_value=httpx.Response(400, json={"cause": "invalid CSR"}),
        )
        handler = await _get_handler(server, "gandi_cert_renew")
        with pytest.raises(ToolError):
            await handler(ctx, cert_id="cert-uuid", data={"csr": "...", "duration": 1})
