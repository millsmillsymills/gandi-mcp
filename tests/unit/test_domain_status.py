"""Tests for the read-only ``gandi_domain_get_status`` tool.

Pins two things:

1. The slicing helper extracts EPP status flags into the agent-friendly shape
   (``transferLocked`` / ``updateLocked`` / ``deleteLocked`` booleans plus the
   raw ``status`` list).
2. The tool itself is visible in readonly mode (it's read-only) so an agent
   can check the lock state before any transfer-out flow.

Gandi's v5 REST API does not expose a write endpoint to TOGGLE lock state —
this tool is read-only by design. See README "Limitations" for the manual
unlock path.
"""

from __future__ import annotations

from gandi_mcp.config import GandiConfig, GandiMode
from gandi_mcp.server import create_server
from gandi_mcp.tools.domain import _status_view


class TestStatusView:
    def test_locked_domain_sets_transfer_locked_true(self) -> None:
        domain = {
            "fqdn": "example.com",
            "status": ["clientTransferProhibited"],
        }
        result = _status_view(domain, "example.com")
        assert result == {
            "fqdn": "example.com",
            "status": ["clientTransferProhibited"],
            "transferLocked": True,
            "updateLocked": False,
            "deleteLocked": False,
        }

    def test_unlocked_domain_sets_all_false(self) -> None:
        domain = {"fqdn": "example.com", "status": []}
        result = _status_view(domain, "example.com")
        assert result["transferLocked"] is False
        assert result["updateLocked"] is False
        assert result["deleteLocked"] is False

    def test_multiple_locks_all_surfaced(self) -> None:
        domain = {
            "fqdn": "example.com",
            "status": ["clientTransferProhibited", "clientUpdateProhibited", "clientDeleteProhibited"],
        }
        result = _status_view(domain, "example.com")
        assert result["transferLocked"] is True
        assert result["updateLocked"] is True
        assert result["deleteLocked"] is True

    def test_missing_status_treated_as_empty(self) -> None:
        # Defensive: Gandi has historically returned objects without a status key
        # for some edge-case domain types. Don't crash; report no locks.
        result = _status_view({"fqdn": "example.com"}, "example.com")
        assert result["status"] == []
        assert result["transferLocked"] is False

    def test_null_status_treated_as_empty(self) -> None:
        result = _status_view({"fqdn": "example.com", "status": None}, "example.com")
        assert result["status"] == []
        assert result["transferLocked"] is False

    def test_fqdn_falls_back_to_caller_arg(self) -> None:
        # If the response is malformed and lacks fqdn, surface the caller's input
        # rather than dropping the field.
        result = _status_view({"status": []}, "fallback.example")
        assert result["fqdn"] == "fallback.example"


def _config(**overrides: object) -> GandiConfig:
    defaults: dict[str, object] = {"_env_file": None, "gandi_token": "test-token"}
    defaults.update(overrides)
    return GandiConfig(**defaults)  # type: ignore[arg-type]


class TestVisibility:
    async def test_visible_in_readonly_mode(self) -> None:
        server = create_server(_config(gandi_mode=GandiMode.READONLY))
        names = {t.name for t in await server.list_tools()}
        assert "gandi_domain_get_status" in names

    async def test_visible_in_readwrite_mode(self) -> None:
        server = create_server(_config(gandi_mode=GandiMode.READWRITE))
        names = {t.name for t in await server.list_tools()}
        assert "gandi_domain_get_status" in names
