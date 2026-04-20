"""FastMCP server creation, lifespan, and mode / purchase gating."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import httpx
from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan

from gandi_mcp.clients.gandi import GandiClient
from gandi_mcp.config import GandiConfig
from gandi_mcp.errors import (
    GandiAuthError,
    GandiConnectionError,
    GandiError,
    GandiServerError,
    GandiTimeoutError,
)

logger = logging.getLogger(__name__)


@dataclass
class ServerContext:
    """Lifespan context passed to all tools via ``ctx.lifespan_context``."""

    config: GandiConfig
    client: GandiClient | None = None


def _classify_startup_error(exc: BaseException) -> str:
    """Convert a startup exception into a short, actionable operator hint."""
    if isinstance(exc, GandiAuthError):
        return "authentication rejected by Gandi — regenerate GANDI_TOKEN"
    if isinstance(exc, GandiTimeoutError):
        return "Gandi API did not respond in time — check network / GANDI_REQUEST_TIMEOUT"
    if isinstance(exc, GandiConnectionError):
        return "cannot reach api.gandi.net — check network / DNS / GANDI_API_BASE_URL"
    if isinstance(exc, GandiServerError):
        return "Gandi API returned 5xx — upstream may be unhealthy, retry later"
    if isinstance(exc, GandiError):
        return f"Gandi API error: {type(exc).__name__}"
    return f"unexpected error ({type(exc).__name__})"


def _build_lifespan(config: GandiConfig):  # type: ignore[no-untyped-def]
    """Build a lifespan closure bound to the caller-supplied config.

    Previously the lifespan re-read env vars, which meant the config passed
    to ``create_server`` was only used for visibility gating while the
    runtime safety asserts saw whatever env was in place at yield time.
    Closing over a single config keeps visibility and runtime layers in
    sync.
    """

    def _disable_all_tools(server: FastMCP | None) -> None:
        if server is not None:
            server.disable(tags={"gandi"})

    @lifespan  # type: ignore[arg-type]
    async def server_lifespan(server: FastMCP) -> AsyncIterator[ServerContext]:
        """Build the Gandi client, validate the PAT, and yield the context.

        On startup failure, tools are disabled and the reason is logged loudly
        (level ERROR, with the typed exception). Agents still see an empty
        tool list rather than tools that all raise — but operators get an
        actionable line in the logs instead of "validation returned False".
        """
        context = ServerContext(config=config)

        if not config.authenticated:
            logger.error("Gandi tools disabled: GANDI_TOKEN not configured")
            _disable_all_tools(server)
            yield context
            return

        assert config.gandi_token is not None
        client = GandiClient(
            base_url=config.gandi_api_base_url,
            token=config.gandi_token.get_secret_value(),
            sharing_id=config.gandi_sharing_id,
            timeout=config.gandi_request_timeout,
            max_retries=config.gandi_max_retries,
        )

        try:
            await client.validate_connection()
        except (GandiError, httpx.HTTPError) as exc:
            reason = _classify_startup_error(exc)
            logger.error("Gandi tools disabled: %s (%s)", reason, exc)
            await client.close()
            _disable_all_tools(server)
            yield context
            return

        context.client = client
        logger.info(
            "Gandi MCP ready — mode=%s, purchases=%s",
            config.gandi_mode.value,
            "allowed" if config.purchases_enabled else "BLOCKED",
        )

        try:
            yield context
        finally:
            try:
                await client.close()
            except (OSError, httpx.HTTPError):
                logger.exception("Error closing Gandi client")

    return server_lifespan


def create_server(config: GandiConfig | None = None) -> FastMCP:
    """Create and configure the FastMCP server."""
    if config is None:
        config = GandiConfig()

    server = FastMCP(
        name="gandi-mcp",
        instructions=(
            "Gandi MCP server — manage domains, DNS, mailboxes, billing, "
            "organizations, and certificates via the Gandi v5 API. Write and "
            "purchase tools are gated behind explicit env flags for safety."
        ),
        lifespan=_build_lifespan(config),
    )

    from gandi_mcp.tools import register_all_tools

    register_all_tools(server)

    # ── Safety gates (defense-in-depth #1: tool visibility) ──────────────
    # Hide the entire write surface in readonly mode.
    if not config.is_readwrite:
        server.disable(tags={"write"})
        logger.info("Read-only mode: write tools disabled")

    # Hide purchase tools unless explicitly opted in.
    # Note: purchase tools are also tagged {"write"}, so they're already
    # hidden in readonly mode — this catches the readwrite-without-purchases
    # case. Defense-in-depth #2 (runtime check) is inside each tool handler.
    if not config.purchases_enabled:
        server.disable(tags={"purchase"})
        logger.info("Purchase tools disabled (set GANDI_ALLOW_PURCHASES=true and GANDI_MODE=readwrite to enable)")

    return server
