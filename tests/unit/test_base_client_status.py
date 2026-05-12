"""Tight assertions for ``BaseGandiClient._raise_for_status`` (closes #83).

The existing ``test_client_status_mapping.py`` pins the
status -> exception-type dispatch. The existing
``test_client_error_bodies.py`` pins ``details`` preservation but only for
400 and 403. These tests pin the remaining survivors from the #83 baseline:

- ``details`` survives the dispatch for **every** typed branch
  (404, 409, 429, 5xx, and the catch-all non-success path), not just 400/403.
- The 5xx range is strictly ``[500, 600)`` -- a status of 600 must NOT
  promote to ``GandiServerError`` (rules out ``status <= 600`` and
  ``status < 601`` boundary mutations).
"""

from __future__ import annotations

import httpx
import pytest
import respx

from gandi_mcp.clients.base import BaseGandiClient
from gandi_mcp.errors import (
    GandiConflictError,
    GandiError,
    GandiNotFoundError,
    GandiRateLimitError,
    GandiServerError,
)

# Status codes whose `_raise_for_status` branches each have their own
# ``details=details`` kwarg -- the parametrised test below pins that the
# parsed error body survives the dispatch on each branch.
DETAILS_PRESERVING_STATUSES: list[tuple[int, type[GandiError]]] = [
    (404, GandiNotFoundError),
    (409, GandiConflictError),
    (429, GandiRateLimitError),
    (500, GandiServerError),
    (503, GandiServerError),
    # Catch-all non-success path (not any typed subclass).
    (418, GandiError),
]


@pytest.fixture
def client() -> BaseGandiClient:
    return BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=1)


class TestDetailsPreservedOnEveryBranch:
    """``details=`` is forwarded to the typed exception for every dispatch branch.

    Pins the surviving baseline mutants that replace ``details=details`` with
    ``details=None`` (or drop the kwarg entirely) inside ``_raise_for_status``
    for 404/409/429/5xx/catch-all.
    """

    @pytest.mark.parametrize(("status", "exc_type"), DETAILS_PRESERVING_STATUSES)
    @pytest.mark.asyncio
    async def test_json_error_body_attached_as_details(
        self, client: BaseGandiClient, status: int, exc_type: type[GandiError]
    ) -> None:
        body = {"code": status, "cause": "Computer says no", "message": "explanation", "object": "domain"}
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.get("/v5/organization/user-info").mock(
                return_value=httpx.Response(status, json=body, headers={"content-type": "application/json"}),
            )
            with pytest.raises(exc_type) as exc_info:
                await client.get("/v5/organization/user-info")
            # All four allowlisted keys must survive the dispatch.
            assert exc_info.value.details == body
        await client.close()


class TestServerErrorRangeBoundary:
    """5xx is exactly ``[500, 600)`` -- 600 falls through to the catch-all."""

    @pytest.mark.asyncio
    async def test_status_600_is_generic_not_server_error(self, client: BaseGandiClient) -> None:
        """Kills ``status <= 600`` and ``status < 601`` boundary mutations."""
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.get("/v5/organization/user-info").mock(return_value=httpx.Response(600, text="bogus"))
            with pytest.raises(GandiError) as exc_info:
                await client.get("/v5/organization/user-info")
            assert not isinstance(exc_info.value, GandiServerError)
            assert exc_info.value.status_code == 600
        await client.close()

    @pytest.mark.asyncio
    async def test_status_599_is_server_error(self, client: BaseGandiClient) -> None:
        """Upper-bound sanity: 599 still maps to ``GandiServerError``."""
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.get("/v5/organization/user-info").mock(return_value=httpx.Response(599, text="edge"))
            with pytest.raises(GandiServerError) as exc_info:
                await client.get("/v5/organization/user-info")
            assert exc_info.value.status_code == 599
        await client.close()
