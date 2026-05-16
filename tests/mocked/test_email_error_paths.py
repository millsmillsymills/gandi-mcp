"""Error-path coverage for email tools.

One test per ``gandi_email_*`` tool that exercises the
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

from gandi_mcp.tools.email import register_email_tools

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
    register_email_tools(s)
    return s


@pytest.mark.mocked
class TestEmailReadErrorPaths:
    async def test_list_mailboxes_maps_401_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.get("/v5/email/mailboxes/example.com").mock(
            return_value=httpx.Response(401, json={"cause": "Unauthorized"}),
        )
        handler = await _get_handler(server, "gandi_email_list_mailboxes")
        with pytest.raises(ToolError):
            await handler(ctx, domain="example.com")

    async def test_get_mailbox_maps_404_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.get("/v5/email/mailboxes/example.com/mb-uuid").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_email_get_mailbox")
        with pytest.raises(ToolError):
            await handler(ctx, domain="example.com", mailbox_id="mb-uuid")

    async def test_list_forwards_maps_401_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.get("/v5/email/forwards/example.com").mock(
            return_value=httpx.Response(401, json={"cause": "Unauthorized"}),
        )
        handler = await _get_handler(server, "gandi_email_list_forwards")
        with pytest.raises(ToolError):
            await handler(ctx, domain="example.com")

    async def test_list_slots_maps_429_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.get("/v5/email/slots/example.com").mock(return_value=httpx.Response(429, text="slow down"))
        handler = await _get_handler(server, "gandi_email_list_slots")
        with pytest.raises(ToolError):
            await handler(ctx, domain="example.com")

    async def test_get_slot_maps_404_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.get("/v5/email/slots/example.com/slot-1").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_email_get_slot")
        with pytest.raises(ToolError):
            await handler(ctx, domain="example.com", slot_id="slot-1")


@pytest.mark.mocked
class TestEmailWriteErrorPaths:
    async def test_update_mailbox_maps_400_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.patch("/v5/email/mailboxes/example.com/mb-uuid").mock(
            return_value=httpx.Response(400, json={"cause": "invalid"}),
        )
        handler = await _get_handler(server, "gandi_email_update_mailbox")
        with pytest.raises(ToolError):
            await handler(ctx, domain="example.com", mailbox_id="mb-uuid", password="hunter2")

    async def test_delete_mailbox_maps_404_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.delete("/v5/email/mailboxes/example.com/mb-uuid").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_email_delete_mailbox")
        with pytest.raises(ToolError):
            await handler(ctx, domain="example.com", mailbox_id="mb-uuid")

    async def test_purge_mailbox_maps_404_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.delete("/v5/email/mailboxes/example.com/mb-uuid/contents").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_email_purge_mailbox")
        with pytest.raises(ToolError):
            await handler(ctx, domain="example.com", mailbox_id="mb-uuid")

    async def test_create_forward_maps_409_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.post("/v5/email/forwards/example.com").mock(
            return_value=httpx.Response(409, json={"cause": "already exists"}),
        )
        handler = await _get_handler(server, "gandi_email_create_forward")
        with pytest.raises(ToolError):
            await handler(ctx, domain="example.com", source="info", destinations=["a@b.com"])

    async def test_update_forward_maps_400_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.put("/v5/email/forwards/example.com/info").mock(
            return_value=httpx.Response(400, json={"cause": "invalid"}),
        )
        handler = await _get_handler(server, "gandi_email_update_forward")
        with pytest.raises(ToolError):
            await handler(ctx, domain="example.com", source="info", destinations=["a@b.com"])

    async def test_delete_forward_maps_404_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.delete("/v5/email/forwards/example.com/info").mock(
            return_value=httpx.Response(404, json={"cause": "not found"}),
        )
        handler = await _get_handler(server, "gandi_email_delete_forward")
        with pytest.raises(ToolError):
            await handler(ctx, domain="example.com", source="info")

    async def test_refund_slot_maps_409_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.delete("/v5/email/slots/example.com/slot-1").mock(
            return_value=httpx.Response(409, json={"cause": "outside refund window"}),
        )
        handler = await _get_handler(server, "gandi_email_refund_slot")
        with pytest.raises(ToolError):
            await handler(ctx, domain="example.com", slot_id="slot-1")


@pytest.mark.mocked
class TestEmailPurchaseErrorPaths:
    async def test_create_mailbox_maps_402_to_tool_error(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        respx_mock.post("/v5/email/mailboxes/example.com").mock(
            return_value=httpx.Response(402, json={"cause": "payment required"}),
        )
        handler = await _get_handler(server, "gandi_email_create_mailbox")
        with pytest.raises(ToolError):
            await handler(ctx, domain="example.com", login="info", password="hunter2")

    async def test_create_slot_maps_402_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.post("/v5/email/slots/example.com").mock(
            return_value=httpx.Response(402, json={"cause": "payment required"}),
        )
        handler = await _get_handler(server, "gandi_email_create_slot")
        with pytest.raises(ToolError):
            await handler(ctx, domain="example.com")

    async def test_renew_mailbox_maps_400_to_tool_error(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        respx_mock.post("/v5/email/mailboxes/example.com/info@example.com/renew").mock(
            return_value=httpx.Response(400, json={"cause": "invalid"}),
        )
        handler = await _get_handler(server, "gandi_email_renew_mailbox")
        with pytest.raises(ToolError):
            await handler(ctx, domain="example.com", email="info@example.com")
