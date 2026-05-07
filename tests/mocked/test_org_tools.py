"""Mocked-integration tests for organization tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest
from fastmcp import FastMCP
from fastmcp.tools.function_tool import FunctionTool

from gandi_mcp.tools.organization import register_organization_tools

if TYPE_CHECKING:
    from unittest.mock import AsyncMock


async def _get_handler(server: FastMCP, name: str) -> Any:
    """Pull a registered tool's underlying async handler by name.

    FastMCP exposes ``get_tool(name)`` as the public lookup; it returns a
    ``FunctionTool`` whose ``.fn`` attribute is the original async handler.
    Subsequent mocked-tool tasks (1.7+) copy this helper verbatim.
    """
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
class TestOrgGetUserInfo:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"id": "user-uuid", "username": "alice", "email": "alice@example.com", "lang": "en"}
        route = respx_mock.get("/v5/organization/user-info").mock(return_value=httpx.Response(200, json=payload))

        handler = await _get_handler(server, "gandi_org_get_user_info")
        result = await handler(ctx)

        assert route.called
        assert result == payload


@pytest.mark.mocked
class TestOrgListOrganizations:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = [{"id": "org-uuid", "name": "acme", "type": "company"}]
        route = respx_mock.get("/v5/organization/organizations").mock(return_value=httpx.Response(200, json=payload))

        handler = await _get_handler(server, "gandi_org_list_organizations")
        result = await handler(ctx)

        assert route.called
        assert result == payload

    async def test_filters_none_params_and_maps_org_type_to_type(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        # Only `name` is set; `permission` and `org_type` are None and must not be sent.
        # `per_page` and `page` have non-None defaults so they ARE serialized.
        route = respx_mock.get("/v5/organization/organizations").mock(
            return_value=httpx.Response(200, json=[]),
        )

        handler = await _get_handler(server, "gandi_org_list_organizations")
        await handler(ctx, name="acme", permission=None, org_type=None)

        assert route.called
        assert dict(route.calls.last.request.url.params) == {"name": "acme", "per_page": "100", "page": "1"}

    async def test_renames_org_type_to_type_in_query(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        # Confirms the tool-layer `org_type` lands on the wire as `type`, not `org_type`.
        route = respx_mock.get("/v5/organization/organizations").mock(
            return_value=httpx.Response(200, json=[]),
        )

        handler = await _get_handler(server, "gandi_org_list_organizations")
        await handler(ctx, org_type="company")

        assert route.called
        params = dict(route.calls.last.request.url.params)
        assert params.get("type") == "company"
        assert "org_type" not in params


@pytest.mark.mocked
class TestOrgGetOrganization:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"id": "org-uuid", "name": "acme"}
        route = respx_mock.get("/v5/organization/organizations/org-uuid").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "gandi_org_get_organization")
        result = await handler(ctx, org_id="org-uuid")

        assert route.called
        assert result == payload

    async def test_url_encodes_org_id(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.get("/v5/organization/organizations/o%2Fweird").mock(
            return_value=httpx.Response(200, json={})
        )

        handler = await _get_handler(server, "gandi_org_get_organization")
        await handler(ctx, org_id="o/weird")

        assert route.called
        assert route.calls.last.request.url.raw_path == b"/v5/organization/organizations/o%2Fweird"


@pytest.mark.mocked
class TestOrgListCustomers:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = [{"id": "cust-uuid", "name": "customer-1"}]
        route = respx_mock.get(
            "/v5/organization/organizations/org-uuid/customers",
            params={"per_page": "100", "page": "1"},
        ).mock(return_value=httpx.Response(200, json=payload))

        handler = await _get_handler(server, "gandi_org_list_customers")
        result = await handler(ctx, org_id="org-uuid")

        assert route.called
        assert result == payload

    async def test_url_encodes_org_id(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.get("/v5/organization/organizations/o%2Fweird/customers").mock(
            return_value=httpx.Response(200, json=[])
        )

        handler = await _get_handler(server, "gandi_org_list_customers")
        await handler(ctx, org_id="o/weird")

        assert route.called
        assert route.calls.last.request.url.raw_path.startswith(b"/v5/organization/organizations/o%2Fweird/customers")


@pytest.mark.mocked
class TestOrgGetCustomer:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"id": "cust-uuid", "name": "customer-1"}
        route = respx_mock.get("/v5/organization/organizations/org-uuid/customers/cust-uuid").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "gandi_org_get_customer")
        result = await handler(ctx, org_id="org-uuid", customer_id="cust-uuid")

        assert route.called
        assert result == payload

    async def test_url_encodes_both_path_segments(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.get("/v5/organization/organizations/o%2Fweird/customers/c%2Fodd").mock(
            return_value=httpx.Response(200, json={})
        )

        handler = await _get_handler(server, "gandi_org_get_customer")
        await handler(ctx, org_id="o/weird", customer_id="c/odd")

        assert route.called
        assert route.calls.last.request.url.raw_path == b"/v5/organization/organizations/o%2Fweird/customers/c%2Fodd"
