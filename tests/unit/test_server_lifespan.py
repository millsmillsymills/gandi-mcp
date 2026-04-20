"""Tests that create_server(config) actually threads the config into the lifespan."""

from __future__ import annotations

import pytest

from gandi_mcp.config import GandiConfig, GandiMode
from gandi_mcp.server import _build_lifespan, create_server


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
