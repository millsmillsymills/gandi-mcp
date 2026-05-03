"""Shared fixtures for mocked-integration tests (Tier 2).

Each test in this tier:
1. Builds a real GandiClient pointed at a fake base URL
2. Intercepts HTTP via respx
3. Registers the relevant tool module on a fresh FastMCP server
4. Calls the tool through its handler with a fake Context
5. Asserts the request shape (method, URL, body) AND the response passes through
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
import respx

from gandi_mcp.clients.gandi import GandiClient
from gandi_mcp.config import GandiConfig, GandiMode
from gandi_mcp.server import ServerContext

BASE_URL = "https://api.gandi.net"


@pytest.fixture
def mocked_client() -> GandiClient:
    """A GandiClient against the fake base URL — paired with respx_mock."""
    return GandiClient(base_url=BASE_URL, token="test-token", timeout=5, max_retries=1)


@pytest.fixture
def respx_mock() -> Any:
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as mock:
        yield mock


def make_ctx(
    client: GandiClient,
    *,
    mode: GandiMode = GandiMode.READWRITE,
    allow_purchases: bool = True,
) -> AsyncMock:
    """Build a Context with the given client + a mode that exposes every tool.

    Mocked tests verify *behavior*, not gating — gating tests live in
    tests/unit/test_safety_gate_runtime.py.
    """
    config = GandiConfig(
        _env_file=None,
        gandi_token="test-token",
        gandi_mode=mode,
        gandi_allow_purchases=allow_purchases,
    )
    ctx = AsyncMock()
    ctx.lifespan_context = ServerContext(config=config, client=client)
    return ctx


@pytest.fixture
def ctx(mocked_client: GandiClient) -> AsyncMock:
    """Default context — readwrite + purchases enabled (so any tool can be exercised)."""
    return make_ctx(mocked_client)
