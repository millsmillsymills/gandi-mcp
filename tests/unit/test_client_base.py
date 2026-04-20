"""Tests for BaseGandiClient request plumbing (sharing_id merge, etc.)."""

from __future__ import annotations

import httpx
import pytest
import respx

from gandi_mcp.clients.base import BaseGandiClient


class TestMergeSharingId:
    """Operator-configured sharing_id cannot be bypassed by callers."""

    def test_no_sharing_id_returns_params_unchanged(self) -> None:
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t")
        assert client._merge_sharing_id(None) is None
        assert client._merge_sharing_id({"per_page": 50}) == {"per_page": 50}

    def test_configured_sharing_id_injected(self) -> None:
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t", sharing_id="org-uuid")
        assert client._merge_sharing_id(None) == {"sharing_id": "org-uuid"}
        assert client._merge_sharing_id({"per_page": 50}) == {
            "per_page": 50,
            "sharing_id": "org-uuid",
        }

    def test_caller_matching_sharing_id_is_noop(self) -> None:
        """A caller passing the configured value is benign."""
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t", sharing_id="org-uuid")
        assert client._merge_sharing_id({"sharing_id": "org-uuid"}) == {"sharing_id": "org-uuid"}

    def test_caller_override_rejected(self) -> None:
        """A caller passing a different sharing_id is rejected (safety-gate)."""
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t", sharing_id="org-uuid")
        with pytest.raises(ValueError, match="managed by GANDI_SHARING_ID"):
            client._merge_sharing_id({"sharing_id": "attacker-uuid"})

    @pytest.mark.asyncio
    async def test_sharing_id_attached_to_every_request(self) -> None:
        """End-to-end: configured sharing_id appears on the wire."""
        client = BaseGandiClient(
            base_url="https://api.gandi.net",
            token="t",
            sharing_id="org-uuid",
            max_retries=1,
        )
        with respx.mock(base_url="https://api.gandi.net") as mock:
            route = mock.get("/v5/organization/user-info").mock(return_value=httpx.Response(200, json={}))
            await client.get("/v5/organization/user-info")
            assert route.called
            assert route.calls.last.request.url.params["sharing_id"] == "org-uuid"
        await client.close()
