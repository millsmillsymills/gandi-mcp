"""Mocked-integration tests for email tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from fastmcp import FastMCP
from fastmcp.tools.function_tool import FunctionTool

from gandi_mcp.tools.email import register_email_tools

if TYPE_CHECKING:
    from unittest.mock import AsyncMock


async def _get_handler(server: FastMCP, name: str) -> Any:
    """Pull a registered tool's underlying async handler by name.

    FastMCP exposes ``get_tool(name)`` as the public lookup; it returns a
    ``FunctionTool`` whose ``.fn`` attribute is the original async handler.
    """
    tool = await server.get_tool(name)
    assert tool is not None, f"tool {name!r} not registered"
    assert isinstance(tool, FunctionTool), f"tool {name!r} is not a FunctionTool"
    return tool.fn


@pytest.fixture
def server() -> FastMCP:
    s = FastMCP(name="t")
    register_email_tools(s)
    return s


# ─── Read tools ────────────────────────────────────────────────────────────


@pytest.mark.mocked
class TestEmailListMailboxes:
    async def test_calls_correct_endpoint_with_default_pagination(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = [{"id": "mb-uuid", "address": "info@example.com"}]
        route = respx_mock.get("/v5/email/mailboxes/example.com").mock(return_value=httpx.Response(200, json=payload))

        handler = await _get_handler(server, "gandi_email_list_mailboxes")
        result = await handler(ctx, domain="example.com")

        assert route.called
        # Defaults flow through to the query string as strings.
        assert dict(route.calls.last.request.url.params) == {"per_page": "100", "page": "1"}
        assert result == payload

    async def test_url_encodes_domain(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.get("/v5/email/mailboxes/weird%2Fdom.com").mock(return_value=httpx.Response(200, json=[]))

        handler = await _get_handler(server, "gandi_email_list_mailboxes")
        await handler(ctx, domain="weird/dom.com")

        assert route.called
        assert route.calls.last.request.url.raw_path.startswith(b"/v5/email/mailboxes/weird%2Fdom.com")


@pytest.mark.mocked
class TestEmailGetMailbox:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"id": "mb-uuid", "address": "info@example.com"}
        route = respx_mock.get("/v5/email/mailboxes/example.com/mb-uuid").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "gandi_email_get_mailbox")
        result = await handler(ctx, domain="example.com", mailbox_id="mb-uuid")

        assert route.called
        assert result == payload

    async def test_url_encodes_domain_and_mailbox_id(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.get("/v5/email/mailboxes/weird%2Fdom.com/mb%2Fweird").mock(
            return_value=httpx.Response(200, json={})
        )

        handler = await _get_handler(server, "gandi_email_get_mailbox")
        await handler(ctx, domain="weird/dom.com", mailbox_id="mb/weird")

        assert route.called
        assert route.calls.last.request.url.raw_path == b"/v5/email/mailboxes/weird%2Fdom.com/mb%2Fweird"


@pytest.mark.mocked
class TestEmailListForwards:
    async def test_calls_correct_endpoint_with_default_pagination(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = [{"source": "info", "destinations": ["a@b.com"]}]
        route = respx_mock.get("/v5/email/forwards/example.com").mock(return_value=httpx.Response(200, json=payload))

        handler = await _get_handler(server, "gandi_email_list_forwards")
        result = await handler(ctx, domain="example.com")

        assert route.called
        assert dict(route.calls.last.request.url.params) == {"per_page": "100", "page": "1"}
        assert result == payload


@pytest.mark.mocked
class TestEmailListSlots:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = [{"id": 1, "status": "active", "mailbox_type": "standard"}]
        route = respx_mock.get("/v5/email/slots/example.com").mock(return_value=httpx.Response(200, json=payload))

        handler = await _get_handler(server, "gandi_email_list_slots")
        result = await handler(ctx, domain="example.com")

        assert route.called
        # No other params expected.
        assert dict(route.calls.last.request.url.params) == {}
        assert result == payload


@pytest.mark.mocked
class TestEmailGetSlot:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"id": 1, "status": "active"}
        route = respx_mock.get("/v5/email/slots/example.com/1").mock(return_value=httpx.Response(200, json=payload))

        handler = await _get_handler(server, "gandi_email_get_slot")
        result = await handler(ctx, domain="example.com", slot_id="1")

        assert route.called
        assert result == payload

    async def test_url_encodes_domain_and_slot_id(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.get("/v5/email/slots/weird%2Fdom.com/slot%2Fweird").mock(
            return_value=httpx.Response(200, json={})
        )

        handler = await _get_handler(server, "gandi_email_get_slot")
        await handler(ctx, domain="weird/dom.com", slot_id="slot/weird")

        assert route.called
        assert route.calls.last.request.url.raw_path == b"/v5/email/slots/weird%2Fdom.com/slot%2Fweird"


# ─── Write tools (non-purchasing) ──────────────────────────────────────────


@pytest.mark.mocked
class TestEmailUpdateMailbox:
    async def test_patches_with_only_password_when_others_none(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"message": "Mailbox updated"}
        route = respx_mock.patch("/v5/email/mailboxes/example.com/mb-uuid").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "gandi_email_update_mailbox")
        result = await handler(
            ctx,
            domain="example.com",
            mailbox_id="mb-uuid",
            password="s3cret",
        )

        assert route.called
        assert route.calls.last.request.method == "PATCH"
        sent = json.loads(route.calls.last.request.content)
        # Only password — aliases/responder were None and must not appear.
        assert sent == {"password": "s3cret"}
        assert "aliases" not in sent
        assert "responder" not in sent
        assert result == payload

    async def test_patches_with_all_fields_when_provided(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        route = respx_mock.patch("/v5/email/mailboxes/example.com/mb-uuid").mock(
            return_value=httpx.Response(200, json={})
        )

        responder = {"enabled": True, "subject": "OOO", "message": "Back Monday"}
        handler = await _get_handler(server, "gandi_email_update_mailbox")
        await handler(
            ctx,
            domain="example.com",
            mailbox_id="mb-uuid",
            password="s3cret",
            aliases=["alias1", "alias2"],
            responder=responder,
        )

        assert route.called
        sent = json.loads(route.calls.last.request.content)
        assert sent == {
            "password": "s3cret",
            "aliases": ["alias1", "alias2"],
            "responder": responder,
        }

    async def test_patches_with_empty_body_when_all_none(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        route = respx_mock.patch("/v5/email/mailboxes/example.com/mb-uuid").mock(
            return_value=httpx.Response(200, json={})
        )

        handler = await _get_handler(server, "gandi_email_update_mailbox")
        await handler(ctx, domain="example.com", mailbox_id="mb-uuid")

        assert route.called
        sent = json.loads(route.calls.last.request.content)
        assert sent == {}

    async def test_url_encodes_domain_and_mailbox_id(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.patch("/v5/email/mailboxes/weird%2Fdom.com/mb%2Fweird").mock(
            return_value=httpx.Response(200, json={})
        )

        handler = await _get_handler(server, "gandi_email_update_mailbox")
        await handler(
            ctx,
            domain="weird/dom.com",
            mailbox_id="mb/weird",
            password="s3cret",
        )

        assert route.called
        assert route.calls.last.request.url.raw_path == b"/v5/email/mailboxes/weird%2Fdom.com/mb%2Fweird"


@pytest.mark.mocked
class TestEmailDeleteMailbox:
    async def test_deletes_correct_endpoint(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.delete("/v5/email/mailboxes/example.com/mb-uuid").mock(return_value=httpx.Response(204))

        handler = await _get_handler(server, "gandi_email_delete_mailbox")
        result = await handler(ctx, domain="example.com", mailbox_id="mb-uuid")

        assert route.called
        assert route.calls.last.request.method == "DELETE"
        assert route.calls.last.request.content == b""
        # 204 → empty dict per _parse_json invariant.
        assert result == {}


@pytest.mark.mocked
class TestEmailPurgeMailbox:
    async def test_deletes_contents_endpoint(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.delete("/v5/email/mailboxes/example.com/mb-uuid/contents").mock(
            return_value=httpx.Response(204)
        )

        handler = await _get_handler(server, "gandi_email_purge_mailbox")
        result = await handler(ctx, domain="example.com", mailbox_id="mb-uuid")

        assert route.called
        assert route.calls.last.request.method == "DELETE"
        assert route.calls.last.request.content == b""
        assert result == {}


@pytest.mark.mocked
class TestEmailCreateForward:
    async def test_posts_source_and_destinations_body(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        payload = {"message": "Forward created"}
        route = respx_mock.post("/v5/email/forwards/example.com").mock(return_value=httpx.Response(201, json=payload))

        handler = await _get_handler(server, "gandi_email_create_forward")
        result = await handler(
            ctx,
            domain="example.com",
            source="info",
            destinations=["a@b.com", "c@d.com"],
        )

        assert route.called
        assert route.calls.last.request.method == "POST"
        sent = json.loads(route.calls.last.request.content)
        assert sent == {"source": "info", "destinations": ["a@b.com", "c@d.com"]}
        assert result == payload


@pytest.mark.mocked
class TestEmailUpdateForward:
    async def test_puts_destinations_only_body(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        payload = {"message": "Forward updated"}
        route = respx_mock.put("/v5/email/forwards/example.com/info").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "gandi_email_update_forward")
        result = await handler(
            ctx,
            domain="example.com",
            source="info",
            destinations=["new@b.com"],
        )

        assert route.called
        assert route.calls.last.request.method == "PUT"
        sent = json.loads(route.calls.last.request.content)
        # Body has destinations only — no source field.
        assert sent == {"destinations": ["new@b.com"]}
        assert "source" not in sent
        assert result == payload


@pytest.mark.mocked
class TestEmailDeleteForward:
    async def test_deletes_correct_endpoint(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.delete("/v5/email/forwards/example.com/info").mock(return_value=httpx.Response(204))

        handler = await _get_handler(server, "gandi_email_delete_forward")
        result = await handler(ctx, domain="example.com", source="info")

        assert route.called
        assert route.calls.last.request.method == "DELETE"
        assert result == {}

    async def test_url_encodes_domain_and_source(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.delete("/v5/email/forwards/weird%2Fdom.com/info%2Fweird").mock(
            return_value=httpx.Response(204)
        )

        handler = await _get_handler(server, "gandi_email_delete_forward")
        await handler(ctx, domain="weird/dom.com", source="info/weird")

        assert route.called
        assert route.calls.last.request.method == "DELETE"
        assert route.calls.last.request.url.raw_path == b"/v5/email/forwards/weird%2Fdom.com/info%2Fweird"


@pytest.mark.mocked
class TestEmailRefundSlot:
    async def test_deletes_correct_endpoint(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.delete("/v5/email/slots/example.com/1").mock(return_value=httpx.Response(204))

        handler = await _get_handler(server, "gandi_email_refund_slot")
        result = await handler(ctx, domain="example.com", slot_id="1")

        assert route.called
        assert route.calls.last.request.method == "DELETE"
        assert route.calls.last.request.content == b""
        assert result == {}


# ─── Purchase tools (double-gated) ─────────────────────────────────────────


@pytest.mark.mocked
class TestEmailCreateMailbox:
    async def test_posts_body_without_aliases_when_omitted(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"message": "Mailbox created"}
        route = respx_mock.post("/v5/email/mailboxes/example.com").mock(return_value=httpx.Response(201, json=payload))

        handler = await _get_handler(server, "gandi_email_create_mailbox")
        result = await handler(
            ctx,
            domain="example.com",
            login="info",
            password="s3cret",
        )

        assert route.called
        assert route.calls.last.request.method == "POST"
        sent = json.loads(route.calls.last.request.content)
        # aliases=None → key omitted entirely.
        assert sent == {"login": "info", "password": "s3cret", "mailbox_type": "standard"}
        assert "aliases" not in sent
        assert result == payload

    async def test_posts_body_with_aliases_when_provided(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        route = respx_mock.post("/v5/email/mailboxes/example.com").mock(return_value=httpx.Response(201, json={}))

        handler = await _get_handler(server, "gandi_email_create_mailbox")
        await handler(
            ctx,
            domain="example.com",
            login="info",
            password="s3cret",
            mailbox_type="premium",
            aliases=["a1", "a2"],
        )

        assert route.called
        sent = json.loads(route.calls.last.request.content)
        assert sent == {
            "login": "info",
            "password": "s3cret",
            "mailbox_type": "premium",
            "aliases": ["a1", "a2"],
        }


@pytest.mark.mocked
class TestEmailCreateSlot:
    async def test_posts_mailbox_type_body(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        payload = {"id": 2, "status": "inactive"}
        route = respx_mock.post("/v5/email/slots/example.com").mock(return_value=httpx.Response(201, json=payload))

        handler = await _get_handler(server, "gandi_email_create_slot")
        result = await handler(ctx, domain="example.com", mailbox_type="premium")

        assert route.called
        assert route.calls.last.request.method == "POST"
        sent = json.loads(route.calls.last.request.content)
        assert sent == {"mailbox_type": "premium"}
        assert result == payload

    async def test_default_mailbox_type_is_standard(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.post("/v5/email/slots/example.com").mock(return_value=httpx.Response(201, json={}))

        handler = await _get_handler(server, "gandi_email_create_slot")
        await handler(ctx, domain="example.com")

        assert route.called
        sent = json.loads(route.calls.last.request.content)
        assert sent == {"mailbox_type": "standard"}


@pytest.mark.mocked
class TestEmailRenewMailbox:
    async def test_posts_duration_body(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        payload = {"message": "Renewed"}
        route = respx_mock.post("/v5/email/mailboxes/example.com/info@example.com/renew").mock(
            return_value=httpx.Response(202, json=payload)
        )

        handler = await _get_handler(server, "gandi_email_renew_mailbox")
        result = await handler(
            ctx,
            domain="example.com",
            email="info@example.com",
            duration=2,
        )

        assert route.called
        assert route.calls.last.request.method == "POST"
        sent = json.loads(route.calls.last.request.content)
        assert sent == {"duration": 2}
        assert result == payload

    async def test_url_encodes_email_with_slashes(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.post("/v5/email/mailboxes/example.com/user%2Fwith%2Fslash%40example.com/renew").mock(
            return_value=httpx.Response(202, json={})
        )

        handler = await _get_handler(server, "gandi_email_renew_mailbox")
        await handler(
            ctx,
            domain="example.com",
            email="user/with/slash@example.com",
        )

        assert route.called
        assert route.calls.last.request.method == "POST"
        # Slashes in the email arg must encode to %2F so they don't shift into a different API path.
        raw = route.calls.last.request.url.raw_path
        assert b"%2F" in raw
        assert raw == b"/v5/email/mailboxes/example.com/user%2Fwith%2Fslash%40example.com/renew"
