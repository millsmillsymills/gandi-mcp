"""Domain management tools (/v5/domain)."""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from gandi_mcp.errors import handle_client_error
from gandi_mcp.tools._common import (
    assert_purchases_allowed,
    assert_readwrite,
    get_client,
)


def _status_view(domain: dict[str, Any], fqdn: str) -> dict[str, Any]:
    """Slice a ``GET /v5/domain/domains/{fqdn}`` response down to its EPP status.

    Gandi's v5 REST API exposes domain lock state only as part of the full
    domain object. This helper produces the smaller, branch-friendly shape
    used by ``gandi_domain_get_status``.
    """
    status = list(domain.get("status") or [])
    return {
        "fqdn": domain.get("fqdn", fqdn),
        "status": status,
        "transferLocked": "clientTransferProhibited" in status,
        "updateLocked": "clientUpdateProhibited" in status,
        "deleteLocked": "clientDeleteProhibited" in status,
    }


def register_domain_read_tools(mcp: FastMCP) -> None:
    """Register read-only domain tools on the server."""

    @mcp.tool(tags={"gandi", "domain"})
    async def gandi_domain_list_domains(
        ctx: Context,
        fqdn_filter: str | None = None,
        tld: str | None = None,
        per_page: int = 100,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """List domains owned by the authenticated user / org.

        Args:
            fqdn_filter: Substring filter on FQDN (e.g. "example").
            tld: Filter by TLD (e.g. "com").
            per_page: Page size (default 100, max 1000).
            page: Page number (1-based).


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            return await get_client(ctx).list_domains(fqdn=fqdn_filter, tld=tld, per_page=per_page, page=page)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "domain"})
    async def gandi_domain_get_domain(ctx: Context, fqdn: str) -> dict[str, Any]:
        """Retrieve full details for a domain (contacts, nameservers, status, dates).

        Args:
            fqdn: Fully-qualified domain name (e.g. "example.com").


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            return await get_client(ctx).get_domain(fqdn)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "domain"})
    async def gandi_domain_get_status(ctx: Context, fqdn: str) -> dict[str, Any]:
        """EPP status flags for a domain — focused view of the lock state.

        Returns ``{fqdn, status, transferLocked, updateLocked, deleteLocked}``
        where ``status`` is the raw EPP status array (e.g. ``["clientTransferProhibited"]``)
        and the booleans are convenience derivations agents can branch on
        before initiating a transfer-out or contact update.

        Gandi's v5 REST API exposes domain status as **read-only** — there is
        no PUT/PATCH endpoint to toggle ``clientTransferProhibited``. To unlock
        a domain for transfer-out, use the Gandi web UI (Domain settings →
        Transfer lock).

        Args:
            fqdn: Fully-qualified domain name (e.g. "example.com").


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            domain = await get_client(ctx).get_domain(fqdn)
            return _status_view(domain, fqdn)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "domain"})
    async def gandi_domain_check_availability(
        ctx: Context,
        name: str,
        processes: list[str] | None = None,
        extension: str | None = None,
        currency: str | None = None,
        country: str | None = None,
        max_duration: int | None = None,
        period: str | None = None,
    ) -> dict[str, Any]:
        """Check domain availability and pricing at the registry.

        Args:
            name: Domain name to check (with or without TLD — if no TLD, use
                ``extension`` to broaden the search).
            processes: Which operations to price ("create", "transfer",
                "restore"). Defaults to all.
            extension: TLD pattern to broaden the check across ("com", "net").
            currency: ISO currency code for pricing ("USD", "EUR").
            country: ISO country code — affects tax-inclusive pricing.
            max_duration: Maximum registration duration in years.
            period: Registration period ("create", "transfer", "renew").


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            return await get_client(ctx).check_availability(
                name,
                processes=processes,
                extension=extension,
                currency=currency,
                country=country,
                max_duration=max_duration,
                period=period,
            )
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "domain"})
    async def gandi_domain_get_claims(ctx: Context, fqdn: str) -> dict[str, Any]:
        """Trademark claims (TMCH) for a candidate registration.

        Args:
            fqdn: Candidate domain to check for trademark conflicts.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            return await get_client(ctx).get_domain_claims(fqdn)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "domain"})
    async def gandi_domain_get_contacts(ctx: Context, fqdn: str) -> dict[str, Any]:
        """Current contact block (admin/tech/bill/owner) for a domain.

        Args:
            fqdn: Fully-qualified domain name.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            return await get_client(ctx).get_domain_contacts(fqdn)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "domain"})
    async def gandi_domain_get_nameservers(ctx: Context, fqdn: str) -> list[str]:
        """Configured nameservers for a domain.

        Args:
            fqdn: Fully-qualified domain name.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            return await get_client(ctx).get_nameservers(fqdn)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "domain"})
    async def gandi_domain_list_glue_records(ctx: Context, fqdn: str) -> list[dict[str, Any]]:
        """List glue records (in-bailiwick host records) for a domain.

        Args:
            fqdn: Fully-qualified domain name.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            return await get_client(ctx).list_glue_records(fqdn)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "domain"})
    async def gandi_domain_get_glue_record(ctx: Context, fqdn: str, name: str) -> dict[str, Any]:
        """Get a specific glue record by hostname label.

        Args:
            fqdn: Parent domain.
            name: Short label of the glue host (e.g. "ns1").


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            return await get_client(ctx).get_glue_record(fqdn, name)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "domain"})
    async def gandi_domain_list_dnssec_keys(ctx: Context, fqdn: str) -> list[dict[str, Any]]:
        """List DS records registered at the registry for DNSSEC.

        Args:
            fqdn: Fully-qualified domain name.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            return await get_client(ctx).list_dnssec_keys(fqdn)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "domain"})
    async def gandi_domain_get_renew_info(ctx: Context, fqdn: str) -> dict[str, Any]:
        """Price and eligibility preview for a domain renewal (no charge).

        Args:
            fqdn: Fully-qualified domain name.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            return await get_client(ctx).get_renew_info(fqdn)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "domain"})
    async def gandi_domain_get_transferin_info(ctx: Context, fqdn: str) -> dict[str, Any]:
        """Check transfer-in availability and price preview (no charge).

        Args:
            fqdn: Fully-qualified domain name.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            return await get_client(ctx).get_transferin_info(fqdn)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(tags={"gandi", "domain"})
    async def gandi_domain_get_ownership_change_status(ctx: Context, fqdn: str) -> dict[str, Any]:
        """Status of a pending ownership change.

        Args:
            fqdn: Fully-qualified domain name.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            return await get_client(ctx).get_ownership_change_status(fqdn)
        except Exception as e:
            handle_client_error(e)


def register_domain_write_tools(mcp: FastMCP) -> None:
    """Register non-purchasing write domain tools on the server."""

    @mcp.tool(
        tags={"gandi", "domain", "write"},
        annotations={"readOnlyHint": False, "destructiveHint": False},
    )
    async def gandi_domain_set_autorenew(
        ctx: Context,
        fqdn: str,
        enabled: bool,
        duration: int | None = None,
    ) -> dict[str, Any]:
        """Enable or disable domain autorenewal.

        Args:
            fqdn: Fully-qualified domain name.
            enabled: True to enable autorenew, False to disable.
            duration: Renewal duration in years — TLD-specific; use
                `gandi_domain_get_renew_info` to preview valid durations. Required
                when enabling.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            assert_readwrite(ctx, "update autorenew")
            payload: dict[str, Any] = {"enabled": enabled}
            if duration is not None:
                payload["duration"] = duration
            return await get_client(ctx).set_autorenew(fqdn, payload)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "domain", "write"},
        annotations={"readOnlyHint": False, "destructiveHint": False},
    )
    async def gandi_domain_update_contacts(
        ctx: Context,
        fqdn: str,
        admin: dict[str, Any] | None = None,
        tech: dict[str, Any] | None = None,
        bill: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update admin/tech/bill contacts on a domain (owner changes use changeowner).

        Args:
            fqdn: Fully-qualified domain name.
            admin: Admin contact block — full contact object per Gandi schema.
            tech: Tech contact block.
            bill: Billing contact block.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            assert_readwrite(ctx, "update contacts")
            data: dict[str, Any] = {}
            if admin is not None:
                data["admin"] = admin
            if tech is not None:
                data["tech"] = tech
            if bill is not None:
                data["bill"] = bill
            return await get_client(ctx).update_domain_contacts(fqdn, data)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "domain", "write"},
        annotations={"readOnlyHint": False, "destructiveHint": False},
    )
    async def gandi_domain_set_nameservers(
        ctx: Context,
        fqdn: str,
        nameservers: list[str],
    ) -> dict[str, Any]:
        """Replace the nameservers configured at the registry.

        Args:
            fqdn: Fully-qualified domain name.
            nameservers: Full list of nameservers (replaces any existing set).


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            assert_readwrite(ctx, "update nameservers")
            return await get_client(ctx).set_nameservers(fqdn, nameservers)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "domain", "write"},
        annotations={"readOnlyHint": False, "destructiveHint": False},
    )
    async def gandi_domain_create_glue_record(
        ctx: Context,
        fqdn: str,
        name: str,
        ips: list[str],
    ) -> dict[str, Any]:
        """Create a glue record (in-bailiwick host).

        Args:
            fqdn: Parent domain (must be owned by this account).
            name: Short label for the glue host (e.g. "ns1").
            ips: List of IPs (IPv4 and/or IPv6) the glue host resolves to.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            assert_readwrite(ctx, "create glue record")
            return await get_client(ctx).create_glue_record(fqdn, name, ips)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "domain", "write"},
        annotations={"readOnlyHint": False, "destructiveHint": False},
    )
    async def gandi_domain_update_glue_record(
        ctx: Context,
        fqdn: str,
        name: str,
        ips: list[str],
    ) -> dict[str, Any]:
        """Replace the IPs of an existing glue record.

        Args:
            fqdn: Parent domain.
            name: Short label of the glue host.
            ips: New list of IPs (replaces any existing entries).


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            assert_readwrite(ctx, "update glue record")
            return await get_client(ctx).update_glue_record(fqdn, name, ips)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "domain", "write"},
        annotations={"readOnlyHint": False, "destructiveHint": True},
    )
    async def gandi_domain_delete_glue_record(ctx: Context, fqdn: str, name: str) -> dict[str, Any]:
        """Delete a glue record.

        Args:
            fqdn: Parent domain.
            name: Short label of the glue host.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            assert_readwrite(ctx, "delete glue record")
            return await get_client(ctx).delete_glue_record(fqdn, name)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "domain", "write"},
        annotations={"readOnlyHint": False, "destructiveHint": False},
    )
    async def gandi_domain_create_dnssec_key(
        ctx: Context,
        fqdn: str,
        algorithm: int,
        digest_type: int,
        digest: str,
        keytag: int,
    ) -> dict[str, Any]:
        """Register a DS record at the registry (activates DNSSEC).

        Args:
            fqdn: Fully-qualified domain name.
            algorithm: DNSSEC algorithm number (e.g. 13 for ECDSAP256SHA256).
            digest_type: IANA codepoint — commonly 1=SHA1, 2=SHA256, 4=SHA384.
            digest: Hex-encoded digest.
            keytag: Key tag (16-bit identifier).


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            assert_readwrite(ctx, "register DS record")
            return await get_client(ctx).create_dnssec_key(
                fqdn,
                {"algorithm": algorithm, "digest_type": digest_type, "digest": digest, "keytag": keytag},
            )
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "domain", "write"},
        annotations={"readOnlyHint": False, "destructiveHint": True},
    )
    async def gandi_domain_delete_dnssec_key(ctx: Context, fqdn: str, key_id: str) -> dict[str, Any]:
        """Remove a DS record from the registry.

        Args:
            fqdn: Fully-qualified domain name.
            key_id: ID of the DS record to delete.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            assert_readwrite(ctx, "delete DS record")
            return await get_client(ctx).delete_dnssec_key(fqdn, key_id)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "domain", "write"},
        annotations={"readOnlyHint": False, "destructiveHint": False},
    )
    async def gandi_domain_reset_authinfo(ctx: Context, fqdn: str) -> dict[str, Any]:
        """Regenerate the transfer authorization code.

        Args:
            fqdn: Fully-qualified domain name.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            assert_readwrite(ctx, "reset authinfo")
            return await get_client(ctx).reset_authinfo(fqdn)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "domain", "write"},
        annotations={"readOnlyHint": False, "destructiveHint": False},
    )
    async def gandi_domain_initiate_ownership_change(
        ctx: Context,
        fqdn: str,
        owner: dict[str, Any],
        notify_former_owner: bool = True,
    ) -> dict[str, Any]:
        """Initiate an ownership (registrant) change.

        Args:
            fqdn: Fully-qualified domain name.
            owner: New owner contact block per Gandi schema.
            notify_former_owner: Email the prior owner about the change.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            assert_readwrite(ctx, "initiate ownership change")
            return await get_client(ctx).initiate_ownership_change(
                fqdn,
                {"owner": owner, "notify_former_owner": notify_former_owner},
            )
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "domain", "write"},
        annotations={"readOnlyHint": False, "destructiveHint": False},
    )
    async def gandi_domain_resend_foa(ctx: Context, fqdn: str) -> dict[str, Any]:
        """Resend the Form-of-Authorization email for a pending ownership change.

        Args:
            fqdn: Fully-qualified domain name.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            assert_readwrite(ctx, "resend FOA")
            return await get_client(ctx).resend_foa(fqdn)
        except Exception as e:
            handle_client_error(e)


def register_domain_purchase_tools(mcp: FastMCP) -> None:
    """Register money-spending domain tools on the server.

    DOUBLE-GATED: requires GANDI_MODE=readwrite AND GANDI_ALLOW_PURCHASES=true."""

    @mcp.tool(
        tags={"gandi", "domain", "write", "purchase"},
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )
    async def gandi_domain_register(ctx: Context, data: dict[str, Any]) -> dict[str, Any]:
        """Register a new domain (SPENDS MONEY).

        Requires GANDI_MODE=readwrite AND GANDI_ALLOW_PURCHASES=true.

        Args:
            data: Full registration payload per the Gandi /v5/domain/domains
                schema — must include ``fqdn``, ``duration``, ``owner``, and
                typically ``admin``/``tech``/``bill`` contacts plus optional
                ``nameservers``, ``tld_period``, ``extra_parameters``.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            assert_readwrite(ctx, "register domain")
            assert_purchases_allowed(ctx, "register domain")
            return await get_client(ctx).register_domain(data)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "domain", "write", "purchase"},
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )
    async def gandi_domain_renew(
        ctx: Context,
        fqdn: str,
        duration: int = 1,
        currency: str | None = None,
    ) -> dict[str, Any]:
        """Renew a domain (SPENDS MONEY).

        Requires GANDI_MODE=readwrite AND GANDI_ALLOW_PURCHASES=true.

        Args:
            fqdn: Fully-qualified domain name.
            duration: Renewal duration in years — TLD-specific; use
                `gandi_domain_get_renew_info` to preview valid durations.
            currency: ISO currency code (defaults to org default).


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            assert_readwrite(ctx, "renew domain")
            assert_purchases_allowed(ctx, "renew domain")
            payload: dict[str, Any] = {"duration": duration}
            if currency is not None:
                payload["currency"] = currency
            return await get_client(ctx).renew_domain(fqdn, payload)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "domain", "write", "purchase"},
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )
    async def gandi_domain_transfer_in(ctx: Context, fqdn: str, data: dict[str, Any]) -> dict[str, Any]:
        """Initiate a domain transfer-in from another registrar (SPENDS MONEY).

        Requires GANDI_MODE=readwrite AND GANDI_ALLOW_PURCHASES=true.

        Args:
            fqdn: Fully-qualified domain name.
            data: Transfer payload (``authinfo``, ``duration``, ``owner``,
                optional contacts and nameservers).


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            assert_readwrite(ctx, "transfer domain")
            assert_purchases_allowed(ctx, "transfer domain")
            return await get_client(ctx).transfer_in(fqdn, data)
        except Exception as e:
            handle_client_error(e)

    @mcp.tool(
        tags={"gandi", "domain", "write"},
        annotations={"readOnlyHint": False, "destructiveHint": True},
    )
    async def gandi_domain_delete(ctx: Context, fqdn: str) -> dict[str, Any]:
        """Delete a domain (restricted — typically only works on test TLDs).

        Args:
            fqdn: Fully-qualified domain name.


        Returns:
            Gandi API response payload (see `https://api.gandi.net/docs` for the schema).
        """
        try:
            assert_readwrite(ctx, "delete domain")
            return await get_client(ctx).delete_domain(fqdn)
        except Exception as e:
            handle_client_error(e)


def register_domain_tools(mcp: FastMCP) -> None:
    """Register every domain tool (read + write + purchase).

    Visibility tiers are gated separately at the server level via
    ``mcp.disable(tags={...})``; this function unconditionally registers
    every tier. Tests that want only one tier should call the granular
    ``register_domain_<tier>_tools`` helpers directly.
    """
    register_domain_read_tools(mcp)
    register_domain_write_tools(mcp)
    register_domain_purchase_tools(mcp)
