"""Tests for URL path-segment percent-encoding in GandiClient."""

from __future__ import annotations

import httpx
import pytest
import respx

from gandi_mcp.clients.gandi import GandiClient


@pytest.fixture
def client() -> GandiClient:
    return GandiClient(
        base_url="https://api.gandi.net",
        token="t",
        timeout=5,
        max_retries=1,
    )


class TestPathSegmentEncoding:
    """User-supplied path segments must be percent-encoded to prevent path shifting."""

    @pytest.mark.asyncio
    async def test_slash_in_dns_record_name_is_encoded(self, client: GandiClient) -> None:
        """A record name containing `/` must not shift into a different API path."""
        with respx.mock(base_url="https://api.gandi.net") as mock:
            route = mock.get(
                "/v5/livedns/domains/example.com/records/has%2Fslash/A",
            ).mock(return_value=httpx.Response(200, json=[]))
            await client.livedns_list_records("example.com", name="has/slash", rrset_type="A")
            assert route.called
        await client.close()

    @pytest.mark.asyncio
    async def test_underscore_and_dot_encoded_safely(self, client: GandiClient) -> None:
        """_acme-challenge.foo is a legitimate DNS name; encoder keeps it intact-ish.

        urllib.parse.quote with safe="" encodes dots (but underscore and hyphen
        are unreserved). Gandi accepts %2E dots in path segments.
        """
        with respx.mock(base_url="https://api.gandi.net") as mock:
            route = mock.get(
                "/v5/livedns/domains/example.com/records/_acme-challenge%2Efoo/TXT",
            ).mock(return_value=httpx.Response(200, json=[]))
            await client.livedns_list_records("example.com", name="_acme-challenge.foo", rrset_type="TXT")
            assert route.called
        await client.close()

    @pytest.mark.asyncio
    async def test_question_mark_in_segment_is_encoded(self, client: GandiClient) -> None:
        """A `?` in a segment must be encoded so it doesn't start the query string."""
        with respx.mock(base_url="https://api.gandi.net") as mock:
            route = mock.delete(
                "/v5/email/forwards/example.com/weird%3Fsource",
            ).mock(return_value=httpx.Response(204))
            await client.email_delete_forward("example.com", "weird?source")
            assert route.called
        await client.close()
