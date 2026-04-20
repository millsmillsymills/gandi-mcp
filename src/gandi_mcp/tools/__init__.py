"""MCP tool definitions for the Gandi v5 API."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_all_tools(mcp: FastMCP) -> None:
    """Register every Gandi tool on the server.

    All tools carry the ``"gandi"`` tag so the lifespan can disable the whole
    surface if authentication fails.
    """
    from gandi_mcp.tools.billing import register_billing_tools
    from gandi_mcp.tools.certificate import register_certificate_tools
    from gandi_mcp.tools.domain import register_domain_tools
    from gandi_mcp.tools.email import register_email_tools
    from gandi_mcp.tools.livedns import register_livedns_tools
    from gandi_mcp.tools.organization import register_organization_tools

    register_organization_tools(mcp)
    register_billing_tools(mcp)
    register_domain_tools(mcp)
    register_livedns_tools(mcp)
    register_email_tools(mcp)
    register_certificate_tools(mcp)
    logger.info("Registered all Gandi tools")
