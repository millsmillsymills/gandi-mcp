"""Shared test fixtures for gandi-mcp."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP

from gandi_mcp.clients.gandi import GandiClient
from gandi_mcp.config import GandiConfig, GandiMode


@dataclass
class FakeLifespanContext:
    """Stand-in for ServerContext when exercising tool handlers outside a real lifespan."""

    client: Any = None
    config: GandiConfig | None = None
    clients: dict[str, Any] = field(default_factory=dict)  # compatibility shim


@pytest.fixture
def readonly_config() -> GandiConfig:
    """Readonly config with a token set."""
    return GandiConfig(
        _env_file=None,
        gandi_token="test-token",
        gandi_mode=GandiMode.READONLY,
    )


@pytest.fixture
def readwrite_config() -> GandiConfig:
    """Readwrite config (purchases still blocked)."""
    return GandiConfig(
        _env_file=None,
        gandi_token="test-token",
        gandi_mode=GandiMode.READWRITE,
    )


@pytest.fixture
def readwrite_with_purchases_config() -> GandiConfig:
    """Full-access config (readwrite + purchases enabled) — for gate tests only."""
    return GandiConfig(
        _env_file=None,
        gandi_token="test-token",
        gandi_mode=GandiMode.READWRITE,
        gandi_allow_purchases=True,
    )


@pytest.fixture
def gandi_client() -> GandiClient:
    """A GandiClient pointed at a synthetic URL for respx-based tests."""
    return GandiClient(
        base_url="https://api.gandi.net",
        token="test-token",
        timeout=5,
        max_retries=1,
    )


def build_fake_ctx(config: GandiConfig, client: Any = None) -> AsyncMock:
    """Build a fake Context with the given config and client."""
    ctx = AsyncMock()
    ctx.lifespan_context = FakeLifespanContext(client=client, config=config)
    return ctx


@pytest.fixture
def mcp_server() -> FastMCP:
    """A bare FastMCP server for tests that just need a namespace to register tools on."""
    return FastMCP(name="test-server")
