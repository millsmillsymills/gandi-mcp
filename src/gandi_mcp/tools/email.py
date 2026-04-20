"""Email tools (/v5/email) — mailboxes, forwards, slots."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from gandi_mcp.errors import handle_client_error
from gandi_mcp.tools._common import (
    assert_purchases_allowed,
    assert_readwrite,
    get_client,
)


def register_email_tools(mcp: FastMCP) -> None:
    """Register email tools on the server."""

    # ── Read ────────────────────────────────────────────────────────────

    @mcp.tool(tags={"gandi", "email"})
    async def email_list_mailboxes(
        ctx: Context,
        domain: str,
        per_page: int = 100,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """List mailboxes for a domain.

        Args:
            domain: Fully-qualified domain name.
            per_page: Page size.
            page: Page number.
        """
        try:
            return await get_client(ctx).email_list_mailboxes(domain, per_page=per_page, page=page)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "email"})
    async def email_get_mailbox(ctx: Context, domain: str, mailbox_id: str) -> dict[str, Any]:
        """Retrieve details for a mailbox.

        Args:
            domain: Fully-qualified domain name.
            mailbox_id: Mailbox UUID.
        """
        try:
            return await get_client(ctx).email_get_mailbox(domain, mailbox_id)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "email"})
    async def email_list_forwards(
        ctx: Context,
        domain: str,
        per_page: int = 100,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """List forwarding addresses for a domain.

        Args:
            domain: Fully-qualified domain name.
            per_page: Page size.
            page: Page number.
        """
        try:
            return await get_client(ctx).email_list_forwards(domain, per_page=per_page, page=page)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "email"})
    async def email_list_slots(ctx: Context, domain: str) -> list[dict[str, Any]]:
        """List mailbox slots (purchased capacity) for a domain.

        Args:
            domain: Fully-qualified domain name.
        """
        try:
            return await get_client(ctx).email_list_slots(domain)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "email"})
    async def email_get_slot(ctx: Context, domain: str, slot_id: str) -> dict[str, Any]:
        """Retrieve details for a slot.

        Args:
            domain: Fully-qualified domain name.
            slot_id: Slot ID.
        """
        try:
            return await get_client(ctx).email_get_slot(domain, slot_id)
        except Exception as e:
            handle_client_error(e)

    # ── Write (non-purchasing) ──────────────────────────────────────────

    @mcp.tool(
        tags={"gandi", "email", "write"},
        annotations={"readOnlyHint": False, "destructiveHint": False},
    )
    async def email_update_mailbox(
        ctx: Context,
        domain: str,
        mailbox_id: str,
        password: str | None = None,
        aliases: list[str] | None = None,
        responder: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a mailbox (password, aliases, vacation responder).

        Args:
            domain: Fully-qualified domain name.
            mailbox_id: Mailbox UUID.
            password: New password (omit to leave unchanged).
            aliases: Full list of aliases (replaces existing).
            responder: Autoresponder block (``enabled``, ``subject``, ``message``).
        """
        try:
            assert_readwrite(ctx, "update mailbox")
            data: dict[str, Any] = {}
            if password is not None:
                data["password"] = password
            if aliases is not None:
                data["aliases"] = aliases
            if responder is not None:
                data["responder"] = responder
            return await get_client(ctx).email_update_mailbox(domain, mailbox_id, data)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "email", "write"},
        annotations={"readOnlyHint": False, "destructiveHint": True},
    )
    async def email_delete_mailbox(ctx: Context, domain: str, mailbox_id: str) -> dict[str, Any]:
        """Delete a mailbox (frees the slot — mail is destroyed).

        Args:
            domain: Fully-qualified domain name.
            mailbox_id: Mailbox UUID.
        """
        try:
            assert_readwrite(ctx, "delete mailbox")
            return await get_client(ctx).email_delete_mailbox(domain, mailbox_id)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "email", "write"},
        annotations={"readOnlyHint": False, "destructiveHint": True},
    )
    async def email_purge_mailbox(ctx: Context, domain: str, mailbox_id: str) -> dict[str, Any]:
        """Purge the contents of a mailbox (destroys all mail, keeps the mailbox).

        Args:
            domain: Fully-qualified domain name.
            mailbox_id: Mailbox UUID.
        """
        try:
            assert_readwrite(ctx, "purge mailbox contents")
            return await get_client(ctx).email_purge_mailbox(domain, mailbox_id)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "email", "write"},
        annotations={"readOnlyHint": False, "destructiveHint": False},
    )
    async def email_create_forward(
        ctx: Context,
        domain: str,
        source: str,
        destinations: list[str],
    ) -> dict[str, Any]:
        """Create a forwarding address.

        Args:
            domain: Fully-qualified domain name.
            source: Local part on the domain (e.g. "info").
            destinations: Full email addresses to forward to.
        """
        try:
            assert_readwrite(ctx, "create email forward")
            return await get_client(ctx).email_create_forward(domain, source, destinations)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "email", "write"},
        annotations={"readOnlyHint": False, "destructiveHint": False},
    )
    async def email_update_forward(
        ctx: Context,
        domain: str,
        source: str,
        destinations: list[str],
    ) -> dict[str, Any]:
        """Replace destinations of an existing forward.

        Args:
            domain: Fully-qualified domain name.
            source: Local part on the domain.
            destinations: Full email addresses to forward to.
        """
        try:
            assert_readwrite(ctx, "update email forward")
            return await get_client(ctx).email_update_forward(domain, source, destinations)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "email", "write"},
        annotations={"readOnlyHint": False, "destructiveHint": True},
    )
    async def email_delete_forward(ctx: Context, domain: str, source: str) -> dict[str, Any]:
        """Delete a forwarding address.

        Args:
            domain: Fully-qualified domain name.
            source: Local part of the forward.
        """
        try:
            assert_readwrite(ctx, "delete email forward")
            return await get_client(ctx).email_delete_forward(domain, source)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "email", "write"},
        annotations={"readOnlyHint": False, "destructiveHint": False},
    )
    async def email_refund_slot(ctx: Context, domain: str, slot_id: str) -> dict[str, Any]:
        """Refund/delete an unused slot (within the refund window).

        Args:
            domain: Fully-qualified domain name.
            slot_id: Slot ID.
        """
        try:
            assert_readwrite(ctx, "refund mailbox slot")
            return await get_client(ctx).email_refund_slot(domain, slot_id)
        except Exception as e:
            handle_client_error(e)

    # ── Purchasing (DOUBLE-GATED) ───────────────────────────────────────

    @mcp.tool(
        tags={"gandi", "email", "write", "purchase"},
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )
    async def email_create_mailbox(
        ctx: Context,
        domain: str,
        login: str,
        password: str,
        mailbox_type: str = "standard",
        aliases: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a mailbox (may consume a slot — SPENDS MONEY).

        Requires GANDI_MODE=readwrite AND GANDI_ALLOW_PURCHASES=true.

        Args:
            domain: Fully-qualified domain name.
            login: Local part of the address.
            password: Initial password.
            mailbox_type: "standard" or "premium".
            aliases: Optional list of aliases.
        """
        try:
            assert_readwrite(ctx, "create mailbox")
            assert_purchases_allowed(ctx, "create mailbox")
            data: dict[str, Any] = {
                "login": login,
                "password": password,
                "mailbox_type": mailbox_type,
            }
            if aliases is not None:
                data["aliases"] = aliases
            return await get_client(ctx).email_create_mailbox(domain, data)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "email", "write", "purchase"},
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )
    async def email_create_slot(
        ctx: Context,
        domain: str,
        mailbox_type: str = "standard",
    ) -> dict[str, Any]:
        """Purchase a new mailbox slot (SPENDS MONEY).

        Requires GANDI_MODE=readwrite AND GANDI_ALLOW_PURCHASES=true.

        Args:
            domain: Fully-qualified domain name.
            mailbox_type: "standard" or "premium".
        """
        try:
            assert_readwrite(ctx, "create mailbox slot")
            assert_purchases_allowed(ctx, "create mailbox slot")
            return await get_client(ctx).email_create_slot(domain, {"mailbox_type": mailbox_type})
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "email", "write", "purchase"},
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )
    async def email_renew_mailbox(
        ctx: Context,
        domain: str,
        email: str,
        duration: int = 1,
    ) -> dict[str, Any]:
        """Renew a mailbox slot (SPENDS MONEY).

        Requires GANDI_MODE=readwrite AND GANDI_ALLOW_PURCHASES=true.

        Args:
            domain: Fully-qualified domain name.
            email: Full email address to renew.
            duration: Renewal duration in years.
        """
        try:
            assert_readwrite(ctx, "renew mailbox")
            assert_purchases_allowed(ctx, "renew mailbox")
            return await get_client(ctx).email_renew_mailbox(domain, email, {"duration": duration})
        except Exception as e:
            handle_client_error(e)
