"""Mocked-integration tests for certificate tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from fastmcp import FastMCP
from fastmcp.tools.function_tool import FunctionTool

from gandi_mcp.tools.certificate import register_certificate_tools

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
    register_certificate_tools(s)
    return s


@pytest.mark.mocked
class TestCertList:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = [{"id": "cert-uuid", "cn": "example.com", "status": "valid"}]
        route = respx_mock.get("/v5/certificate/issued-certs").mock(return_value=httpx.Response(200, json=payload))

        handler = await _get_handler(server, "cert_list")
        result = await handler(ctx)

        assert route.called
        assert result == payload

    async def test_filters_none_status_and_keeps_pagination(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        # status=None must not be serialized; per_page/page have non-None defaults so they ARE sent.
        route = respx_mock.get("/v5/certificate/issued-certs").mock(
            return_value=httpx.Response(200, json=[]),
        )

        handler = await _get_handler(server, "cert_list")
        await handler(ctx, status=None)

        assert route.called
        assert dict(route.calls.last.request.url.params) == {"per_page": "100", "page": "1"}

    async def test_passes_status_filter_in_query(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.get("/v5/certificate/issued-certs").mock(
            return_value=httpx.Response(200, json=[]),
        )

        handler = await _get_handler(server, "cert_list")
        await handler(ctx, status="valid")

        assert route.called
        params = dict(route.calls.last.request.url.params)
        assert params.get("status") == "valid"
        assert params.get("per_page") == "100"
        assert params.get("page") == "1"


@pytest.mark.mocked
class TestCertGet:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"id": "cert-uuid", "cn": "example.com"}
        route = respx_mock.get("/v5/certificate/issued-certs/cert-uuid").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "cert_get")
        result = await handler(ctx, cert_id="cert-uuid")

        assert route.called
        assert result == payload

    async def test_url_encodes_cert_id(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.get("/v5/certificate/issued-certs/cert%2Fweird").mock(
            return_value=httpx.Response(200, json={})
        )

        handler = await _get_handler(server, "cert_get")
        await handler(ctx, cert_id="cert/weird")

        assert route.called
        assert route.calls.last.request.url.raw_path == b"/v5/certificate/issued-certs/cert%2Fweird"


@pytest.mark.mocked
class TestCertRevoke:
    async def test_calls_correct_endpoint_with_delete_method(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"message": "Certificate revoked"}
        route = respx_mock.delete("/v5/certificate/issued-certs/cert-uuid").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "cert_revoke")
        result = await handler(ctx, cert_id="cert-uuid")

        assert route.called
        assert route.calls.last.request.method == "DELETE"
        assert result == payload

    async def test_url_encodes_cert_id(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.delete("/v5/certificate/issued-certs/cert%2Fweird").mock(
            return_value=httpx.Response(200, json={})
        )

        handler = await _get_handler(server, "cert_revoke")
        await handler(ctx, cert_id="cert/weird")

        assert route.called
        assert route.calls.last.request.method == "DELETE"
        assert route.calls.last.request.url.raw_path == b"/v5/certificate/issued-certs/cert%2Fweird"


@pytest.mark.mocked
class TestCertIssue:
    async def test_posts_body_to_correct_endpoint(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        body = {
            "cn": "example.com",
            "duration": 1,
            "package": "cert_std_1_0_0",
            "csr": "-----BEGIN CSR-----\n...",
        }
        payload = {"id": "cert-uuid", "cn": "example.com", "status": "pending"}
        route = respx_mock.post("/v5/certificate/issued-certs", json=body).mock(
            return_value=httpx.Response(202, json=payload)
        )

        handler = await _get_handler(server, "cert_issue")
        result = await handler(ctx, data=body)

        assert route.called
        assert route.calls.last.request.method == "POST"
        sent = json.loads(route.calls.last.request.content)
        assert sent == body
        assert result == payload


@pytest.mark.mocked
class TestCertRenew:
    async def test_posts_body_to_correct_endpoint(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        body = {
            "cn": "example.com",
            "duration": 1,
            "package": "cert_std_1_0_0",
            "csr": "-----BEGIN CSR-----\n...",
        }
        payload = {"id": "cert-uuid", "cn": "example.com", "status": "pending"}
        route = respx_mock.post("/v5/certificate/issued-certs/cert-uuid/renew", json=body).mock(
            return_value=httpx.Response(202, json=payload)
        )

        handler = await _get_handler(server, "cert_renew")
        result = await handler(ctx, cert_id="cert-uuid", data=body)

        assert route.called
        assert route.calls.last.request.method == "POST"
        sent = json.loads(route.calls.last.request.content)
        assert sent == body
        assert result == payload

    async def test_url_encodes_cert_id(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        body = {"duration": 1, "csr": "-----BEGIN CSR-----\n..."}
        route = respx_mock.post("/v5/certificate/issued-certs/cert%2Fweird/renew", json=body).mock(
            return_value=httpx.Response(202, json={})
        )

        handler = await _get_handler(server, "cert_renew")
        await handler(ctx, cert_id="cert/weird", data=body)

        assert route.called
        assert route.calls.last.request.method == "POST"
        assert route.calls.last.request.url.raw_path == b"/v5/certificate/issued-certs/cert%2Fweird/renew"
        sent = json.loads(route.calls.last.request.content)
        assert sent == body
