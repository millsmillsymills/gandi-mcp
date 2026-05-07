"""Runtime safety-gate invariants (closes #12).

The project promises defense-in-depth: tool visibility is one layer, and every
write/purchase handler ALSO runs `assert_readwrite` / `assert_purchases_allowed`
at runtime so a stale client-side tool cache can't slip a write through. Until
now only the visibility layer was tested — this module pins the runtime and
tag invariants.
"""

from __future__ import annotations

from typing import Any, ClassVar
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from gandi_mcp.clients.base import BaseGandiClient
from gandi_mcp.config import GandiConfig, GandiMode
from gandi_mcp.errors import (
    GandiPurchaseBlockedError,
    GandiReadOnlyError,
    GandiTimeoutError,
)
from gandi_mcp.server import ServerContext, create_server
from gandi_mcp.tools._common import assert_purchases_allowed, assert_readwrite


def _ctx(config: GandiConfig) -> Any:
    """Minimal fake Context with the given config on lifespan_context.

    Real fastmcp.Context has lifespan_context as a property; use a plain mock
    so tests can set the attribute directly. Handlers under test only read
    ``ctx.lifespan_context.config``.
    """
    ctx = MagicMock()
    ctx.lifespan_context = ServerContext(config=config)
    return ctx


@pytest.fixture
def readonly_ctx() -> Any:
    return _ctx(GandiConfig(_env_file=None, gandi_token="t", gandi_mode=GandiMode.READONLY))


@pytest.fixture
def readwrite_ctx() -> Any:
    return _ctx(GandiConfig(_env_file=None, gandi_token="t", gandi_mode=GandiMode.READWRITE))


@pytest.fixture
def full_ctx() -> Any:
    return _ctx(
        GandiConfig(
            _env_file=None,
            gandi_token="t",
            gandi_mode=GandiMode.READWRITE,
            gandi_allow_purchases=True,
        )
    )


class TestAssertReadwrite:
    def test_readonly_raises(self, readonly_ctx: Any) -> None:
        with pytest.raises(GandiReadOnlyError, match="read-only mode"):
            assert_readwrite(readonly_ctx, "delete thing")

    def test_readwrite_passes(self, readwrite_ctx: Any) -> None:
        assert_readwrite(readwrite_ctx, "delete thing")  # no raise

    def test_full_passes(self, full_ctx: Any) -> None:
        assert_readwrite(full_ctx, "delete thing")  # no raise


class TestAssertPurchasesAllowed:
    def test_readonly_raises(self, readonly_ctx: Any) -> None:
        with pytest.raises(GandiPurchaseBlockedError, match="purchases are disabled"):
            assert_purchases_allowed(readonly_ctx, "register domain")

    def test_readwrite_without_purchases_raises(self, readwrite_ctx: Any) -> None:
        with pytest.raises(GandiPurchaseBlockedError, match="purchases are disabled"):
            assert_purchases_allowed(readwrite_ctx, "register domain")

    def test_full_passes(self, full_ctx: Any) -> None:
        assert_purchases_allowed(full_ctx, "register domain")  # no raise


class TestTagInvariants:
    """Tag classification must match handler-level asserts and annotations."""

    # Single source of truth for the purchase surface. Adding a tool that spends
    # money requires adding its name here — any mismatch with the {"write",
    # "purchase"} tag set fails the test.
    EXPECTED_PURCHASE_TOOLS: ClassVar[set[str]] = {
        "gandi_domain_register",
        "gandi_domain_renew",
        "gandi_domain_transfer_in",
        "gandi_email_create_mailbox",
        "gandi_email_create_slot",
        "gandi_email_renew_mailbox",
        "gandi_cert_issue",
        "gandi_cert_renew",
    }

    async def test_expected_purchase_tools_carry_purchase_tag(self) -> None:
        server = create_server(
            GandiConfig(
                _env_file=None,
                gandi_token="t",
                gandi_mode=GandiMode.READWRITE,
                gandi_allow_purchases=True,
            )
        )
        tools = {t.name: t for t in await server.list_tools()}
        for name in self.EXPECTED_PURCHASE_TOOLS:
            tool = tools.get(name)
            assert tool is not None, f"purchase tool {name} missing from registry"
            assert "purchase" in tool.tags, f"{name} missing 'purchase' tag"
            assert "write" in tool.tags, f"{name} missing 'write' tag"

    async def test_no_unexpected_purchase_tools(self) -> None:
        """A tool gaining the 'purchase' tag without being listed above is a regression."""
        server = create_server(
            GandiConfig(
                _env_file=None,
                gandi_token="t",
                gandi_mode=GandiMode.READWRITE,
                gandi_allow_purchases=True,
            )
        )
        purchase_tools = {t.name for t in await server.list_tools() if "purchase" in t.tags}
        assert purchase_tools == self.EXPECTED_PURCHASE_TOOLS

    async def test_purchase_implies_write(self) -> None:
        """Every 'purchase' tool must also be 'write' — the cascading disable relies on it."""
        server = create_server(
            GandiConfig(
                _env_file=None,
                gandi_token="t",
                gandi_mode=GandiMode.READWRITE,
                gandi_allow_purchases=True,
            )
        )
        for tool in await server.list_tools():
            if "purchase" in tool.tags:
                assert "write" in tool.tags, f"{tool.name} is purchase but not write"

    async def test_write_tools_have_readonly_hint_false(self) -> None:
        server = create_server(
            GandiConfig(
                _env_file=None,
                gandi_token="t",
                gandi_mode=GandiMode.READWRITE,
                gandi_allow_purchases=True,
            )
        )
        for tool in await server.list_tools():
            if "write" in tool.tags:
                hint = getattr(tool.annotations, "readOnlyHint", None) if tool.annotations else None
                assert hint is False, f"{tool.name}: write tool must have readOnlyHint=False"


class TestTimeoutRetryPolicy:
    """Non-idempotent methods must NOT retry on timeout (no double-spend)."""

    @pytest.mark.asyncio
    async def test_post_timeout_attempts_exactly_once(self) -> None:
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=3)
        with respx.mock(base_url="https://api.gandi.net") as mock:
            route = mock.post("/v5/domain/domains").mock(
                side_effect=httpx.ReadTimeout("read timeout"),
            )
            with pytest.raises(GandiTimeoutError):
                await client.post("/v5/domain/domains", json={})
            # Critical invariant: the server may have processed the write.
            # A retry could double-spend on purchase endpoints.
            assert route.call_count == 1
        await client.close()

    @pytest.mark.asyncio
    async def test_put_timeout_attempts_exactly_once(self) -> None:
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=3)
        with respx.mock(base_url="https://api.gandi.net") as mock:
            route = mock.put("/v5/domain/domains/example.com/authinfo").mock(
                side_effect=httpx.ReadTimeout("read timeout"),
            )
            with pytest.raises(GandiTimeoutError):
                await client.put("/v5/domain/domains/example.com/authinfo")
            assert route.call_count == 1
        await client.close()

    @pytest.mark.asyncio
    async def test_delete_timeout_attempts_exactly_once(self) -> None:
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=3)
        with respx.mock(base_url="https://api.gandi.net") as mock:
            route = mock.delete("/v5/domain/domains/example.com").mock(
                side_effect=httpx.ReadTimeout("read timeout"),
            )
            with pytest.raises(GandiTimeoutError):
                await client.delete("/v5/domain/domains/example.com")
            assert route.call_count == 1
        await client.close()

    @pytest.mark.asyncio
    async def test_patch_timeout_attempts_exactly_once(self) -> None:
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=3)
        with respx.mock(base_url="https://api.gandi.net") as mock:
            route = mock.patch("/v5/domain/domains/example.com/autorenew").mock(
                side_effect=httpx.ReadTimeout("read timeout"),
            )
            with pytest.raises(GandiTimeoutError):
                await client.patch("/v5/domain/domains/example.com/autorenew", json={})
            assert route.call_count == 1
        await client.close()
