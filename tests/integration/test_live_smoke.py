"""Live smoke tests against api.gandi.net.

Skipped cleanly when ``GANDI_TOKEN`` is not set so unit-only CI runs do
not flake on missing credentials. Set the env var locally to exercise:

    GANDI_TOKEN=$(pass show gandi/pat) uv run pytest tests/integration/ -v

The tests are read-only by design (PROTO-006 default-safe posture) — none
of them spend money or mutate registrar state.
"""

from __future__ import annotations

import os

import pytest

from gandi_mcp.clients.gandi import GandiClient
from gandi_mcp.config import GandiConfig

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("GANDI_TOKEN"),
        reason="GANDI_TOKEN is required for live integration tests",
    ),
]


@pytest.fixture
async def client() -> GandiClient:
    config = GandiConfig()
    assert config.gandi_token is not None
    c = GandiClient(
        base_url=config.gandi_api_base_url,
        token=config.gandi_token.get_secret_value(),
        sharing_id=config.gandi_sharing_id,
        timeout=config.gandi_request_timeout,
        max_retries=1,
    )
    yield c
    await c.close()


@pytest.mark.asyncio
async def test_user_info_round_trip(client: GandiClient) -> None:
    """The PAT owner's profile must be retrievable and contain a username."""
    info = await client.get_user_info()
    assert isinstance(info, dict)
    assert "username" in info
