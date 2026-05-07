"""Mocked-integration tests for domain tools (28 tools).

Largest module in the suite. Covers all read, write, and purchase tools.
DANGEROUS-mock-only-forever tools (``gandi_domain_update_contacts``,
``gandi_domain_set_nameservers``, ``gandi_domain_initiate_ownership_change``,
``gandi_domain_resend_foa``, ``gandi_domain_delete``) get the same body-shape coverage
as the safer writes — at this tier all tools are exercised identically;
the live tier is where the operational distinction matters.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from fastmcp import FastMCP
from fastmcp.tools.function_tool import FunctionTool

from gandi_mcp.tools.domain import register_domain_tools

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
    register_domain_tools(s)
    return s


# ─── Read tools ────────────────────────────────────────────────────────────


@pytest.mark.mocked
class TestDomainListDomains:
    async def test_calls_correct_endpoint_with_default_pagination(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = [{"fqdn": "example.com", "id": "d-uuid"}]
        route = respx_mock.get("/v5/domain/domains").mock(return_value=httpx.Response(200, json=payload))

        handler = await _get_handler(server, "gandi_domain_list_domains")
        result = await handler(ctx)

        assert route.called
        # Defaults flow through to the query string as strings; None filters drop out.
        assert dict(route.calls.last.request.url.params) == {"per_page": "100", "page": "1"}
        assert result == payload

    async def test_filters_none_params_with_explicit_defaults(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        route = respx_mock.get("/v5/domain/domains").mock(return_value=httpx.Response(200, json=[]))

        handler = await _get_handler(server, "gandi_domain_list_domains")
        await handler(ctx, per_page=100, page=1, fqdn_filter=None)

        assert route.called
        # fqdn_filter=None must not appear in the query string.
        assert dict(route.calls.last.request.url.params) == {"per_page": "100", "page": "1"}

    async def test_passes_filters_when_provided(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.get("/v5/domain/domains").mock(return_value=httpx.Response(200, json=[]))

        handler = await _get_handler(server, "gandi_domain_list_domains")
        await handler(ctx, fqdn_filter="example", tld="com", per_page=50, page=2)

        assert route.called
        assert dict(route.calls.last.request.url.params) == {
            "fqdn": "example",
            "tld": "com",
            "per_page": "50",
            "page": "2",
        }


@pytest.mark.mocked
class TestDomainGetDomain:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"fqdn": "example.com", "id": "d-uuid", "status": []}
        route = respx_mock.get("/v5/domain/domains/example.com").mock(return_value=httpx.Response(200, json=payload))

        handler = await _get_handler(server, "gandi_domain_get_domain")
        result = await handler(ctx, fqdn="example.com")

        assert route.called
        assert result == payload

    async def test_url_encodes_fqdn(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.get("/v5/domain/domains/weird%2Fdom.com").mock(return_value=httpx.Response(200, json={}))

        handler = await _get_handler(server, "gandi_domain_get_domain")
        await handler(ctx, fqdn="weird/dom.com")

        assert route.called
        assert route.calls.last.request.url.raw_path == b"/v5/domain/domains/weird%2Fdom.com"


@pytest.mark.mocked
class TestDomainGetStatus:
    async def test_hits_get_domain_and_applies_status_view(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        # Wraps gandi_domain_get_domain then applies _status_view — assert both ends.
        payload = {
            "fqdn": "example.com",
            "status": ["clientTransferProhibited"],
            "id": "d-uuid",
            "dates": {"registry_ends_at": "2030-01-01"},
        }
        route = respx_mock.get("/v5/domain/domains/example.com").mock(return_value=httpx.Response(200, json=payload))

        handler = await _get_handler(server, "gandi_domain_get_status")
        result = await handler(ctx, fqdn="example.com")

        assert route.called
        # _status_view applied: agent-friendly shape with the four expected keys.
        assert result == {
            "fqdn": "example.com",
            "status": ["clientTransferProhibited"],
            "transferLocked": True,
            "updateLocked": False,
            "deleteLocked": False,
        }


@pytest.mark.mocked
class TestDomainCheckAvailability:
    async def test_passes_name_as_query_param(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        payload = {"products": [{"name": "example.com", "status": "available"}]}
        route = respx_mock.get("/v5/domain/check").mock(return_value=httpx.Response(200, json=payload))

        handler = await _get_handler(server, "gandi_domain_check_availability")
        result = await handler(ctx, name="example.com")

        assert route.called
        # Only ``name`` — every other param was None and must drop out.
        assert dict(route.calls.last.request.url.params) == {"name": "example.com"}
        assert result == payload

    async def test_passes_all_query_params_when_provided(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        route = respx_mock.get("/v5/domain/check").mock(return_value=httpx.Response(200, json={}))

        handler = await _get_handler(server, "gandi_domain_check_availability")
        await handler(
            ctx,
            name="example",
            processes=["create", "transfer"],
            extension="com",
            currency="USD",
            country="US",
            max_duration=10,
            period="create",
        )

        assert route.called
        params = dict(route.calls.last.request.url.params)
        # httpx serializes list-valued params as repeated keys; dict() collapses to last value.
        # Just assert the scalar params plus the presence of name.
        assert params["name"] == "example"
        assert params["extension"] == "com"
        assert params["currency"] == "USD"
        assert params["country"] == "US"
        assert params["max_duration"] == "10"
        assert params["period"] == "create"


@pytest.mark.mocked
class TestDomainGetClaims:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload: dict[str, Any] = {"claims": []}
        route = respx_mock.get("/v5/domain/domains/example.com/claims").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "gandi_domain_get_claims")
        result = await handler(ctx, fqdn="example.com")

        assert route.called
        assert result == payload


@pytest.mark.mocked
class TestDomainGetContacts:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload: dict[str, Any] = {"admin": {}, "tech": {}, "bill": {}, "owner": {}}
        route = respx_mock.get("/v5/domain/domains/example.com/contacts").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "gandi_domain_get_contacts")
        result = await handler(ctx, fqdn="example.com")

        assert route.called
        assert result == payload


@pytest.mark.mocked
class TestDomainGetNameservers:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = ["ns1.gandi.net", "ns2.gandi.net"]
        route = respx_mock.get("/v5/domain/domains/example.com/nameservers").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "gandi_domain_get_nameservers")
        result = await handler(ctx, fqdn="example.com")

        assert route.called
        assert result == payload


@pytest.mark.mocked
class TestDomainListGlueRecords:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = [{"name": "ns1", "ips": ["192.0.2.1"]}]
        route = respx_mock.get("/v5/domain/domains/example.com/hosts").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "gandi_domain_list_glue_records")
        result = await handler(ctx, fqdn="example.com")

        assert route.called
        assert result == payload


@pytest.mark.mocked
class TestDomainGetGlueRecord:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"name": "ns1", "ips": ["192.0.2.1"]}
        route = respx_mock.get("/v5/domain/domains/example.com/hosts/ns1").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "gandi_domain_get_glue_record")
        result = await handler(ctx, fqdn="example.com", name="ns1")

        assert route.called
        assert result == payload

    async def test_url_encodes_fqdn_and_name(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.get("/v5/domain/domains/weird%2Fdom.com/hosts/ns%2Fweird").mock(
            return_value=httpx.Response(200, json={})
        )

        handler = await _get_handler(server, "gandi_domain_get_glue_record")
        await handler(ctx, fqdn="weird/dom.com", name="ns/weird")

        assert route.called
        assert route.calls.last.request.url.raw_path == b"/v5/domain/domains/weird%2Fdom.com/hosts/ns%2Fweird"


@pytest.mark.mocked
class TestDomainListDnssecKeys:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = [{"id": "k1", "algorithm": 13}]
        route = respx_mock.get("/v5/domain/domains/example.com/dnskeys").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "gandi_domain_list_dnssec_keys")
        result = await handler(ctx, fqdn="example.com")

        assert route.called
        assert result == payload


@pytest.mark.mocked
class TestDomainGetRenewInfo:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"prices": [{"duration_unit": "y", "min_duration": 1, "max_duration": 10}]}
        route = respx_mock.get("/v5/domain/domains/example.com/renew").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "gandi_domain_get_renew_info")
        result = await handler(ctx, fqdn="example.com")

        assert route.called
        assert result == payload


@pytest.mark.mocked
class TestDomainGetTransferinInfo:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"available": True, "prices": []}
        route = respx_mock.get("/v5/domain/transferin/example.com").mock(return_value=httpx.Response(200, json=payload))

        handler = await _get_handler(server, "gandi_domain_get_transferin_info")
        result = await handler(ctx, fqdn="example.com")

        assert route.called
        assert result == payload


@pytest.mark.mocked
class TestDomainGetOwnershipChangeStatus:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"state": "PENDING_FOA"}
        route = respx_mock.get("/v5/domain/changeowner/example.com").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "gandi_domain_get_ownership_change_status")
        result = await handler(ctx, fqdn="example.com")

        assert route.called
        assert result == payload


# ─── Write tools (non-purchasing) ──────────────────────────────────────────


@pytest.mark.mocked
class TestDomainSetAutorenew:
    async def test_patches_with_enabled_only_when_duration_omitted(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"message": "Autorenew updated"}
        route = respx_mock.patch("/v5/domain/domains/example.com/autorenew").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "gandi_domain_set_autorenew")
        result = await handler(ctx, fqdn="example.com", enabled=True)

        assert route.called
        assert route.calls.last.request.method == "PATCH"
        sent = json.loads(route.calls.last.request.content)
        # duration omitted → key not present.
        assert sent == {"enabled": True}
        assert "duration" not in sent
        assert result == payload

    async def test_patches_with_duration_when_provided(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.patch("/v5/domain/domains/example.com/autorenew").mock(
            return_value=httpx.Response(200, json={})
        )

        handler = await _get_handler(server, "gandi_domain_set_autorenew")
        await handler(ctx, fqdn="example.com", enabled=True, duration=2)

        assert route.called
        sent = json.loads(route.calls.last.request.content)
        assert sent == {"enabled": True, "duration": 2}

    async def test_disable_passes_enabled_false(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.patch("/v5/domain/domains/example.com/autorenew").mock(
            return_value=httpx.Response(200, json={})
        )

        handler = await _get_handler(server, "gandi_domain_set_autorenew")
        await handler(ctx, fqdn="example.com", enabled=False)

        assert route.called
        sent = json.loads(route.calls.last.request.content)
        assert sent == {"enabled": False}


@pytest.mark.mocked
class TestDomainUpdateContacts:
    """DANGEROUS — mock-only-forever; live tier never runs this."""

    async def test_patches_only_provided_blocks(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        payload = {"message": "Contacts updated"}
        route = respx_mock.patch("/v5/domain/domains/example.com/contacts").mock(
            return_value=httpx.Response(200, json=payload)
        )

        admin = {"given": "Jane", "family": "Doe"}
        handler = await _get_handler(server, "gandi_domain_update_contacts")
        result = await handler(ctx, fqdn="example.com", admin=admin)

        assert route.called
        assert route.calls.last.request.method == "PATCH"
        sent = json.loads(route.calls.last.request.content)
        # tech and bill omitted → keys absent.
        assert sent == {"admin": admin}
        assert "tech" not in sent
        assert "bill" not in sent
        assert result == payload

    async def test_patches_all_three_when_provided(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.patch("/v5/domain/domains/example.com/contacts").mock(
            return_value=httpx.Response(200, json={})
        )

        admin = {"given": "A"}
        tech = {"given": "T"}
        bill = {"given": "B"}
        handler = await _get_handler(server, "gandi_domain_update_contacts")
        await handler(ctx, fqdn="example.com", admin=admin, tech=tech, bill=bill)

        assert route.called
        sent = json.loads(route.calls.last.request.content)
        assert sent == {"admin": admin, "tech": tech, "bill": bill}

    async def test_patches_empty_body_when_all_none(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.patch("/v5/domain/domains/example.com/contacts").mock(
            return_value=httpx.Response(200, json={})
        )

        handler = await _get_handler(server, "gandi_domain_update_contacts")
        await handler(ctx, fqdn="example.com")

        assert route.called
        sent = json.loads(route.calls.last.request.content)
        assert sent == {}


@pytest.mark.mocked
class TestDomainSetNameservers:
    """DANGEROUS — mock-only-forever; live tier never runs this."""

    async def test_puts_nameservers_body(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        payload = {"message": "Nameservers updated"}
        route = respx_mock.put("/v5/domain/domains/example.com/nameservers").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "gandi_domain_set_nameservers")
        result = await handler(ctx, fqdn="example.com", nameservers=["ns1.example.com", "ns2.example.com"])

        assert route.called
        assert route.calls.last.request.method == "PUT"
        sent = json.loads(route.calls.last.request.content)
        assert sent == {"nameservers": ["ns1.example.com", "ns2.example.com"]}
        assert result == payload


@pytest.mark.mocked
class TestDomainCreateGlueRecord:
    async def test_posts_name_and_ips_body(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        payload = {"message": "Glue record created"}
        route = respx_mock.post("/v5/domain/domains/example.com/hosts").mock(
            return_value=httpx.Response(201, json=payload)
        )

        handler = await _get_handler(server, "gandi_domain_create_glue_record")
        result = await handler(ctx, fqdn="example.com", name="ns1", ips=["192.0.2.1", "2001:db8::1"])

        assert route.called
        assert route.calls.last.request.method == "POST"
        sent = json.loads(route.calls.last.request.content)
        assert sent == {"name": "ns1", "ips": ["192.0.2.1", "2001:db8::1"]}
        assert result == payload


@pytest.mark.mocked
class TestDomainUpdateGlueRecord:
    async def test_puts_ips_only_body(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        payload = {"message": "Glue record updated"}
        route = respx_mock.put("/v5/domain/domains/example.com/hosts/ns1").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "gandi_domain_update_glue_record")
        result = await handler(ctx, fqdn="example.com", name="ns1", ips=["192.0.2.99"])

        assert route.called
        assert route.calls.last.request.method == "PUT"
        sent = json.loads(route.calls.last.request.content)
        # Body has ips only — no name field (it's in the URL).
        assert sent == {"ips": ["192.0.2.99"]}
        assert "name" not in sent
        assert result == payload


@pytest.mark.mocked
class TestDomainDeleteGlueRecord:
    async def test_deletes_correct_endpoint(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.delete("/v5/domain/domains/example.com/hosts/ns1").mock(return_value=httpx.Response(204))

        handler = await _get_handler(server, "gandi_domain_delete_glue_record")
        result = await handler(ctx, fqdn="example.com", name="ns1")

        assert route.called
        assert route.calls.last.request.method == "DELETE"
        assert route.calls.last.request.content == b""
        assert result == {}


@pytest.mark.mocked
class TestDomainCreateDnssecKey:
    async def test_posts_full_dnssec_body(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        payload = {"id": "k1"}
        route = respx_mock.post("/v5/domain/domains/example.com/dnskeys").mock(
            return_value=httpx.Response(201, json=payload)
        )

        handler = await _get_handler(server, "gandi_domain_create_dnssec_key")
        result = await handler(
            ctx,
            fqdn="example.com",
            algorithm=13,
            digest_type=2,
            digest="ABCDEF0123",
            keytag=12345,
        )

        assert route.called
        assert route.calls.last.request.method == "POST"
        sent = json.loads(route.calls.last.request.content)
        assert sent == {"algorithm": 13, "digest_type": 2, "digest": "ABCDEF0123", "keytag": 12345}
        assert result == payload


@pytest.mark.mocked
class TestDomainDeleteDnssecKey:
    async def test_deletes_correct_endpoint(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.delete("/v5/domain/domains/example.com/dnskeys/k1").mock(return_value=httpx.Response(204))

        handler = await _get_handler(server, "gandi_domain_delete_dnssec_key")
        result = await handler(ctx, fqdn="example.com", key_id="k1")

        assert route.called
        assert route.calls.last.request.method == "DELETE"
        assert route.calls.last.request.content == b""
        assert result == {}

    async def test_url_encodes_fqdn_and_key_id(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.delete("/v5/domain/domains/weird%2Fdom.com/dnskeys/k%2Fweird").mock(
            return_value=httpx.Response(204)
        )

        handler = await _get_handler(server, "gandi_domain_delete_dnssec_key")
        await handler(ctx, fqdn="weird/dom.com", key_id="k/weird")

        assert route.called
        assert route.calls.last.request.url.raw_path == b"/v5/domain/domains/weird%2Fdom.com/dnskeys/k%2Fweird"


@pytest.mark.mocked
class TestDomainResetAuthinfo:
    async def test_puts_correct_endpoint_with_empty_body(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"message": "Auth code regenerated"}
        route = respx_mock.put("/v5/domain/domains/example.com/authinfo").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "gandi_domain_reset_authinfo")
        result = await handler(ctx, fqdn="example.com")

        assert route.called
        assert route.calls.last.request.method == "PUT"
        # No body — client method passes no json kwarg.
        assert route.calls.last.request.content == b""
        assert result == payload


@pytest.mark.mocked
class TestDomainInitiateOwnershipChange:
    """DANGEROUS — mock-only-forever; live tier never runs this."""

    async def test_posts_body_with_owner_and_default_notify(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"id": "co-uuid"}
        route = respx_mock.post("/v5/domain/changeowner/example.com").mock(
            return_value=httpx.Response(202, json=payload)
        )

        owner = {"given": "Jane", "family": "Doe", "email": "jane@example.com"}
        handler = await _get_handler(server, "gandi_domain_initiate_ownership_change")
        result = await handler(ctx, fqdn="example.com", owner=owner)

        assert route.called
        assert route.calls.last.request.method == "POST"
        sent = json.loads(route.calls.last.request.content)
        # Default notify_former_owner=True must be sent through.
        assert sent == {"owner": owner, "notify_former_owner": True}
        assert result == payload

    async def test_posts_with_notify_false_when_overridden(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        route = respx_mock.post("/v5/domain/changeowner/example.com").mock(return_value=httpx.Response(202, json={}))

        owner = {"given": "X"}
        handler = await _get_handler(server, "gandi_domain_initiate_ownership_change")
        await handler(ctx, fqdn="example.com", owner=owner, notify_former_owner=False)

        assert route.called
        sent = json.loads(route.calls.last.request.content)
        assert sent == {"owner": owner, "notify_former_owner": False}


@pytest.mark.mocked
class TestDomainResendFoa:
    """DANGEROUS — mock-only-forever; live tier never runs this."""

    async def test_posts_correct_endpoint_with_empty_body(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"message": "FOA resent"}
        route = respx_mock.post("/v5/domain/changeowner/example.com/foa").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "gandi_domain_resend_foa")
        result = await handler(ctx, fqdn="example.com")

        assert route.called
        assert route.calls.last.request.method == "POST"
        assert route.calls.last.request.content == b""
        assert result == payload


@pytest.mark.mocked
class TestDomainDelete:
    """DANGEROUS — mock-only-forever; live tier never runs this."""

    async def test_deletes_correct_endpoint(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.delete("/v5/domain/domains/example.com").mock(return_value=httpx.Response(204))

        handler = await _get_handler(server, "gandi_domain_delete")
        result = await handler(ctx, fqdn="example.com")

        assert route.called
        assert route.calls.last.request.method == "DELETE"
        assert route.calls.last.request.content == b""
        assert result == {}


# ─── Purchase tools (double-gated, SPENDS MONEY) ───────────────────────────


@pytest.mark.mocked
class TestDomainRegister:
    async def test_posts_full_payload_passthrough(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        payload = {"message": "Domain registered", "id": "d-uuid"}
        route = respx_mock.post("/v5/domain/domains").mock(return_value=httpx.Response(202, json=payload))

        data = {
            "fqdn": "example.com",
            "duration": 1,
            "owner": {"given": "Jane", "family": "Doe", "email": "jane@example.com"},
            "admin": {"given": "Jane"},
            "tech": {"given": "Jane"},
            "bill": {"given": "Jane"},
            "nameservers": ["ns1.example.com"],
        }
        handler = await _get_handler(server, "gandi_domain_register")
        result = await handler(ctx, data=data)

        assert route.called
        assert route.calls.last.request.method == "POST"
        sent = json.loads(route.calls.last.request.content)
        # Pure pass-through: every key the caller supplied lands on the wire untouched.
        assert sent == data
        assert result == payload


@pytest.mark.mocked
class TestDomainRenew:
    async def test_posts_duration_only_when_currency_omitted(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"message": "Domain renewed"}
        route = respx_mock.post("/v5/domain/domains/example.com/renew").mock(
            return_value=httpx.Response(202, json=payload)
        )

        handler = await _get_handler(server, "gandi_domain_renew")
        result = await handler(ctx, fqdn="example.com", duration=2)

        assert route.called
        assert route.calls.last.request.method == "POST"
        sent = json.loads(route.calls.last.request.content)
        assert sent == {"duration": 2}
        assert "currency" not in sent
        assert result == payload

    async def test_default_duration_is_one(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.post("/v5/domain/domains/example.com/renew").mock(return_value=httpx.Response(202, json={}))

        handler = await _get_handler(server, "gandi_domain_renew")
        await handler(ctx, fqdn="example.com")

        assert route.called
        sent = json.loads(route.calls.last.request.content)
        # Default duration=1 must land on the wire.
        assert sent == {"duration": 1}

    async def test_includes_currency_when_provided(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.post("/v5/domain/domains/example.com/renew").mock(return_value=httpx.Response(202, json={}))

        handler = await _get_handler(server, "gandi_domain_renew")
        await handler(ctx, fqdn="example.com", duration=3, currency="EUR")

        assert route.called
        sent = json.loads(route.calls.last.request.content)
        assert sent == {"duration": 3, "currency": "EUR"}

    async def test_url_encodes_fqdn(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        # Purchase tool with fqdn in path — encoding regression here would silently
        # POST against a different endpoint.
        route = respx_mock.post("/v5/domain/domains/weird%2Fdom.com/renew").mock(
            return_value=httpx.Response(202, json={})
        )

        handler = await _get_handler(server, "gandi_domain_renew")
        await handler(ctx, fqdn="weird/dom.com")

        assert route.called
        assert route.calls.last.request.method == "POST"
        assert route.calls.last.request.url.raw_path == b"/v5/domain/domains/weird%2Fdom.com/renew"


@pytest.mark.mocked
class TestDomainTransferIn:
    async def test_posts_full_payload_passthrough(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        payload = {"message": "Transfer initiated"}
        route = respx_mock.post("/v5/domain/transferin/example.com").mock(
            return_value=httpx.Response(202, json=payload)
        )

        data = {
            "authinfo": "auth-code-xyz",
            "duration": 1,
            "owner": {"given": "Jane", "family": "Doe", "email": "jane@example.com"},
            "nameservers": ["ns1.example.com", "ns2.example.com"],
        }
        handler = await _get_handler(server, "gandi_domain_transfer_in")
        result = await handler(ctx, fqdn="example.com", data=data)

        assert route.called
        assert route.calls.last.request.method == "POST"
        sent = json.loads(route.calls.last.request.content)
        assert sent == data
        assert result == payload
