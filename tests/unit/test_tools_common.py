"""Direct unit tests for ``gandi_mcp.tools._common`` (closes #86).

The four helpers in this module are the runtime safety gate the AST walker
(``test_safety_gates.py``) pins statically. Their behavior is exercised
indirectly by every tool handler test, but those live higher in the test
pyramid — outside the unit suite mutmut scopes over. Pinning the behavior
in dedicated unit tests lets mutmut measure kill rate on this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest

from gandi_mcp.errors import GandiPurchaseBlockedError, GandiReadOnlyError
from gandi_mcp.tools._common import (
    assert_purchases_allowed,
    assert_readwrite,
    get_client,
    get_server_context,
)

if TYPE_CHECKING:
    from gandi_mcp.config import GandiConfig


@dataclass
class _FakeCtx:
    """Stand-in for ``ServerContext`` — mirrors the shape used by tool handlers.

    Defined locally rather than imported from ``tests/conftest.py`` so the
    mutmut mirror tree (which lives outside the original pytest rootdir)
    can resolve the test in isolation.
    """

    client: Any = None
    config: GandiConfig | None = None
    clients: dict[str, Any] = field(default_factory=dict)


def _build_ctx(config: GandiConfig, client: Any = None) -> AsyncMock:
    ctx = AsyncMock()
    ctx.lifespan_context = _FakeCtx(client=client, config=config)
    return ctx


class TestGetServerContext:
    def test_returns_lifespan_context_unchanged(self, readonly_config) -> None:  # type: ignore[no-untyped-def]
        """``get_server_context`` is a typed pass-through to ``ctx.lifespan_context``."""
        ctx = _build_ctx(readonly_config)
        assert get_server_context(ctx) is ctx.lifespan_context


class TestGetClient:
    def test_returns_client_when_initialized(self, readonly_config) -> None:  # type: ignore[no-untyped-def]
        """When the lifespan stored a client, ``get_client`` returns it unchanged."""
        sentinel = object()
        ctx = _build_ctx(readonly_config, client=sentinel)
        assert get_client(ctx) is sentinel

    def test_raises_runtime_error_when_client_missing(self, readonly_config) -> None:  # type: ignore[no-untyped-def]
        """``client is None`` reflects a lifespan failure — must raise loudly.

        Any tool reaching ``get_client`` without an initialised client is a
        bug in the lifespan or a stale server instance; the message points
        contributors at the lifespan's disable-all-tools path.
        """
        ctx = _build_ctx(readonly_config, client=None)
        with pytest.raises(RuntimeError, match="not initialized"):
            get_client(ctx)

    def test_raises_when_context_has_no_client_attr(self) -> None:
        """A ``_FakeCtx`` with a default ``client=None`` raises too."""
        from gandi_mcp.config import GandiConfig, GandiMode

        config = GandiConfig(_env_file=None, gandi_token="t", gandi_mode=GandiMode.READONLY)
        ctx = _build_ctx(config)
        assert isinstance(ctx.lifespan_context, _FakeCtx)
        with pytest.raises(RuntimeError, match="not initialized"):
            get_client(ctx)


class TestAssertReadwrite:
    def test_noop_in_readwrite_mode(self, readwrite_config) -> None:  # type: ignore[no-untyped-def]
        """In readwrite mode, the gate is a no-op and returns ``None``."""
        ctx = _build_ctx(readwrite_config)
        assert assert_readwrite(ctx, "register domain") is None

    def test_noop_in_readwrite_with_purchases(self, readwrite_with_purchases_config) -> None:  # type: ignore[no-untyped-def]
        """The purchases-enabled config is a superset of readwrite — also no-op."""
        ctx = _build_ctx(readwrite_with_purchases_config)
        assert assert_readwrite(ctx, "register domain") is None

    def test_raises_readonly_in_readonly_mode(self, readonly_config) -> None:  # type: ignore[no-untyped-def]
        """In readonly mode, the gate raises and the action verb appears in the message.

        The verb is load-bearing — the agent needs to see *which* write was
        blocked so it can decide whether to ask the operator to flip
        ``GANDI_MODE``.
        """
        ctx = _build_ctx(readonly_config)
        with pytest.raises(GandiReadOnlyError, match="register domain"):
            assert_readwrite(ctx, "register domain")

    def test_error_mentions_readonly_env_flag(self, readonly_config) -> None:  # type: ignore[no-untyped-def]
        """The error names ``GANDI_MODE=readonly`` so an operator knows what to flip."""
        ctx = _build_ctx(readonly_config)
        with pytest.raises(GandiReadOnlyError, match="GANDI_MODE=readonly"):
            assert_readwrite(ctx, "any write")

    def test_error_message_is_canonical(self, readonly_config) -> None:  # type: ignore[no-untyped-def]
        """Pin the exact message verbatim — kills wrap / case / ``None`` mutations.

        Substring matches survive a ``"XX...XX"`` wrap mutation because the
        inner substring is preserved. Equality on the full f-string output
        catches every variant, including ``GandiReadOnlyError(None)`` whose
        ``str(exc)`` is ``"None"``.
        """
        ctx = _build_ctx(readonly_config)
        with pytest.raises(GandiReadOnlyError) as exc_info:
            assert_readwrite(ctx, "register domain")
        assert str(exc_info.value) == "Cannot register domain in read-only mode (GANDI_MODE=readonly)"

    def test_error_message_interpolates_action(self, readonly_config) -> None:  # type: ignore[no-untyped-def]
        """The ``action`` argument is interpolated verbatim — two cases pin it."""
        ctx = _build_ctx(readonly_config)
        for action in ("delete mailbox", "transfer-out domain"):
            with pytest.raises(GandiReadOnlyError) as exc_info:
                assert_readwrite(ctx, action)
            assert str(exc_info.value) == f"Cannot {action} in read-only mode (GANDI_MODE=readonly)"


class TestAssertPurchasesAllowed:
    def test_noop_when_purchases_enabled(self, readwrite_with_purchases_config) -> None:  # type: ignore[no-untyped-def]
        """When both flags are set, the gate is a no-op and returns ``None``."""
        ctx = _build_ctx(readwrite_with_purchases_config)
        assert assert_purchases_allowed(ctx, "register domain") is None

    def test_raises_in_readwrite_without_purchases(self, readwrite_config) -> None:  # type: ignore[no-untyped-def]
        """Readwrite alone is not enough — purchases must be explicitly enabled."""
        ctx = _build_ctx(readwrite_config)
        with pytest.raises(GandiPurchaseBlockedError, match="register domain"):
            assert_purchases_allowed(ctx, "register domain")

    def test_raises_in_readonly_mode(self, readonly_config) -> None:  # type: ignore[no-untyped-def]
        """In readonly mode, the purchase gate also blocks.

        Note: handlers run ``assert_readwrite`` first, so this path is
        normally pre-empted. We pin the behavior here in case a future
        refactor reorders the calls.
        """
        ctx = _build_ctx(readonly_config)
        with pytest.raises(GandiPurchaseBlockedError):
            assert_purchases_allowed(ctx, "register domain")

    def test_error_mentions_allow_purchases_env_flag(self, readwrite_config) -> None:  # type: ignore[no-untyped-def]
        """The error hint names ``GANDI_ALLOW_PURCHASES`` so an operator can flip it."""
        ctx = _build_ctx(readwrite_config)
        with pytest.raises(GandiPurchaseBlockedError, match="GANDI_ALLOW_PURCHASES"):
            assert_purchases_allowed(ctx, "register domain")

    def test_error_message_is_canonical(self, readwrite_config) -> None:  # type: ignore[no-untyped-def]
        """Pin the exact purchase-blocked message verbatim.

        Substring matches (``"register domain"`` / ``"GANDI_ALLOW_PURCHASES"``)
        survive ``"XX...XX"`` wrap mutations because the inner substring is
        preserved. Equality on the full f-string catches every variant —
        including ``GandiPurchaseBlockedError(None)`` which stringifies to
        ``"None"``.
        """
        ctx = _build_ctx(readwrite_config)
        with pytest.raises(GandiPurchaseBlockedError) as exc_info:
            assert_purchases_allowed(ctx, "register domain")
        assert str(exc_info.value) == (
            "Cannot register domain — purchases are disabled (set GANDI_ALLOW_PURCHASES=true)"
        )

    def test_error_message_interpolates_action(self, readwrite_config) -> None:  # type: ignore[no-untyped-def]
        """The ``action`` argument is interpolated verbatim — two cases pin it."""
        ctx = _build_ctx(readwrite_config)
        for action in ("renew domain", "create mailbox"):
            with pytest.raises(GandiPurchaseBlockedError) as exc_info:
                assert_purchases_allowed(ctx, action)
            assert str(exc_info.value) == (f"Cannot {action} — purchases are disabled (set GANDI_ALLOW_PURCHASES=true)")
