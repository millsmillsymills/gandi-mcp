"""Organization tools (/v5/organization) — read-only surface."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from gandi_mcp.errors import handle_client_error
from gandi_mcp.tools._common import get_client


def register_organization_tools(mcp: FastMCP) -> None:
    """Register organization tools on the server."""

    @mcp.tool(tags={"gandi", "organization"})
    async def org_get_user_info(ctx: Context) -> dict[str, Any]:
        """Profile info for the token owner (name, email, lang, scope)."""
        try:
            return await get_client(ctx).get_user_info()
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "organization"})
    async def org_list_organizations(
        ctx: Context,
        name: str | None = None,
        permission: str | None = None,
        org_type: str | None = None,
        per_page: int = 100,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """List organizations the token can access.

        Args:
            name: Filter on organization name (substring match).
            permission: Filter by granted permission ("view", "admin", "billing").
            org_type: Filter by org type ("individual", "company", "association",
                "publicbody").
            per_page: Page size.
            page: Page number.
        """
        try:
            return await get_client(ctx).list_organizations(
                name=name, permission=permission, type=org_type, per_page=per_page, page=page
            )
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "organization"})
    async def org_get_organization(ctx: Context, org_id: str) -> dict[str, Any]:
        """Retrieve one organization by UUID.

        Args:
            org_id: Organization UUID (aka sharing_id).
        """
        try:
            return await get_client(ctx).get_organization(org_id)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "organization"})
    async def org_list_customers(
        ctx: Context,
        org_id: str,
        per_page: int = 100,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """List customers under a reseller org.

        Args:
            org_id: Reseller organization UUID.
            per_page: Page size.
            page: Page number.
        """
        try:
            return await get_client(ctx).list_customers(org_id, per_page=per_page, page=page)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "organization"})
    async def org_get_customer(ctx: Context, org_id: str, customer_id: str) -> dict[str, Any]:
        """Retrieve a specific customer of a reseller org.

        Args:
            org_id: Reseller organization UUID.
            customer_id: Customer UUID.
        """
        try:
            return await get_client(ctx).get_customer(org_id, customer_id)
        except Exception as e:
            handle_client_error(e)
