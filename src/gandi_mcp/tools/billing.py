"""Billing tools (/v5/billing) — read-only surface."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from gandi_mcp.errors import handle_client_error
from gandi_mcp.tools._common import get_client


def register_billing_tools(mcp: FastMCP) -> None:
    """Register billing tools on the server."""

    @mcp.tool(tags={"gandi", "billing"})
    async def billing_get_info(ctx: Context) -> dict[str, Any]:
        """Billing summary for the token owner (prepaid balance, annual spend, tier)."""
        try:
            return await get_client(ctx).get_billing_info()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "billing"})
    async def billing_get_info_for_org(ctx: Context, sharing_id: str) -> dict[str, Any]:
        """Billing summary for a specific organization.

        Args:
            sharing_id: Organization UUID.
        """
        try:
            return await get_client(ctx).get_billing_info_for_org(sharing_id)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "billing"})
    async def billing_get_price_catalog(
        ctx: Context,
        product_type: str,
        currency: str | None = None,
        country: str | None = None,
        grid: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve pricing for a product category (no charge).

        Useful for previewing costs before any purchase-mode operation.

        Args:
            product_type: One of "domain", "domain_option", "certificate",
                "mailbox", "cloud", "simplehosting", "openstack", "tmch",
                "phoneadvisory".
            currency: ISO currency code ("USD", "EUR").
            country: ISO country code — affects tax-inclusive prices.
            grid: Pricing grid level ("A", "B", "C", "D", "E").
        """
        try:
            return await get_client(ctx).get_price_catalog(product_type, currency=currency, country=country, grid=grid)
        except Exception as e:
            handle_client_error(e)
