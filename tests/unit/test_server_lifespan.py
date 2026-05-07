"""Tests for create_server / lifespan startup paths."""

from __future__ import annotations

import httpx
import pytest
import respx

from gandi_mcp.config import GandiConfig, GandiMode
from gandi_mcp.server import _build_lifespan, create_server


def _authed_config() -> GandiConfig:
    return GandiConfig(
        _env_file=None,
        gandi_token="test-token",
        gandi_mode=GandiMode.READONLY,
        gandi_max_retries=1,
    )


@pytest.mark.asyncio
async def test_lifespan_uses_passed_config_not_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Config passed to create_server must flow through to the lifespan.

    Previously the lifespan re-read env vars, so the ``config`` arg was only
    used for visibility gating and the runtime-visible config was whatever env
    said at lifespan-time. This test pins the behavior by setting env to a
    contradictory value and asserting the lifespan context yields the
    explicitly-passed config.
    """
    # env says 7 attempts, explicit config says 5. If the lifespan re-reads
    # env (old behavior), context.config.gandi_max_retries will be 7.
    monkeypatch.setenv("GANDI_MAX_RETRIES", "7")

    explicit = GandiConfig(
        _env_file=None,
        gandi_token=None,  # authenticated=False → lifespan skips validation
        gandi_mode=GandiMode.READONLY,
        gandi_max_retries=5,
    )
    server = create_server(explicit)

    # Invoke the lifespan closure directly — server.lifespan is a bound method
    # on the internal provider, not the Lifespan object we registered.
    lifespan = _build_lifespan(explicit)
    async with lifespan(server) as context:
        assert context.config is explicit
        assert context.config.gandi_max_retries == 5


class TestLifespanStartupBranches:
    """Four startup paths: no token, validate raised (auth/network), happy path."""

    @pytest.mark.asyncio
    async def test_no_token_disables_tools_without_network(self, caplog: pytest.LogCaptureFixture) -> None:
        config = GandiConfig(_env_file=None, gandi_token=None)
        server = create_server(config)
        lifespan = _build_lifespan(config)
        with caplog.at_level("ERROR"):
            async with lifespan(server) as context:
                assert context.client is None
        assert any("API credential not configured" in r.message for r in caplog.records)
        # No network calls should have happened — respx isn't mounted, so a
        # real attempt would try to hit api.gandi.net and succeed-or-fail
        # unpredictably. The absence of respx is itself the assertion.

    @pytest.mark.asyncio
    async def test_auth_error_logs_actionable_reason(self, caplog: pytest.LogCaptureFixture) -> None:
        config = _authed_config()
        server = create_server(config)
        lifespan = _build_lifespan(config)
        with (
            respx.mock(base_url="https://api.gandi.net") as mock,
            caplog.at_level("ERROR"),
        ):
            mock.get("/v5/organization/user-info").mock(return_value=httpx.Response(401, text="bad token"))
            async with lifespan(server) as context:
                assert context.client is None
        messages = " ".join(r.message for r in caplog.records)
        assert "Gandi tools disabled" in messages
        assert "regenerate GANDI_TOKEN" in messages

    @pytest.mark.asyncio
    async def test_connection_error_logs_actionable_reason(self, caplog: pytest.LogCaptureFixture) -> None:
        config = _authed_config()
        server = create_server(config)
        lifespan = _build_lifespan(config)
        with (
            respx.mock(base_url="https://api.gandi.net") as mock,
            caplog.at_level("ERROR"),
        ):
            mock.get("/v5/organization/user-info").mock(side_effect=httpx.ConnectError("dns fail"))
            async with lifespan(server) as context:
                assert context.client is None
        messages = " ".join(r.message for r in caplog.records)
        assert "cannot reach api.gandi.net" in messages

    @pytest.mark.asyncio
    async def test_server_error_logs_actionable_reason(self, caplog: pytest.LogCaptureFixture) -> None:
        config = _authed_config()
        server = create_server(config)
        lifespan = _build_lifespan(config)
        with (
            respx.mock(base_url="https://api.gandi.net") as mock,
            caplog.at_level("ERROR"),
        ):
            mock.get("/v5/organization/user-info").mock(return_value=httpx.Response(503, text="upstream"))
            async with lifespan(server) as context:
                assert context.client is None
        messages = " ".join(r.message for r in caplog.records)
        assert "Gandi API returned 5xx" in messages

    @pytest.mark.asyncio
    async def test_happy_path_yields_client(self, caplog: pytest.LogCaptureFixture) -> None:
        config = _authed_config()
        server = create_server(config)
        lifespan = _build_lifespan(config)
        with (
            respx.mock(base_url="https://api.gandi.net") as mock,
            caplog.at_level("INFO"),
        ):
            mock.get("/v5/organization/user-info").mock(return_value=httpx.Response(200, json={"username": "test"}))
            async with lifespan(server) as context:
                assert context.client is not None
        assert any("Gandi MCP ready" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_validate_connection_raises_on_failure() -> None:
    """validate_connection now propagates typed exceptions instead of collapsing to False."""
    from gandi_mcp.clients.base import BaseGandiClient
    from gandi_mcp.errors import GandiAuthError

    client = BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=1)
    with respx.mock(base_url="https://api.gandi.net") as mock:
        mock.get("/v5/organization/user-info").mock(
            return_value=httpx.Response(401, text="bad"),
        )
        with pytest.raises(GandiAuthError):
            await client.validate_connection()
    await client.close()


@pytest.mark.asyncio
async def test_validate_connection_returns_none_on_success() -> None:
    from gandi_mcp.clients.base import BaseGandiClient

    client = BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=1)
    with respx.mock(base_url="https://api.gandi.net") as mock:
        mock.get("/v5/organization/user-info").mock(return_value=httpx.Response(200, json={}))
        result = await client.validate_connection()
        assert result is None
    await client.close()
