"""Pin the exact string outputs and tag sets produced by ``server.py`` (#85).

Mutmut surfaced that the operator-facing strings in
``_classify_startup_error`` and the visibility-tag literals in ``create_server``
drift silently under wrap / case mutations. The existing lifespan tests assert
the surfaced exception type but not the exact actionable hint, so a mutation
like ``return "XX...XX"`` slipped through.

Each test asserts an exact equality on the message (or an exact tag) so a
mutation that wraps the string, ALL-CAPS-es it, or replaces it with ``None``
fails immediately.
"""

from __future__ import annotations

import logging

import httpx
import pytest
import respx

from gandi_mcp.config import GandiConfig, GandiMode
from gandi_mcp.errors import (
    GandiAuthError,
    GandiConnectionError,
    GandiError,
    GandiNotFoundError,
    GandiServerError,
    GandiTimeoutError,
)
from gandi_mcp.server import _build_lifespan, _classify_startup_error, create_server

# ── _classify_startup_error: exact-equality on each branch ────────────────


class TestClassifyStartupError:
    """Each branch returns the canonical actionable hint verbatim.

    Mutmut produced ``"XX...XX"``, lowercase, and ALL-CAPS variants of every
    message — equality (not substring) is the only check that kills all three
    classes at once.
    """

    def test_auth_error(self) -> None:
        assert (
            _classify_startup_error(GandiAuthError("HTTP 401"))
            == "authentication rejected by Gandi — regenerate GANDI_TOKEN"
        )

    def test_timeout_error(self) -> None:
        assert (
            _classify_startup_error(GandiTimeoutError("slow"))
            == "Gandi API did not respond in time — check network / GANDI_REQUEST_TIMEOUT"
        )

    def test_connection_error(self) -> None:
        assert (
            _classify_startup_error(GandiConnectionError("dns"))
            == "cannot reach api.gandi.net — check network / DNS / GANDI_API_BASE_URL"
        )

    def test_server_error(self) -> None:
        assert (
            _classify_startup_error(GandiServerError("HTTP 503"))
            == "Gandi API returned 5xx — upstream may be unhealthy, retry later"
        )

    def test_generic_gandi_error_includes_exception_classname(self) -> None:
        """The fallback Gandi-error message embeds the exception ``__name__``.

        Pinned exactly so a mutation that uses ``type(None).__name__``
        ("NoneType") instead of ``type(exc).__name__`` fails.
        """
        assert _classify_startup_error(GandiNotFoundError("404")) == "Gandi API error: GandiNotFoundError"
        # Also pin the bare ``GandiError`` shape so a future contributor
        # widening the hierarchy can't drop the class name silently.
        assert _classify_startup_error(GandiError("x")) == "Gandi API error: GandiError"

    def test_unmapped_exception_uses_exception_classname(self) -> None:
        """The fallback branch ALSO embeds the exception class name (different mutant)."""
        assert _classify_startup_error(RuntimeError("boom")) == "unexpected error (RuntimeError)"
        assert _classify_startup_error(ValueError("nope")) == "unexpected error (ValueError)"


# ── create_server: instructions string + log message verbatim ──────────────


_INSTRUCTIONS = (
    "Gandi MCP server — manage domains, DNS, mailboxes, billing, "
    "organizations, and certificates via the Gandi v5 API. Write and "
    "purchase tools are gated behind explicit env flags for safety."
)


def _config(**overrides):  # type: ignore[no-untyped-def]
    defaults = {"_env_file": None, "gandi_token": "test-token"}
    defaults.update(overrides)
    return GandiConfig(**defaults)


class TestCreateServerInstructions:
    """The server-instructions string is part of the MCP handshake — pin it verbatim.

    Mutmut wrap-mutations (``"XX...XX"``), case mutations (lowercase, ALLCAPS),
    and the ``instructions=None`` mutation all change the exact string.
    """

    def test_instructions_match_canonical(self) -> None:
        server = create_server(_config())
        assert server.instructions == _INSTRUCTIONS

    def test_instructions_are_not_none(self) -> None:
        """Mutmut produces ``instructions=None``; assert truthy + str type."""
        server = create_server(_config())
        assert isinstance(server.instructions, str)
        assert server.instructions  # non-empty


class TestCreateServerHandlesNoneConfig:
    """Calling ``create_server()`` with no argument must use a default ``GandiConfig``.

    A mutmut survivor replaced ``config = GandiConfig()`` with ``config = None``;
    the next attribute access on ``config`` would crash. Constructing the
    default explicitly proves the branch is exercised.
    """

    def test_none_config_constructs_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # GandiConfig() reads env; clear the relevant vars so the default is deterministic.
        for var in ("GANDI_TOKEN", "GANDI_MODE", "GANDI_ALLOW_PURCHASES"):
            monkeypatch.delenv(var, raising=False)
        server = create_server()  # no arg → default config path
        assert server.name == "gandi-mcp"


class TestVisibilityLogMessages:
    """The mode-change log lines are operator-facing — pin the exact wording.

    Mutmut surfaced wrap, case, and ``None`` mutations on both readonly and
    purchases-disabled log calls.
    """

    def test_readonly_logs_canonical_message(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="gandi_mcp.server"):
            create_server(_config(gandi_mode=GandiMode.READONLY))
        messages = [r.message for r in caplog.records]
        assert "Read-only mode: write tools disabled" in messages

    def test_purchases_blocked_logs_canonical_message(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="gandi_mcp.server"):
            create_server(_config(gandi_mode=GandiMode.READWRITE, gandi_allow_purchases=False))
        messages = [r.message for r in caplog.records]
        assert "Purchase tools disabled (set GANDI_ALLOW_PURCHASES=true and GANDI_MODE=readwrite to enable)" in messages

    def test_full_access_emits_neither_disable_log(self, caplog: pytest.LogCaptureFixture) -> None:
        """When both flags are set, neither disable-info line should fire."""
        with caplog.at_level(logging.INFO, logger="gandi_mcp.server"):
            create_server(_config(gandi_mode=GandiMode.READWRITE, gandi_allow_purchases=True))
        messages = " ".join(r.message for r in caplog.records)
        assert "Read-only mode" not in messages
        assert "Purchase tools disabled" not in messages


# ── _build_lifespan: actually exercises the disable-all-tools tag set ──────


class TestLifespanDisablesGandiTagOnly:
    """When the lifespan disables tools, it must use the exact tag set ``{"gandi"}``.

    Mutmut survivors:
    - ``tags=None`` — would either crash or no-op; in either case, gandi tools
      remain visible after the no-auth path, which fails this test.
    - ``tags={"XXgandiXX"}`` / ``tags={"GANDI"}`` — no real tool has those tags,
      so the disable call is a no-op and gandi tools remain visible.
    - ``if server is None`` (inverted guard) — disable never fires for a
      real (non-None) server.

    A successful "no token" path must leave the visible tool list empty.
    """

    @pytest.mark.asyncio
    async def test_no_token_disables_every_gandi_tool(self) -> None:
        config = _config(gandi_token=None, gandi_mode=GandiMode.READWRITE, gandi_allow_purchases=True)
        server = create_server(config)
        lifespan = _build_lifespan(config)
        async with lifespan(server):
            visible = await server.list_tools()
            gandi_tools = [t for t in visible if "gandi" in (t.tags or set())]
            assert gandi_tools == [], (
                "lifespan failed to disable gandi-tagged tools — likely wrong tag set"
                f" (visible gandi tools: {[t.name for t in gandi_tools]})"
            )

    @pytest.mark.asyncio
    async def test_auth_failure_disables_every_gandi_tool(self) -> None:
        config = _config(gandi_token="t", gandi_mode=GandiMode.READWRITE, gandi_allow_purchases=True)
        server = create_server(config)
        lifespan = _build_lifespan(config)
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.get("/v5/organization/user-info").mock(return_value=httpx.Response(401, text="bad"))
            async with lifespan(server):
                visible = await server.list_tools()
                gandi_tools = [t for t in visible if "gandi" in (t.tags or set())]
                assert gandi_tools == [], (
                    "lifespan failed to disable gandi-tagged tools after auth failure"
                    f" (visible: {[t.name for t in gandi_tools]})"
                )


# ── create_server: lifespan is actually threaded through to FastMCP ────────


class TestCreateServerLifespanWiring:
    """``create_server`` must pass its built lifespan to ``FastMCP(lifespan=...)``.

    Mutmut surfaced three survivors that all leave the runtime lifespan
    misconfigured: ``lifespan=None``, ``lifespan=_build_lifespan(None)``, and
    dropping the kwarg entirely (FastMCP falls back to its no-op
    ``default_lifespan``). All three keep ``create_server`` returning a
    server, so a test that inspects only the returned object's visibility
    rules cannot tell them apart from the original.

    Two assertions pin them:
    1. ``mcp._lifespan is not default_lifespan`` — kills ``lifespan=None`` and
       the kwarg-removed mutation; both leave the FastMCP-supplied no-op in
       place.
    2. Driving ``mcp._lifespan(mcp)`` actually accesses ``config.authenticated`` —
       kills ``lifespan=_build_lifespan(None)`` because that closure's
       ``config`` is ``None`` and the first attribute access raises
       ``AttributeError`` before the lifespan can yield.
    """

    def test_lifespan_is_not_fastmcp_default(self) -> None:
        from fastmcp.server.server import default_lifespan

        server = create_server(_config())
        assert server._lifespan is not default_lifespan, (
            "create_server returned a server with FastMCP's default no-op lifespan; "
            "the gandi-mcp lifespan was not wired through (mutation likely changed "
            "the lifespan= kwarg to None or removed it)"
        )

    @pytest.mark.asyncio
    async def test_lifespan_uses_supplied_config(self) -> None:
        """Driving the wired lifespan must succeed with a real ``GandiConfig``.

        With ``_build_lifespan(None)`` baked in, the first ``config.authenticated``
        access inside the lifespan raises ``AttributeError`` on ``NoneType``,
        which fails this test. The no-token path is used so we don't have to
        mock the API — the lifespan short-circuits before any HTTP call.
        """
        config = _config(gandi_token=None, gandi_mode=GandiMode.READWRITE, gandi_allow_purchases=True)
        server = create_server(config)
        async with server._lifespan(server) as ctx:
            # ServerContext.config must be the config we passed in — proves the
            # closure captured the caller-supplied config, not None.
            assert ctx.config is config

    @pytest.mark.asyncio
    async def test_lifespan_short_circuits_to_disabled_tools_on_no_token(self) -> None:
        """End-to-end: a no-token config produces a server with no visible gandi tools.

        Distinguishes ``lifespan=_build_lifespan(None)`` (which would raise
        AttributeError before reaching ``disable``) from the original (which
        cleanly disables every ``gandi``-tagged tool).
        """
        config = _config(gandi_token=None, gandi_mode=GandiMode.READWRITE, gandi_allow_purchases=True)
        server = create_server(config)
        async with server._lifespan(server):
            visible = await server.list_tools()
            gandi_tools = [t for t in visible if "gandi" in (t.tags or set())]
            assert gandi_tools == [], (
                f"create_server's wired lifespan failed to disable gandi tools on no-token startup "
                f"(visible: {[t.name for t in gandi_tools]})"
            )
