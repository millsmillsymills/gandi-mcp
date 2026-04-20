"""Gandi v5 API client — domain, LiveDNS, email, billing, organization, certificates."""

from __future__ import annotations

from typing import Any

from gandi_mcp.clients.base import BaseGandiClient


class GandiClient(BaseGandiClient):
    """Thin wrapper over the Gandi v5 REST API.

    Endpoints are grouped by product area. Every method is a typed pass-through
    — the Gandi API responses flow to tools as ``dict[str, Any]`` without a
    Pydantic validation layer, matching the convention of sister MCP servers
    (unraid-mcp, unifi-mcp).
    """

    # ═════════════════════════════════════════════════════════════════════
    # Organization (/v5/organization)
    # ═════════════════════════════════════════════════════════════════════

    async def get_user_info(self) -> dict[str, Any]:
        """Current authenticated user's profile."""
        result: dict[str, Any] = await self.get("/v5/organization/user-info")
        return result

    async def list_organizations(self, **params: Any) -> list[dict[str, Any]]:
        """List organizations the authenticated user can access."""
        result: list[dict[str, Any]] = await self.get(
            "/v5/organization/organizations",
            params={k: v for k, v in params.items() if v is not None},
        )
        return result

    async def get_organization(self, org_id: str) -> dict[str, Any]:
        """Get a specific organization."""
        result: dict[str, Any] = await self.get(f"/v5/organization/organizations/{org_id}")
        return result

    async def list_customers(self, org_id: str, **params: Any) -> list[dict[str, Any]]:
        """List customers under a reseller organization."""
        result: list[dict[str, Any]] = await self.get(
            f"/v5/organization/organizations/{org_id}/customers",
            params={k: v for k, v in params.items() if v is not None},
        )
        return result

    async def get_customer(self, org_id: str, customer_id: str) -> dict[str, Any]:
        """Get a specific customer of a reseller organization."""
        result: dict[str, Any] = await self.get(f"/v5/organization/organizations/{org_id}/customers/{customer_id}")
        return result

    # ═════════════════════════════════════════════════════════════════════
    # Billing (/v5/billing)
    # ═════════════════════════════════════════════════════════════════════

    async def get_billing_info(self) -> dict[str, Any]:
        """Billing info for the authenticated user (balance, prepaid, outstanding)."""
        result: dict[str, Any] = await self.get("/v5/billing/info")
        return result

    async def get_billing_info_for_org(self, sharing_id: str) -> dict[str, Any]:
        """Billing info for a specific organization (by sharing_id)."""
        result: dict[str, Any] = await self.get(f"/v5/billing/info/{sharing_id}")
        return result

    async def get_price_catalog(self, product_type: str, **params: Any) -> dict[str, Any]:
        """Pricing catalog for a product type (domain, certificate, mailbox, etc.).

        The caller is responsible for passing a valid ``product_type`` — see
        the Gandi API docs for the current list.
        """
        result: dict[str, Any] = await self.get(
            f"/v5/billing/price/{product_type}",
            params={k: v for k, v in params.items() if v is not None},
        )
        return result

    # ═════════════════════════════════════════════════════════════════════
    # Domain (/v5/domain)
    # ═════════════════════════════════════════════════════════════════════

    async def list_domains(self, **params: Any) -> list[dict[str, Any]]:
        """List domains owned by the authenticated user."""
        result: list[dict[str, Any]] = await self.get(
            "/v5/domain/domains",
            params={k: v for k, v in params.items() if v is not None},
        )
        return result

    async def get_domain(self, fqdn: str) -> dict[str, Any]:
        """Retrieve full details and configuration for a domain."""
        result: dict[str, Any] = await self.get(f"/v5/domain/domains/{fqdn}")
        return result

    async def check_availability(self, name: str, **params: Any) -> dict[str, Any]:
        """Check domain availability and pricing.

        Accepts the standard ``check`` query parameters (``processes``, ``grid``,
        ``currency``, ``country``, ``lang``, ``max_duration``, ``period``,
        ``extension``). ``name`` is passed as ``name`` in the query string.
        """
        params = {k: v for k, v in params.items() if v is not None}
        params["name"] = name
        result: dict[str, Any] = await self.get("/v5/domain/check", params=params)
        return result

    async def get_domain_claims(self, fqdn: str) -> dict[str, Any]:
        """TMCH trademark claims for a candidate registration."""
        result: dict[str, Any] = await self.get(f"/v5/domain/domains/{fqdn}/claims")
        return result

    async def register_domain(self, data: dict[str, Any]) -> dict[str, Any]:
        """Register a new domain (SPENDS MONEY).

        The caller must supply a full payload per the Gandi API schema:
        ``fqdn``, ``duration``, ``owner``, and any of ``admin``/``tech``/``bill``
        contacts, plus optional ``nameservers``, ``tld_period``, etc.
        """
        result: dict[str, Any] = await self.post("/v5/domain/domains", json=data)
        return result

    async def delete_domain(self, fqdn: str) -> dict[str, Any]:
        """Delete a domain (restricted feature — typically only for test TLDs)."""
        result: dict[str, Any] = await self.delete(f"/v5/domain/domains/{fqdn}")
        return result

    async def set_autorenew(self, fqdn: str, data: dict[str, Any]) -> dict[str, Any]:
        """Configure autorenewal (payload: ``enabled``, ``duration``, ``org_id``)."""
        result: dict[str, Any] = await self.patch(f"/v5/domain/domains/{fqdn}/autorenew", json=data)
        return result

    async def reset_authinfo(self, fqdn: str) -> dict[str, Any]:
        """Regenerate the domain's authorization (transfer) code."""
        result: dict[str, Any] = await self.put(f"/v5/domain/domains/{fqdn}/authinfo")
        return result

    async def initiate_ownership_change(self, fqdn: str, data: dict[str, Any]) -> dict[str, Any]:
        """Initiate an ownership change (``changeowner``)."""
        result: dict[str, Any] = await self.post(f"/v5/domain/changeowner/{fqdn}", json=data)
        return result

    async def get_ownership_change_status(self, fqdn: str) -> dict[str, Any]:
        """Check the status of a pending ownership change."""
        result: dict[str, Any] = await self.get(f"/v5/domain/changeowner/{fqdn}")
        return result

    async def resend_foa(self, fqdn: str) -> dict[str, Any]:
        """Resend the Form-of-Authorization email to the current owner."""
        result: dict[str, Any] = await self.post(f"/v5/domain/changeowner/{fqdn}/foa")
        return result

    # ── Contacts ────────────────────────────────────────────────────────

    async def get_domain_contacts(self, fqdn: str) -> dict[str, Any]:
        """Current contact block for a domain."""
        result: dict[str, Any] = await self.get(f"/v5/domain/domains/{fqdn}/contacts")
        return result

    async def update_domain_contacts(self, fqdn: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update the admin/tech/bill contacts for a domain."""
        result: dict[str, Any] = await self.patch(f"/v5/domain/domains/{fqdn}/contacts", json=data)
        return result

    # ── Nameservers / Glue records ──────────────────────────────────────

    async def get_nameservers(self, fqdn: str) -> list[str]:
        """Currently configured nameservers."""
        result: list[str] = await self.get(f"/v5/domain/domains/{fqdn}/nameservers")
        return result

    async def set_nameservers(self, fqdn: str, nameservers: list[str]) -> dict[str, Any]:
        """Replace the domain's nameservers."""
        result: dict[str, Any] = await self.put(
            f"/v5/domain/domains/{fqdn}/nameservers",
            json={"nameservers": nameservers},
        )
        return result

    async def list_glue_records(self, fqdn: str) -> list[dict[str, Any]]:
        """List glue records (in-bailiwick host records)."""
        result: list[dict[str, Any]] = await self.get(f"/v5/domain/domains/{fqdn}/hosts")
        return result

    async def get_glue_record(self, fqdn: str, name: str) -> dict[str, Any]:
        """Get a specific glue record by name."""
        result: dict[str, Any] = await self.get(f"/v5/domain/domains/{fqdn}/hosts/{name}")
        return result

    async def create_glue_record(self, fqdn: str, name: str, ips: list[str]) -> dict[str, Any]:
        """Create a glue record."""
        result: dict[str, Any] = await self.post(
            f"/v5/domain/domains/{fqdn}/hosts",
            json={"name": name, "ips": ips},
        )
        return result

    async def update_glue_record(self, fqdn: str, name: str, ips: list[str]) -> dict[str, Any]:
        """Update a glue record's IPs."""
        result: dict[str, Any] = await self.put(
            f"/v5/domain/domains/{fqdn}/hosts/{name}",
            json={"ips": ips},
        )
        return result

    async def delete_glue_record(self, fqdn: str, name: str) -> dict[str, Any]:
        """Delete a glue record."""
        result: dict[str, Any] = await self.delete(f"/v5/domain/domains/{fqdn}/hosts/{name}")
        return result

    # ── DNSSEC ──────────────────────────────────────────────────────────

    async def list_dnssec_keys(self, fqdn: str) -> list[dict[str, Any]]:
        """List DNSSEC DS keys registered at the registry."""
        result: list[dict[str, Any]] = await self.get(f"/v5/domain/domains/{fqdn}/dnskeys")
        return result

    async def create_dnssec_key(self, fqdn: str, data: dict[str, Any]) -> dict[str, Any]:
        """Register a DS record at the registry."""
        result: dict[str, Any] = await self.post(f"/v5/domain/domains/{fqdn}/dnskeys", json=data)
        return result

    async def delete_dnssec_key(self, fqdn: str, key_id: str) -> dict[str, Any]:
        """Remove a DS record."""
        result: dict[str, Any] = await self.delete(f"/v5/domain/domains/{fqdn}/dnskeys/{key_id}")
        return result

    # ── Renewal / Transfer (purchases) ──────────────────────────────────

    async def get_renew_info(self, fqdn: str) -> dict[str, Any]:
        """Price and eligibility preview for a domain renewal."""
        result: dict[str, Any] = await self.get(f"/v5/domain/domains/{fqdn}/renew")
        return result

    async def renew_domain(self, fqdn: str, data: dict[str, Any]) -> dict[str, Any]:
        """Renew a domain (SPENDS MONEY)."""
        result: dict[str, Any] = await self.post(f"/v5/domain/domains/{fqdn}/renew", json=data)
        return result

    async def get_transferin_info(self, fqdn: str) -> dict[str, Any]:
        """Check transfer-in availability / price preview."""
        result: dict[str, Any] = await self.get(f"/v5/domain/transferin/{fqdn}")
        return result

    async def transfer_in(self, fqdn: str, data: dict[str, Any]) -> dict[str, Any]:
        """Initiate a domain transfer-in (SPENDS MONEY)."""
        result: dict[str, Any] = await self.post(f"/v5/domain/transferin/{fqdn}", json=data)
        return result

    # ═════════════════════════════════════════════════════════════════════
    # LiveDNS (/v5/livedns)
    # ═════════════════════════════════════════════════════════════════════

    async def livedns_list_domains(self) -> list[dict[str, Any]]:
        """List domains handled by LiveDNS."""
        result: list[dict[str, Any]] = await self.get("/v5/livedns/domains")
        return result

    async def livedns_get_domain(self, fqdn: str) -> dict[str, Any]:
        """LiveDNS zone properties for a domain."""
        result: dict[str, Any] = await self.get(f"/v5/livedns/domains/{fqdn}")
        return result

    async def livedns_add_domain(self, fqdn: str) -> dict[str, Any]:
        """Add a domain to LiveDNS management."""
        result: dict[str, Any] = await self.post("/v5/livedns/domains", json={"fqdn": fqdn})
        return result

    async def livedns_patch_domain(self, fqdn: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update LiveDNS zone settings (``automatic_snapshots`` etc.)."""
        result: dict[str, Any] = await self.patch(f"/v5/livedns/domains/{fqdn}", json=data)
        return result

    async def livedns_list_nameservers(self, fqdn: str) -> list[str]:
        """LiveDNS nameservers for a domain."""
        result: list[str] = await self.get(f"/v5/livedns/domains/{fqdn}/nameservers")
        return result

    async def livedns_list_rrtypes(self) -> list[str]:
        """Accepted DNS record types."""
        result: list[str] = await self.get("/v5/livedns/dns/rrtypes")
        return result

    # ── Records ─────────────────────────────────────────────────────────

    async def livedns_list_records(
        self,
        fqdn: str,
        name: str | None = None,
        rrset_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """List records for a domain, optionally filtered by name and/or type."""
        path = f"/v5/livedns/domains/{fqdn}/records"
        if name and rrset_type:
            path = f"{path}/{name}/{rrset_type}"
        elif name:
            path = f"{path}/{name}"
        result: list[dict[str, Any]] = await self.get(path)
        return result

    async def livedns_create_record(
        self,
        fqdn: str,
        name: str,
        rrset_type: str,
        values: list[str],
        ttl: int | None = None,
    ) -> dict[str, Any]:
        """Create a single record."""
        payload: dict[str, Any] = {
            "rrset_name": name,
            "rrset_type": rrset_type,
            "rrset_values": values,
        }
        if ttl is not None:
            payload["rrset_ttl"] = ttl
        result: dict[str, Any] = await self.post(
            f"/v5/livedns/domains/{fqdn}/records",
            json=payload,
        )
        return result

    async def livedns_replace_record(
        self,
        fqdn: str,
        name: str,
        rrset_type: str,
        values: list[str],
        ttl: int | None = None,
    ) -> dict[str, Any]:
        """Replace a specific (name, type) record set."""
        payload: dict[str, Any] = {"rrset_values": values}
        if ttl is not None:
            payload["rrset_ttl"] = ttl
        result: dict[str, Any] = await self.put(
            f"/v5/livedns/domains/{fqdn}/records/{name}/{rrset_type}",
            json=payload,
        )
        return result

    async def livedns_replace_zone(self, fqdn: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        """Replace ALL records for a domain (destructive bulk write)."""
        result: dict[str, Any] = await self.put(
            f"/v5/livedns/domains/{fqdn}/records",
            json={"items": items},
        )
        return result

    async def livedns_delete_record(self, fqdn: str, name: str, rrset_type: str) -> dict[str, Any]:
        """Delete a specific (name, type) record set."""
        result: dict[str, Any] = await self.delete(f"/v5/livedns/domains/{fqdn}/records/{name}/{rrset_type}")
        return result

    async def livedns_delete_all_records(self, fqdn: str) -> dict[str, Any]:
        """Delete ALL records for a domain (irreversibly destructive)."""
        result: dict[str, Any] = await self.delete(f"/v5/livedns/domains/{fqdn}/records")
        return result

    # ── DNSSEC (LiveDNS) ────────────────────────────────────────────────

    async def livedns_list_keys(self, fqdn: str) -> list[dict[str, Any]]:
        """List LiveDNS DNSSEC keys for a domain."""
        result: list[dict[str, Any]] = await self.get(f"/v5/livedns/domains/{fqdn}/keys")
        return result

    async def livedns_create_key(self, fqdn: str, flags: int = 257) -> dict[str, Any]:
        """Create a DNSSEC key (defaults to KSK, flags=257)."""
        result: dict[str, Any] = await self.post(
            f"/v5/livedns/domains/{fqdn}/keys",
            json={"flags": flags},
        )
        return result

    async def livedns_delete_key(self, fqdn: str, key_id: str) -> dict[str, Any]:
        """Delete a LiveDNS DNSSEC key."""
        result: dict[str, Any] = await self.delete(f"/v5/livedns/domains/{fqdn}/keys/{key_id}")
        return result

    # ═════════════════════════════════════════════════════════════════════
    # Email (/v5/email)
    # ═════════════════════════════════════════════════════════════════════

    async def email_list_mailboxes(self, domain: str, **params: Any) -> list[dict[str, Any]]:
        """List mailboxes for a domain."""
        result: list[dict[str, Any]] = await self.get(
            f"/v5/email/mailboxes/{domain}",
            params={k: v for k, v in params.items() if v is not None},
        )
        return result

    async def email_get_mailbox(self, domain: str, mailbox_id: str) -> dict[str, Any]:
        """Get a specific mailbox."""
        result: dict[str, Any] = await self.get(f"/v5/email/mailboxes/{domain}/{mailbox_id}")
        return result

    async def email_create_mailbox(self, domain: str, data: dict[str, Any]) -> dict[str, Any]:
        """Create a mailbox (may consume a slot — typically SPENDS MONEY)."""
        result: dict[str, Any] = await self.post(f"/v5/email/mailboxes/{domain}", json=data)
        return result

    async def email_update_mailbox(self, domain: str, mailbox_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update a mailbox (password, aliases, quota, responder, etc.)."""
        result: dict[str, Any] = await self.patch(
            f"/v5/email/mailboxes/{domain}/{mailbox_id}",
            json=data,
        )
        return result

    async def email_delete_mailbox(self, domain: str, mailbox_id: str) -> dict[str, Any]:
        """Delete a mailbox."""
        result: dict[str, Any] = await self.delete(f"/v5/email/mailboxes/{domain}/{mailbox_id}")
        return result

    async def email_purge_mailbox(self, domain: str, mailbox_id: str) -> dict[str, Any]:
        """Purge the contents of a mailbox (destructive)."""
        result: dict[str, Any] = await self.delete(f"/v5/email/mailboxes/{domain}/{mailbox_id}/contents")
        return result

    # ── Forwards ────────────────────────────────────────────────────────

    async def email_list_forwards(self, domain: str, **params: Any) -> list[dict[str, Any]]:
        """List forwarding addresses for a domain."""
        result: list[dict[str, Any]] = await self.get(
            f"/v5/email/forwards/{domain}",
            params={k: v for k, v in params.items() if v is not None},
        )
        return result

    async def email_create_forward(self, domain: str, source: str, destinations: list[str]) -> dict[str, Any]:
        """Create a forwarding address."""
        result: dict[str, Any] = await self.post(
            f"/v5/email/forwards/{domain}",
            json={"source": source, "destinations": destinations},
        )
        return result

    async def email_update_forward(self, domain: str, source: str, destinations: list[str]) -> dict[str, Any]:
        """Replace destinations of an existing forward."""
        result: dict[str, Any] = await self.put(
            f"/v5/email/forwards/{domain}/{source}",
            json={"destinations": destinations},
        )
        return result

    async def email_delete_forward(self, domain: str, source: str) -> dict[str, Any]:
        """Delete a forward."""
        result: dict[str, Any] = await self.delete(f"/v5/email/forwards/{domain}/{source}")
        return result

    # ── Slots ───────────────────────────────────────────────────────────

    async def email_list_slots(self, domain: str) -> list[dict[str, Any]]:
        """List mailbox slots for a domain."""
        result: list[dict[str, Any]] = await self.get(f"/v5/email/slots/{domain}")
        return result

    async def email_get_slot(self, domain: str, slot_id: str) -> dict[str, Any]:
        """Get a specific slot."""
        result: dict[str, Any] = await self.get(f"/v5/email/slots/{domain}/{slot_id}")
        return result

    async def email_create_slot(self, domain: str, data: dict[str, Any]) -> dict[str, Any]:
        """Create a mailbox slot (SPENDS MONEY)."""
        result: dict[str, Any] = await self.post(f"/v5/email/slots/{domain}", json=data)
        return result

    async def email_refund_slot(self, domain: str, slot_id: str) -> dict[str, Any]:
        """Refund/delete a slot (within the refund window)."""
        result: dict[str, Any] = await self.delete(f"/v5/email/slots/{domain}/{slot_id}")
        return result

    async def email_renew_mailbox(self, domain: str, email: str, data: dict[str, Any]) -> dict[str, Any]:
        """Renew a single mailbox slot (SPENDS MONEY)."""
        result: dict[str, Any] = await self.post(
            f"/v5/email/mailboxes/{domain}/{email}/renew",
            json=data,
        )
        return result

    # ═════════════════════════════════════════════════════════════════════
    # Certificates (/v5/certificate)
    # ═════════════════════════════════════════════════════════════════════

    async def cert_list(self, **params: Any) -> list[dict[str, Any]]:
        """List issued SSL certificates."""
        result: list[dict[str, Any]] = await self.get(
            "/v5/certificate/issued-certs",
            params={k: v for k, v in params.items() if v is not None},
        )
        return result

    async def cert_get(self, cert_id: str) -> dict[str, Any]:
        """Get a specific certificate."""
        result: dict[str, Any] = await self.get(f"/v5/certificate/issued-certs/{cert_id}")
        return result

    async def cert_issue(self, data: dict[str, Any]) -> dict[str, Any]:
        """Issue a new certificate (SPENDS MONEY)."""
        result: dict[str, Any] = await self.post("/v5/certificate/issued-certs", json=data)
        return result

    async def cert_revoke(self, cert_id: str) -> dict[str, Any]:
        """Revoke a certificate."""
        result: dict[str, Any] = await self.delete(f"/v5/certificate/issued-certs/{cert_id}")
        return result

    async def cert_renew(self, cert_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Renew a certificate (SPENDS MONEY)."""
        result: dict[str, Any] = await self.post(
            f"/v5/certificate/issued-certs/{cert_id}/renew",
            json=data,
        )
        return result
