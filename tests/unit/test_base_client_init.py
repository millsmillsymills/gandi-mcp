"""Pinning tests for BaseGandiClient.__init__ wiring.

These tests assert that constructor defaults, header keys/values, timeout
threading, and base-URL normalization match the contract that the rest of
the system relies on. They exist primarily to kill mutmut survivors in the
``__init__`` and ``_merge_sharing_id`` clusters (issue #83).
"""

from __future__ import annotations

import pytest

from gandi_mcp import __version__
from gandi_mcp.clients.base import BaseGandiClient


class TestInitDefaults:
    """Default values for ``timeout`` and ``max_retries`` are wire-load-bearing."""

    @pytest.mark.asyncio
    async def test_default_timeout_is_30_seconds(self) -> None:
        """``timeout`` defaults to 30 seconds (pins mutmut __init__ #1, #26)."""
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t")
        try:
            assert client._client.timeout.connect == 30
            assert client._client.timeout.read == 30
            assert client._client.timeout.write == 30
            assert client._client.timeout.pool == 30
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_default_max_retries_is_3(self) -> None:
        """``max_retries`` defaults to 3 (pins mutmut __init__ #2)."""
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t")
        try:
            assert client._max_retries == 3
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_custom_timeout_propagates_to_client(self) -> None:
        """A non-default ``timeout`` reaches the underlying httpx client.

        Pins mutmut __init__ #8 (``timeout=None``), #11 (timeout kwarg
        elided — falls back to httpx default of 5s), and #26
        (``httpx.Timeout(None)`` — disables timeout).
        """
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t", timeout=7)
        try:
            assert client._client.timeout.connect == 7
            assert client._client.timeout.read == 7
            assert client._client.timeout.write == 7
            assert client._client.timeout.pool == 7
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_custom_max_retries_propagates(self) -> None:
        """A non-default ``max_retries`` is stored verbatim."""
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=5)
        try:
            assert client._max_retries == 5
        finally:
            await client.close()


class TestInitBaseUrl:
    """``base_url`` is normalized via ``rstrip(\'/\')`` — only trailing slashes."""

    @pytest.mark.asyncio
    async def test_trailing_slash_stripped(self) -> None:
        """Pins mutmut __init__ #12 (``rstrip(None)``) and #13 (``lstrip(\'/\')``)."""
        client = BaseGandiClient(base_url="https://api.gandi.net/", token="t")
        try:
            assert str(client._client.base_url) == "https://api.gandi.net"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_only_slashes_are_stripped(self) -> None:
        """Pins mutmut __init__ #14 (``rstrip(\'XX/XX\')`` would also strip ``X``).

        With ``rstrip("/")`` the trailing ``XX`` survives; mutmut #14 substitutes
        ``rstrip("XX/XX")`` which would also peel them off.
        """
        client = BaseGandiClient(base_url="https://api.gandi.net/v1XX", token="t")
        try:
            assert client._client.base_url.path == "/v1XX/"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_no_trailing_slash_unchanged(self) -> None:
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t")
        try:
            assert str(client._client.base_url) == "https://api.gandi.net"
        finally:
            await client.close()


class TestInitHeaders:
    """Header keys are case-sensitive on the wire (httpx preserves raw casing)."""

    @pytest.mark.asyncio
    async def test_authorization_header_exact(self) -> None:
        """Pins mutmut __init__ #7, #10 (headers omitted), #15-17 (key casing).

        Header keys must be exactly ``Authorization`` — httpx preserves the
        original case in ``.raw`` even though lookups are case-insensitive.
        """
        client = BaseGandiClient(base_url="https://api.gandi.net", token="my-token")
        try:
            raw = dict(client._client.headers.raw)
            assert b"Authorization" in raw
            assert b"authorization" not in raw
            assert b"AUTHORIZATION" not in raw
            assert b"XXAuthorizationXX" not in raw
            assert raw[b"Authorization"] == b"Bearer my-token"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_accept_header_exact(self) -> None:
        """Pins mutmut __init__ #18-22 (Accept key casing / value casing)."""
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t")
        try:
            raw = dict(client._client.headers.raw)
            assert b"Accept" in raw
            assert b"accept" not in raw
            assert b"ACCEPT" not in raw
            assert b"XXAcceptXX" not in raw
            assert raw[b"Accept"] == b"application/json"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_user_agent_header_exact(self) -> None:
        """Pins mutmut __init__ #23-25 (User-Agent key casing)."""
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t")
        try:
            raw = dict(client._client.headers.raw)
            assert b"User-Agent" in raw
            assert b"user-agent" not in raw
            assert b"USER-AGENT" not in raw
            assert b"XXUser-AgentXX" not in raw
            value = raw[b"User-Agent"].decode("ascii")
            assert value == (f"gandi-mcp/{__version__} (+https://github.com/millsmillsymills/gandi-mcp)")
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_token_interpolated_into_bearer_value(self) -> None:
        """Bearer prefix is literal; the token is appended verbatim."""
        client = BaseGandiClient(base_url="https://api.gandi.net", token="abc123")
        try:
            raw = dict(client._client.headers.raw)
            assert raw[b"Authorization"] == b"Bearer abc123"
        finally:
            await client.close()


class TestMergeSharingIdErrorMessage:
    """The override-rejection error message is operator-facing and must be stable."""

    def test_override_rejection_message_text_exact(self) -> None:
        """Pins mutmut ``_merge_sharing_id`` #12 (``XX...XX`` marker insertion)."""
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t", sharing_id="org-uuid")
        with pytest.raises(ValueError, match="managed by GANDI_SHARING_ID") as excinfo:
            client._merge_sharing_id({"sharing_id": "attacker-uuid"})
        assert str(excinfo.value) == ("sharing_id is managed by GANDI_SHARING_ID; do not pass it per-request")
