"""Tests for BaseGandiClient retry semantics."""

from __future__ import annotations

import httpx
import pytest
import respx

from gandi_mcp.clients.base import BaseGandiClient
from gandi_mcp.errors import GandiConnectionError


class TestRetrySemantics:
    """max_retries is a total-attempt count, not an extra-retry count.

    Previously `ge=0` was allowed, which passed stop_after_attempt(0) to tenacity
    — that stops before the first attempt, breaking every request. Config now
    enforces ge=1 so this footgun can't fire.
    """

    @pytest.mark.asyncio
    async def test_max_retries_one_attempts_exactly_once(self) -> None:
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=1)
        with respx.mock(base_url="https://api.gandi.net") as mock:
            route = mock.get("/v5/organization/user-info").mock(side_effect=httpx.ConnectError("boom"))
            with pytest.raises(GandiConnectionError):
                await client.get("/v5/organization/user-info")
            # With max_retries=1 there is no retry — one attempt, then surface the error.
            assert route.call_count == 1
        await client.close()
