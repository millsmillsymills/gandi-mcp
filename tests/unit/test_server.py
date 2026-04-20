"""Tests for server creation and the tool-visibility gates."""

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
        assert "domain_register" not in tool_names
        assert "domain_renew" not in tool_names
        assert "email_create_mailbox" not in tool_names
        assert "cert_issue" not in tool_names

        # Regular write tools must also be hidden
        assert "livedns_create_record" not in tool_names
        assert "livedns_delete_record" not in tool_names
        assert "domain_set_nameservers" not in tool_names

        # Read tools must remain visible
        assert "org_get_user_info" in tool_names
        assert "domain_list_domains" in tool_names
        assert "livedns_list_records" in tool_names
        assert "billing_get_info" in tool_names


class TestReadWriteGate:
    async def test_readwrite_exposes_writes_but_hides_purchases(self):
        server = create_server(_config(gandi_mode=GandiMode.READWRITE))
        tool_names = {t.name for t in await server.list_tools()}

        # Non-purchase writes visible
        assert "livedns_create_record" in tool_names
        assert "domain_set_nameservers" in tool_names
        assert "email_update_mailbox" in tool_names

        # Purchase tools still hidden (requires GANDI_ALLOW_PURCHASES=true)
        assert "domain_register" not in tool_names
        assert "domain_renew" not in tool_names
        assert "email_create_mailbox" not in tool_names
        assert "cert_issue" not in tool_names


class TestFullAccess:
    async def test_purchases_visible_only_when_both_flags_set(self):
        server = create_server(_config(gandi_mode=GandiMode.READWRITE, gandi_allow_purchases=True))
        tool_names = {t.name for t in await server.list_tools()}

        assert "domain_register" in tool_names
        assert "domain_renew" in tool_names
        assert "email_create_mailbox" in tool_names
        assert "cert_issue" in tool_names

    async def test_purchases_flag_alone_does_not_unlock(self):
        # Opt-in flag but still readonly — purchases must stay hidden.
        server = create_server(_config(gandi_mode=GandiMode.READONLY, gandi_allow_purchases=True))
        tool_names = {t.name for t in await server.list_tools()}

        assert "domain_register" not in tool_names
        assert "cert_issue" not in tool_names


class TestToolCounts:
    async def test_readonly_fewer_tools_than_readwrite(self):
        ro = await create_server(_config(gandi_mode=GandiMode.READONLY)).list_tools()
        rw = await create_server(_config(gandi_mode=GandiMode.READWRITE)).list_tools()
        assert len(ro) < len(rw)

    async def test_readwrite_fewer_tools_than_full(self):
        rw = await create_server(_config(gandi_mode=GandiMode.READWRITE)).list_tools()
        full = await create_server(_config(gandi_mode=GandiMode.READWRITE, gandi_allow_purchases=True)).list_tools()
        assert len(rw) < len(full)
