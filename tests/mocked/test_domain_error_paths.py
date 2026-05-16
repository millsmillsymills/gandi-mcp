"""Error-path coverage for domain tools.

One test per ``gandi_domain_*`` tool that exercises the
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

from gandi_mcp.tools.domain import register_domain_tools

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
    register_domain_tools(s)
    return s


@pytest.mark.mocked
class TestDomainReadErrorPaths:
    async def test_list_domains_maps_401_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.get("/v5/domain/domains").mock(
            return_value=httpx.Response(401, json={"cause": "Unauthorized"}),
        )
        handler = await _get_handler(server, "gandi_domain_list_domains")
        with pytest.raises(ToolError):
            await handler(ctx)

    async def test_get_domain_maps_404_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.get("/v5/domain/domains/example.com").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_domain_get_domain")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")

    async def test_get_status_maps_404_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.get("/v5/domain/domains/example.com").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_domain_get_status")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")

    async def test_check_availability_maps_400_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.get("/v5/domain/check").mock(
            return_value=httpx.Response(400, json={"cause": "invalid name"}),
        )
        handler = await _get_handler(server, "gandi_domain_check_availability")
        with pytest.raises(ToolError):
            await handler(ctx, name="example.com")

    async def test_get_claims_maps_404_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.get("/v5/domain/domains/example.com/claims").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_domain_get_claims")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")

    async def test_get_contacts_maps_404_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.get("/v5/domain/domains/example.com/contacts").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_domain_get_contacts")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")

    async def test_get_nameservers_maps_404_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.get("/v5/domain/domains/example.com/nameservers").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_domain_get_nameservers")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")

    async def test_list_glue_records_maps_404_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.get("/v5/domain/domains/example.com/hosts").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_domain_list_glue_records")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")

    async def test_get_glue_record_maps_404_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.get("/v5/domain/domains/example.com/hosts/ns1").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_domain_get_glue_record")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com", name="ns1")

    async def test_list_dnssec_keys_maps_404_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.get("/v5/domain/domains/example.com/dnskeys").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_domain_list_dnssec_keys")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")

    async def test_get_renew_info_maps_404_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.get("/v5/domain/domains/example.com/renew").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_domain_get_renew_info")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")

    async def test_get_transferin_info_maps_404_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.get("/v5/domain/transferin/example.com").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_domain_get_transferin_info")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")

    async def test_get_ownership_change_status_maps_404_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.get("/v5/domain/changeowner/example.com").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_domain_get_ownership_change_status")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")


@pytest.mark.mocked
class TestDomainWriteErrorPaths:
    async def test_set_autorenew_maps_400_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.patch("/v5/domain/domains/example.com/autorenew").mock(
            return_value=httpx.Response(400, json={"cause": "invalid"}),
        )
        handler = await _get_handler(server, "gandi_domain_set_autorenew")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com", enabled=True)

    async def test_update_contacts_maps_400_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.patch("/v5/domain/domains/example.com/contacts").mock(
            return_value=httpx.Response(400, json={"cause": "invalid contact"}),
        )
        handler = await _get_handler(server, "gandi_domain_update_contacts")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com", admin={"given": "Jane"})

    async def test_set_nameservers_maps_400_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.put("/v5/domain/domains/example.com/nameservers").mock(
            return_value=httpx.Response(400, json={"cause": "invalid"}),
        )
        handler = await _get_handler(server, "gandi_domain_set_nameservers")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com", nameservers=["ns1.example.com"])

    async def test_create_glue_record_maps_409_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.post("/v5/domain/domains/example.com/hosts").mock(
            return_value=httpx.Response(409, json={"cause": "already exists"}),
        )
        handler = await _get_handler(server, "gandi_domain_create_glue_record")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com", name="ns1", ips=["192.0.2.1"])

    async def test_update_glue_record_maps_400_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.put("/v5/domain/domains/example.com/hosts/ns1").mock(
            return_value=httpx.Response(400, json={"cause": "invalid"}),
        )
        handler = await _get_handler(server, "gandi_domain_update_glue_record")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com", name="ns1", ips=["192.0.2.99"])

    async def test_delete_glue_record_maps_404_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.delete("/v5/domain/domains/example.com/hosts/ns1").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_domain_delete_glue_record")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com", name="ns1")

    async def test_create_dnssec_key_maps_400_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.post("/v5/domain/domains/example.com/dnskeys").mock(
            return_value=httpx.Response(400, json={"cause": "invalid digest"}),
        )
        handler = await _get_handler(server, "gandi_domain_create_dnssec_key")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com", algorithm=13, digest_type=2, digest="ABCDEF", keytag=12345)

    async def test_delete_dnssec_key_maps_404_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.delete("/v5/domain/domains/example.com/dnskeys/k1").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_domain_delete_dnssec_key")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com", key_id="k1")

    async def test_reset_authinfo_maps_404_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.put("/v5/domain/domains/example.com/authinfo").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_domain_reset_authinfo")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")

    async def test_initiate_ownership_change_maps_400_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.post("/v5/domain/changeowner/example.com").mock(
            return_value=httpx.Response(400, json={"cause": "invalid owner"}),
        )
        handler = await _get_handler(server, "gandi_domain_initiate_ownership_change")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com", owner={"given": "Jane"})

    async def test_resend_foa_maps_404_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.post("/v5/domain/changeowner/example.com/foa").mock(
            return_value=httpx.Response(404, json={"cause": "no pending change"}),
        )
        handler = await _get_handler(server, "gandi_domain_resend_foa")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")


@pytest.mark.mocked
class TestDomainPurchaseErrorPaths:
    async def test_register_maps_402_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.post("/v5/domain/domains").mock(
            return_value=httpx.Response(402, json={"cause": "payment required"}),
        )
        handler = await _get_handler(server, "gandi_domain_register")
        with pytest.raises(ToolError):
            await handler(ctx, data={"fqdn": "example.com", "duration": 1, "owner": {}})

    async def test_renew_maps_402_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.post("/v5/domain/domains/example.com/renew").mock(
            return_value=httpx.Response(402, json={"cause": "payment required"}),
        )
        handler = await _get_handler(server, "gandi_domain_renew")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")

    async def test_transfer_in_maps_400_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.post("/v5/domain/transferin/example.com").mock(
            return_value=httpx.Response(400, json={"cause": "invalid authinfo"}),
        )
        handler = await _get_handler(server, "gandi_domain_transfer_in")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com", data={"authinfo": "x", "duration": 1, "owner": {}})

    async def test_delete_maps_403_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.delete("/v5/domain/domains/example.com").mock(
            return_value=httpx.Response(403, json={"cause": "not deletable"}),
        )
        handler = await _get_handler(server, "gandi_domain_delete")
        with pytest.raises(ToolError):
            await handler(ctx, fqdn="example.com")
