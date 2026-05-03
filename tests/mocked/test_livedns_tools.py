"""Mocked-integration tests for LiveDNS tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from fastmcp import FastMCP
from fastmcp.tools.function_tool import FunctionTool

from gandi_mcp.tools.livedns import register_livedns_tools

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
    register_livedns_tools(s)
    return s


# ─── Read tools ────────────────────────────────────────────────────────────


@pytest.mark.mocked
class TestLivednsListDomains:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = [{"fqdn": "example.com", "automatic_snapshots": True}]
        route = respx_mock.get("/v5/livedns/domains").mock(return_value=httpx.Response(200, json=payload))

        handler = await _get_handler(server, "livedns_list_domains")
        result = await handler(ctx)

        assert route.called
        assert result == payload


@pytest.mark.mocked
class TestLivednsGetDomain:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"fqdn": "example.com", "automatic_snapshots": True}
        route = respx_mock.get("/v5/livedns/domains/example.com").mock(return_value=httpx.Response(200, json=payload))

        handler = await _get_handler(server, "livedns_get_domain")
        result = await handler(ctx, fqdn="example.com")

        assert route.called
        assert result == payload

    async def test_url_encodes_fqdn(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.get("/v5/livedns/domains/has%2Fslash.com").mock(return_value=httpx.Response(200, json={}))

        handler = await _get_handler(server, "livedns_get_domain")
        await handler(ctx, fqdn="has/slash.com")

        assert route.called
        assert route.calls.last.request.url.raw_path == b"/v5/livedns/domains/has%2Fslash.com"


@pytest.mark.mocked
class TestLivednsListNameservers:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = ["ns1.gandi.net", "ns2.gandi.net", "ns3.gandi.net"]
        route = respx_mock.get("/v5/livedns/domains/example.com/nameservers").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "livedns_list_nameservers")
        result = await handler(ctx, fqdn="example.com")

        assert route.called
        assert result == payload

    async def test_url_encodes_fqdn(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.get("/v5/livedns/domains/has%2Fslash.com/nameservers").mock(
            return_value=httpx.Response(200, json=[])
        )

        handler = await _get_handler(server, "livedns_list_nameservers")
        await handler(ctx, fqdn="has/slash.com")

        assert route.called
        assert route.calls.last.request.url.raw_path == b"/v5/livedns/domains/has%2Fslash.com/nameservers"


@pytest.mark.mocked
class TestLivednsListRrtypes:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = ["A", "AAAA", "CNAME", "MX", "TXT"]
        route = respx_mock.get("/v5/livedns/dns/rrtypes").mock(return_value=httpx.Response(200, json=payload))

        handler = await _get_handler(server, "livedns_list_rrtypes")
        result = await handler(ctx)

        assert route.called
        assert result == payload


@pytest.mark.mocked
class TestLivednsListRecords:
    async def test_no_filter_uses_base_records_path(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        payload = [{"rrset_name": "www", "rrset_type": "A", "rrset_values": ["1.2.3.4"]}]
        route = respx_mock.get("/v5/livedns/domains/example.com/records").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "livedns_list_records")
        result = await handler(ctx, fqdn="example.com", name=None, rrset_type=None)

        assert route.called
        # No path segments added beyond /records, no query params either.
        assert route.calls.last.request.url.raw_path == b"/v5/livedns/domains/example.com/records"
        assert dict(route.calls.last.request.url.params) == {}
        assert result == payload

    async def test_name_only_appends_name_segment(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.get("/v5/livedns/domains/example.com/records/www").mock(
            return_value=httpx.Response(200, json=[])
        )

        handler = await _get_handler(server, "livedns_list_records")
        await handler(ctx, fqdn="example.com", name="www", rrset_type=None)

        assert route.called
        assert route.calls.last.request.url.raw_path == b"/v5/livedns/domains/example.com/records/www"

    async def test_name_and_type_appends_both_segments(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.get("/v5/livedns/domains/example.com/records/www/A").mock(
            return_value=httpx.Response(200, json=[])
        )

        handler = await _get_handler(server, "livedns_list_records")
        await handler(ctx, fqdn="example.com", name="www", rrset_type="A")

        assert route.called
        assert route.calls.last.request.url.raw_path == b"/v5/livedns/domains/example.com/records/www/A"

    async def test_url_encodes_name_with_slash(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.get("/v5/livedns/domains/example.com/records/rec%2Fwith%2Fslash").mock(
            return_value=httpx.Response(200, json=[])
        )

        handler = await _get_handler(server, "livedns_list_records")
        await handler(ctx, fqdn="example.com", name="rec/with/slash", rrset_type=None)

        assert route.called
        assert route.calls.last.request.url.raw_path == b"/v5/livedns/domains/example.com/records/rec%2Fwith%2Fslash"


@pytest.mark.mocked
class TestLivednsListDnssecKeys:
    async def test_calls_correct_endpoint_and_returns_payload(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = [{"id": "key-uuid", "flags": 257, "algorithm": 13}]
        route = respx_mock.get("/v5/livedns/domains/example.com/keys").mock(
            return_value=httpx.Response(200, json=payload)
        )

        handler = await _get_handler(server, "livedns_list_dnssec_keys")
        result = await handler(ctx, fqdn="example.com")

        assert route.called
        assert result == payload

    async def test_url_encodes_fqdn(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.get("/v5/livedns/domains/has%2Fslash.com/keys").mock(
            return_value=httpx.Response(200, json=[])
        )

        handler = await _get_handler(server, "livedns_list_dnssec_keys")
        await handler(ctx, fqdn="has/slash.com")

        assert route.called
        assert route.calls.last.request.url.raw_path == b"/v5/livedns/domains/has%2Fslash.com/keys"


# ─── Write tools ───────────────────────────────────────────────────────────


@pytest.mark.mocked
class TestLivednsAddDomain:
    async def test_posts_fqdn_body_to_correct_endpoint(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        payload = {"message": "DNS Zone Created"}
        route = respx_mock.post("/v5/livedns/domains").mock(return_value=httpx.Response(201, json=payload))

        handler = await _get_handler(server, "livedns_add_domain")
        result = await handler(ctx, fqdn="example.com")

        assert route.called
        assert route.calls.last.request.method == "POST"
        sent = json.loads(route.calls.last.request.content)
        assert sent == {"fqdn": "example.com"}
        assert result == payload


@pytest.mark.mocked
class TestLivednsUpdateDomain:
    async def test_patches_with_automatic_snapshots_when_set(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"message": "Updated"}
        route = respx_mock.patch("/v5/livedns/domains/example.com").mock(return_value=httpx.Response(200, json=payload))

        handler = await _get_handler(server, "livedns_update_domain")
        result = await handler(ctx, fqdn="example.com", automatic_snapshots=True)

        assert route.called
        assert route.calls.last.request.method == "PATCH"
        sent = json.loads(route.calls.last.request.content)
        assert sent == {"automatic_snapshots": True}
        assert result == payload

    async def test_omits_automatic_snapshots_when_none(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.patch("/v5/livedns/domains/example.com").mock(return_value=httpx.Response(200, json={}))

        handler = await _get_handler(server, "livedns_update_domain")
        await handler(ctx, fqdn="example.com", automatic_snapshots=None)

        assert route.called
        sent = json.loads(route.calls.last.request.content)
        assert sent == {}

    async def test_url_encodes_fqdn(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.patch("/v5/livedns/domains/has%2Fslash.com").mock(return_value=httpx.Response(200, json={}))

        handler = await _get_handler(server, "livedns_update_domain")
        await handler(ctx, fqdn="has/slash.com", automatic_snapshots=False)

        assert route.called
        assert route.calls.last.request.url.raw_path == b"/v5/livedns/domains/has%2Fslash.com"


@pytest.mark.mocked
class TestLivednsCreateRecord:
    async def test_posts_full_body_with_ttl(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        payload = {"message": "DNS Record Created"}
        route = respx_mock.post("/v5/livedns/domains/example.com/records").mock(
            return_value=httpx.Response(201, json=payload)
        )

        handler = await _get_handler(server, "livedns_create_record")
        result = await handler(
            ctx,
            fqdn="example.com",
            name="www",
            rrset_type="A",
            values=["1.2.3.4"],
            ttl=3600,
        )

        assert route.called
        assert route.calls.last.request.method == "POST"
        sent = json.loads(route.calls.last.request.content)
        assert sent == {
            "rrset_name": "www",
            "rrset_type": "A",
            "rrset_values": ["1.2.3.4"],
            "rrset_ttl": 3600,
        }
        assert result == payload

    async def test_omits_ttl_when_none(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.post("/v5/livedns/domains/example.com/records").mock(
            return_value=httpx.Response(201, json={})
        )

        handler = await _get_handler(server, "livedns_create_record")
        await handler(
            ctx,
            fqdn="example.com",
            name="www",
            rrset_type="A",
            values=["1.2.3.4"],
            ttl=None,
        )

        assert route.called
        sent = json.loads(route.calls.last.request.content)
        assert sent == {
            "rrset_name": "www",
            "rrset_type": "A",
            "rrset_values": ["1.2.3.4"],
        }
        assert "rrset_ttl" not in sent


@pytest.mark.mocked
class TestLivednsReplaceRecord:
    async def test_puts_body_to_correct_endpoint_with_ttl(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        payload = {"message": "DNS Record Replaced"}
        route = respx_mock.put("/v5/livedns/domains/example.com/records/www/A").mock(
            return_value=httpx.Response(201, json=payload)
        )

        handler = await _get_handler(server, "livedns_replace_record")
        result = await handler(
            ctx,
            fqdn="example.com",
            name="www",
            rrset_type="A",
            values=["5.6.7.8"],
            ttl=600,
        )

        assert route.called
        assert route.calls.last.request.method == "PUT"
        sent = json.loads(route.calls.last.request.content)
        assert sent == {"rrset_values": ["5.6.7.8"], "rrset_ttl": 600}
        assert result == payload

    async def test_omits_ttl_when_none(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.put("/v5/livedns/domains/example.com/records/www/A").mock(
            return_value=httpx.Response(201, json={})
        )

        handler = await _get_handler(server, "livedns_replace_record")
        await handler(
            ctx,
            fqdn="example.com",
            name="www",
            rrset_type="A",
            values=["5.6.7.8"],
            ttl=None,
        )

        assert route.called
        sent = json.loads(route.calls.last.request.content)
        assert sent == {"rrset_values": ["5.6.7.8"]}

    async def test_url_encodes_name_and_type(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.put("/v5/livedns/domains/example.com/records/rec%2Fwith%2Fslash/weird%2Ftype").mock(
            return_value=httpx.Response(201, json={})
        )

        handler = await _get_handler(server, "livedns_replace_record")
        await handler(
            ctx,
            fqdn="example.com",
            name="rec/with/slash",
            rrset_type="weird/type",
            values=["v1"],
        )

        assert route.called
        assert (
            route.calls.last.request.url.raw_path
            == b"/v5/livedns/domains/example.com/records/rec%2Fwith%2Fslash/weird%2Ftype"
        )


@pytest.mark.mocked
class TestLivednsReplaceZone:
    async def test_puts_items_body_to_correct_endpoint(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        items = [
            {"rrset_name": "@", "rrset_type": "A", "rrset_values": ["1.2.3.4"], "rrset_ttl": 3600},
            {"rrset_name": "www", "rrset_type": "CNAME", "rrset_values": ["@"]},
        ]
        payload = {"message": "Zone replaced"}
        route = respx_mock.put("/v5/livedns/domains/example.com/records").mock(
            return_value=httpx.Response(201, json=payload)
        )

        handler = await _get_handler(server, "livedns_replace_zone")
        result = await handler(ctx, fqdn="example.com", items=items)

        assert route.called
        assert route.calls.last.request.method == "PUT"
        sent = json.loads(route.calls.last.request.content)
        assert sent == {"items": items}
        assert result == payload


@pytest.mark.mocked
class TestLivednsDeleteRecord:
    async def test_deletes_correct_endpoint(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.delete("/v5/livedns/domains/example.com/records/www/A").mock(
            return_value=httpx.Response(204)
        )

        handler = await _get_handler(server, "livedns_delete_record")
        result = await handler(ctx, fqdn="example.com", name="www", rrset_type="A")

        assert route.called
        assert route.calls.last.request.method == "DELETE"
        # 204 No Content → empty dict per _parse_json invariant.
        assert result == {}

    async def test_url_encodes_name_and_type(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.delete("/v5/livedns/domains/example.com/records/rec%2Fwith%2Fslash/weird%2Ftype").mock(
            return_value=httpx.Response(204)
        )

        handler = await _get_handler(server, "livedns_delete_record")
        await handler(ctx, fqdn="example.com", name="rec/with/slash", rrset_type="weird/type")

        assert route.called
        assert route.calls.last.request.method == "DELETE"
        assert (
            route.calls.last.request.url.raw_path
            == b"/v5/livedns/domains/example.com/records/rec%2Fwith%2Fslash/weird%2Ftype"
        )


@pytest.mark.mocked
class TestLivednsDeleteAllRecords:
    async def test_deletes_correct_endpoint_and_returns_empty_dict_on_204(
        self, ctx: AsyncMock, respx_mock: Any, server: FastMCP
    ) -> None:
        route = respx_mock.delete("/v5/livedns/domains/example.com/records").mock(return_value=httpx.Response(204))

        handler = await _get_handler(server, "livedns_delete_all_records")
        result = await handler(ctx, fqdn="example.com")

        assert route.called
        assert route.calls.last.request.method == "DELETE"
        # No body sent.
        assert route.calls.last.request.content == b""
        # 204 → empty dict, not an error (per _parse_json invariant).
        assert result == {}


@pytest.mark.mocked
class TestLivednsCreateDnssecKey:
    async def test_posts_default_ksk_flags(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        payload = {"id": "key-uuid", "flags": 257}
        route = respx_mock.post("/v5/livedns/domains/example.com/keys").mock(
            return_value=httpx.Response(201, json=payload)
        )

        handler = await _get_handler(server, "livedns_create_dnssec_key")
        result = await handler(ctx, fqdn="example.com")

        assert route.called
        assert route.calls.last.request.method == "POST"
        sent = json.loads(route.calls.last.request.content)
        assert sent == {"flags": 257}
        assert result == payload

    async def test_posts_zsk_flags_when_set(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.post("/v5/livedns/domains/example.com/keys").mock(return_value=httpx.Response(201, json={}))

        handler = await _get_handler(server, "livedns_create_dnssec_key")
        await handler(ctx, fqdn="example.com", flags=256)

        assert route.called
        sent = json.loads(route.calls.last.request.content)
        assert sent == {"flags": 256}


@pytest.mark.mocked
class TestLivednsDeleteDnssecKey:
    async def test_deletes_correct_endpoint(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.delete("/v5/livedns/domains/example.com/keys/key-uuid").mock(
            return_value=httpx.Response(204)
        )

        handler = await _get_handler(server, "livedns_delete_dnssec_key")
        result = await handler(ctx, fqdn="example.com", key_id="key-uuid")

        assert route.called
        assert route.calls.last.request.method == "DELETE"
        assert result == {}

    async def test_url_encodes_key_id(self, ctx: AsyncMock, respx_mock: Any, server: FastMCP) -> None:
        route = respx_mock.delete("/v5/livedns/domains/example.com/keys/key%2Fweird").mock(
            return_value=httpx.Response(204)
        )

        handler = await _get_handler(server, "livedns_delete_dnssec_key")
        await handler(ctx, fqdn="example.com", key_id="key/weird")

        assert route.called
        assert route.calls.last.request.method == "DELETE"
        assert route.calls.last.request.url.raw_path == b"/v5/livedns/domains/example.com/keys/key%2Fweird"
