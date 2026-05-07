"""Tests for server creation and the tool-visibility gates."""

from typing import ClassVar

from gandi_mcp.config import GandiConfig, GandiMode
from gandi_mcp.server import create_server


def _config(**overrides):
    defaults = {
        "_env_file": None,
        "gandi_token": "test-token",
    }
    defaults.update(overrides)
    return GandiConfig(**defaults)


class TestCreateServer:
    def test_server_has_name(self):
        server = create_server(_config())
        assert server.name == "gandi-mcp"


class TestReadOnlyGate:
    async def test_readonly_hides_all_write_tools(self):
        server = create_server(_config(gandi_mode=GandiMode.READONLY))
        tool_names = {t.name for t in await server.list_tools()}

        # Purchase tools must be hidden
        assert "gandi_domain_register" not in tool_names
        assert "gandi_domain_renew" not in tool_names
        assert "gandi_email_create_mailbox" not in tool_names
        assert "gandi_cert_issue" not in tool_names

        # Regular write tools must also be hidden
        assert "gandi_livedns_create_record" not in tool_names
        assert "gandi_livedns_delete_record" not in tool_names
        assert "gandi_domain_set_nameservers" not in tool_names

        # Read tools must remain visible
        assert "gandi_org_get_user_info" in tool_names
        assert "gandi_domain_list_domains" in tool_names
        assert "gandi_livedns_list_records" in tool_names
        assert "gandi_billing_get_info" in tool_names


class TestReadWriteGate:
    async def test_readwrite_exposes_writes_but_hides_purchases(self):
        server = create_server(_config(gandi_mode=GandiMode.READWRITE))
        tool_names = {t.name for t in await server.list_tools()}

        # Non-purchase writes visible
        assert "gandi_livedns_create_record" in tool_names
        assert "gandi_domain_set_nameservers" in tool_names
        assert "gandi_email_update_mailbox" in tool_names

        # Purchase tools still hidden (requires GANDI_ALLOW_PURCHASES=true)
        assert "gandi_domain_register" not in tool_names
        assert "gandi_domain_renew" not in tool_names
        assert "gandi_email_create_mailbox" not in tool_names
        assert "gandi_cert_issue" not in tool_names


class TestFullAccess:
    async def test_purchases_visible_only_when_both_flags_set(self):
        server = create_server(_config(gandi_mode=GandiMode.READWRITE, gandi_allow_purchases=True))
        tool_names = {t.name for t in await server.list_tools()}

        assert "gandi_domain_register" in tool_names
        assert "gandi_domain_renew" in tool_names
        assert "gandi_email_create_mailbox" in tool_names
        assert "gandi_cert_issue" in tool_names

    async def test_purchases_flag_alone_does_not_unlock(self):
        # Opt-in flag but still readonly — purchases must stay hidden.
        server = create_server(_config(gandi_mode=GandiMode.READONLY, gandi_allow_purchases=True))
        tool_names = {t.name for t in await server.list_tools()}

        assert "gandi_domain_register" not in tool_names
        assert "gandi_cert_issue" not in tool_names


class TestDestructiveHints:
    """Every delete/revoke/purge-style tool must be flagged destructiveHint=True."""

    # Tools whose underlying API call removes state. MCP clients may branch
    # on destructiveHint to show a confirmation prompt before invoking.
    DESTRUCTIVE_TOOLS: ClassVar[set[str]] = {
        "gandi_domain_delete",
        "gandi_domain_delete_glue_record",
        "gandi_domain_delete_dnssec_key",
        "gandi_livedns_delete_record",
        "gandi_email_delete_mailbox",
        "gandi_email_delete_forward",
        "gandi_email_purge_mailbox",
        "gandi_email_refund_slot",
        "gandi_cert_revoke",
    }

    async def test_destructive_tools_have_destructive_hint(self):
        server = create_server(_config(gandi_mode=GandiMode.READWRITE, gandi_allow_purchases=True))
        tools = {t.name: t for t in await server.list_tools()}
        for name in self.DESTRUCTIVE_TOOLS:
            tool = tools.get(name)
            assert tool is not None, f"{name} not registered"
            hint = getattr(tool.annotations, "destructiveHint", None) if tool.annotations else None
            assert hint is True, f"{name} must have destructiveHint=True (got {hint!r})"


class TestToolCounts:
    async def test_readonly_fewer_tools_than_readwrite(self):
        ro = await create_server(_config(gandi_mode=GandiMode.READONLY)).list_tools()
        rw = await create_server(_config(gandi_mode=GandiMode.READWRITE)).list_tools()
        assert len(ro) < len(rw)

    async def test_readwrite_fewer_tools_than_full(self):
        rw = await create_server(_config(gandi_mode=GandiMode.READWRITE)).list_tools()
        full = await create_server(_config(gandi_mode=GandiMode.READWRITE, gandi_allow_purchases=True)).list_tools()
        assert len(rw) < len(full)
