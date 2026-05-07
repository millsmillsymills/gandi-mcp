"""SSL certificate tools (/v5/certificate)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from gandi_mcp.errors import handle_client_error
from gandi_mcp.tools._common import (
    assert_purchases_allowed,
    assert_readwrite,
    get_client,
)


def register_certificate_tools(mcp: FastMCP) -> None:
    """Register certificate tools on the server."""

    # ── Read ────────────────────────────────────────────────────────────

    @mcp.tool(tags={"gandi", "certificate"})
    async def gandi_cert_list(
        ctx: Context,
        status: str | None = None,
        per_page: int = 100,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """List issued SSL certificates.

        Args:
            status: Filter by status ("valid", "expired", "revoked",
                "pending", "replaced").
            per_page: Page size.
            page: Page number.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            return await get_client(ctx).cert_list(status=status, per_page=per_page, page=page)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "certificate"})
    async def gandi_cert_get(ctx: Context, cert_id: str) -> dict[str, Any]:
        """Retrieve details for a specific certificate.

        Args:
            cert_id: Certificate UUID.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            return await get_client(ctx).cert_get(cert_id)
        except Exception as e:
            handle_client_error(e)

    # ── Write (non-purchasing) ──────────────────────────────────────────

    @mcp.tool(
        tags={"gandi", "certificate", "write"},
        annotations={"readOnlyHint": False, "destructiveHint": True},
    )
    async def gandi_cert_revoke(ctx: Context, cert_id: str) -> dict[str, Any]:
        """Revoke an issued certificate.

        Args:
            cert_id: Certificate UUID.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            assert_readwrite(ctx, "revoke certificate")
            return await get_client(ctx).cert_revoke(cert_id)
        except Exception as e:
            handle_client_error(e)

    # ── Purchasing (DOUBLE-GATED) ───────────────────────────────────────

    @mcp.tool(
        tags={"gandi", "certificate", "write", "purchase"},
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )
    async def gandi_cert_issue(ctx: Context, data: dict[str, Any]) -> dict[str, Any]:
        """Issue a new SSL certificate (SPENDS MONEY).

        Requires GANDI_MODE=readwrite AND GANDI_ALLOW_PURCHASES=true.

        Args:
            data: Full issuance payload per the Gandi certificate schema —
                must include ``cn``, ``package``, ``duration``, a CSR, and a
                DCV method.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            assert_readwrite(ctx, "issue certificate")
            assert_purchases_allowed(ctx, "issue certificate")
            return await get_client(ctx).cert_issue(data)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "certificate", "write", "purchase"},
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )
    async def gandi_cert_renew(ctx: Context, cert_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Renew an existing certificate (SPENDS MONEY).

        Requires GANDI_MODE=readwrite AND GANDI_ALLOW_PURCHASES=true.

        Args:
            cert_id: Certificate UUID.
            data: Renewal payload (new CSR, duration, DCV method).


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            assert_readwrite(ctx, "renew certificate")
            assert_purchases_allowed(ctx, "renew certificate")
            return await get_client(ctx).cert_renew(cert_id, data)
        except Exception as e:
            handle_client_error(e)
