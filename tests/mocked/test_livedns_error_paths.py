"""Error-path coverage for LiveDNS tools.

One test per ``gandi_livedns_*`` tool that exercises the
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

from gandi_mcp.tools.livedns import register_livedns_tools

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
    register_livedns_tools(s)
    return s


@pytest.mark.mocked
class TestLiveDnsReadErrorPaths:
    async def test_list_domains_maps_401_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.get("/v5/livedns/domains").mock(return_value=httpx.Response(401, json={"cause": "Unauthorized"}))
        handler = await _get_handler(server, "gandi_livedns_list_domains")
        with pytest.raises(ToolError):
            await handler(ctx)

    async def test_get_domain_maps_404_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.get("/v5/livedns/domains/example.com").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_livedns_get_domain")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")

    async def test_list_nameservers_maps_404_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.get("/v5/livedns/domains/example.com/nameservers").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_livedns_list_nameservers")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")

    async def test_list_rrtypes_maps_429_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.get("/v5/livedns/dns/rrtypes").mock(return_value=httpx.Response(429, text="slow down"))
        handler = await _get_handler(server, "gandi_livedns_list_rrtypes")
        with pytest.raises(ToolError):
            await handler(ctx)

    async def test_list_records_maps_404_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.get("/v5/livedns/domains/example.com/records").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_livedns_list_records")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")

    async def test_list_dnssec_keys_maps_404_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.get("/v5/livedns/domains/example.com/keys").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_livedns_list_dnssec_keys")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")


@pytest.mark.mocked
class TestLiveDnsWriteErrorPaths:
    async def test_add_domain_maps_409_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.post("/v5/livedns/domains").mock(
            return_value=httpx.Response(409, json={"cause": "already exists"}),
        )
        handler = await _get_handler(server, "gandi_livedns_add_domain")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")

    async def test_update_domain_maps_400_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.patch("/v5/livedns/domains/example.com").mock(
            return_value=httpx.Response(400, json={"cause": "invalid"}),
        )
        handler = await _get_handler(server, "gandi_livedns_update_domain")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com", automatic_snapshots=True)

    async def test_create_record_maps_409_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.post("/v5/livedns/domains/example.com/records").mock(
            return_value=httpx.Response(409, json={"cause": "already exists"}),
        )
        handler = await _get_handler(server, "gandi_livedns_create_record")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com", name="www", rrset_type="A", values=["192.0.2.1"])

    async def test_replace_record_maps_400_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.put("/v5/livedns/domains/example.com/records/www/A").mock(
            return_value=httpx.Response(400, json={"cause": "invalid"}),
        )
        handler = await _get_handler(server, "gandi_livedns_replace_record")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com", name="www", rrset_type="A", values=["192.0.2.1"])

    async def test_replace_zone_maps_400_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.put("/v5/livedns/domains/example.com/records").mock(
            return_value=httpx.Response(400, json={"cause": "invalid"}),
        )
        handler = await _get_handler(server, "gandi_livedns_replace_zone")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com", items=[])

    async def test_delete_record_maps_404_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.delete("/v5/livedns/domains/example.com/records/www/A").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_livedns_delete_record")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com", name="www", rrset_type="A")

    async def test_delete_all_records_maps_404_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.delete("/v5/livedns/domains/example.com/records").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_livedns_delete_all_records")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")

    async def test_create_dnssec_key_maps_400_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.post("/v5/livedns/domains/example.com/keys").mock(
            return_value=httpx.Response(400, json={"cause": "invalid"}),
        )
        handler = await _get_handler(server, "gandi_livedns_create_dnssec_key")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")

    async def test_delete_dnssec_key_maps_404_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.delete("/v5/livedns/domains/example.com/keys/k1").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_livedns_delete_dnssec_key")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com", key_id="k1")
