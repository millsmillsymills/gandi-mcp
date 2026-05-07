"""MCP tool definitions for the Gandi v5 API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_read_tools(mcp: FastMCP) -> None:
    """Register every read-only Gandi tool.

    PROTO-005 calls for the read surface and the write surface to be
    registerable independently. Operators or tests that want a strictly
    read-only server can call this function alone.
    """
    from gandi_mcp.tools.billing import register_billing_read_tools
    from gandi_mcp.tools.certificate import register_certificate_read_tools
    from gandi_mcp.tools.domain import register_domain_read_tools
    from gandi_mcp.tools.email import register_email_read_tools
    from gandi_mcp.tools.livedns import register_livedns_read_tools
    from gandi_mcp.tools.organization import register_organization_read_tools

    register_organization_read_tools(mcp)
    register_billing_read_tools(mcp)
    register_domain_read_tools(mcp)
    register_livedns_read_tools(mcp)
    register_email_read_tools(mcp)
    register_certificate_read_tools(mcp)


def register_write_tools(mcp: FastMCP) -> None:
    """Register every state-changing Gandi tool (writes + purchases).

    Pairs with ``register_read_tools`` so callers can choose to attach the
    write surface separately. Defense-in-depth still applies: each tool's
    handler runs ``assert_readwrite`` (and ``assert_purchases_allowed`` for
    purchase tools), and ``server.py`` continues to gate visibility via
    ``mcp.disable(tags={"write"})`` when ``GANDI_MODE != readwrite``.
    """
    from gandi_mcp.tools.certificate import (
        register_certificate_purchase_tools,
        register_certificate_write_tools,
    )
    from gandi_mcp.tools.domain import (
        register_domain_purchase_tools,
        register_domain_write_tools,
    )
    from gandi_mcp.tools.email import (
        register_email_purchase_tools,
        register_email_write_tools,
    )
    from gandi_mcp.tools.livedns import register_livedns_write_tools

    register_domain_write_tools(mcp)
    register_domain_purchase_tools(mcp)
    register_livedns_write_tools(mcp)
    register_email_write_tools(mcp)
    register_email_purchase_tools(mcp)
    register_certificate_write_tools(mcp)
    register_certificate_purchase_tools(mcp)


def register_all_tools(mcp: FastMCP) -> None:
    """Register every Gandi tool on the server.

    All tools carry the ``"gandi"`` tag so the lifespan can disable the whole
    surface if authentication fails. Read- and write-tier visibility is
    further gated by tags in ``server.py`` based on ``config.writes_enabled``
    and ``config.purchases_enabled``.
    """
    register_read_tools(mcp)
    register_write_tools(mcp)
    logger.info("Registered all Gandi tools")
