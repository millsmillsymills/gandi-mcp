"""Property tests for ``BaseGandiClient._request`` retry policy (closes #34).

Invariant: a timeout during a non-idempotent method (POST, PUT, PATCH, DELETE)
is NEVER retried. Retrying could double-execute a purchase, a DNS record
mutation, a mailbox delete, etc. Idempotent methods (GET, HEAD) MAY retry on
timeout.

The property is checked against the full set of HTTP methods. The client's
retry decorator is wired with method-conditional ``retry_on`` — this test
pins that wiring statically by injecting a fault and counting calls.

``asyncio.sleep`` is patched to a no-op so tenacity's exponential backoff
between retries doesn't blow the property-suite's <5 s runtime budget.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from gandi_mcp.clients.base import BaseGandiClient
from gandi_mcp.errors import GandiConnectionError, GandiTimeoutError

IDEMPOTENT = frozenset({"GET", "HEAD"})
NON_IDEMPOTENT = frozenset({"POST", "PUT", "PATCH", "DELETE"})
ALL_METHODS = IDEMPOTENT | NON_IDEMPOTENT


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace ``asyncio.sleep`` with a no-op so tenacity's backoff doesn't run.

    The retry-policy invariants only care about call counts and the surfaced
    exception type. Real backoff time would push this file past the
    property-suite runtime budget without changing the assertion outcomes.
    """

    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _instant)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=20, deadline=None)
@given(method=st.sampled_from(sorted(NON_IDEMPOTENT)))
@pytest.mark.asyncio
async def test_non_idempotent_timeout_is_never_retried(method: str) -> None:
    """A ``TimeoutException`` on POST/PUT/PATCH/DELETE must surface immediately.

    The respx route is configured to always timeout; if tenacity were to retry
    on a non-idempotent timeout, the route would be hit more than once. We
    assert exactly one call regardless of ``max_retries``.
    """
    client = BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=5)
    with respx.mock(base_url="https://api.gandi.net") as mock:
        route = mock.request(method, "/v5/dummy").mock(side_effect=httpx.TimeoutException("timeout"))
        with pytest.raises(GandiTimeoutError):
            await client._request(method, "/v5/dummy")
        assert route.call_count == 1, f"{method} retried on timeout: {route.call_count} calls"
    await client.close()


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=10, deadline=None)
@given(method=st.sampled_from(sorted(IDEMPOTENT)))
@pytest.mark.asyncio
async def test_idempotent_timeout_is_retried(method: str) -> None:
    """A ``TimeoutException`` on GET/HEAD must be retried up to ``max_retries``.

    Stronger: respx records ``max_retries`` calls before the final exception
    surfaces. Without retry on idempotent timeout, the call count would be 1.
    """
    client = BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=3)
    with respx.mock(base_url="https://api.gandi.net") as mock:
        route = mock.request(method, "/v5/dummy").mock(side_effect=httpx.TimeoutException("timeout"))
        with pytest.raises(GandiTimeoutError):
            await client._request(method, "/v5/dummy")
        assert route.call_count == 3, f"{method} did not retry on timeout: {route.call_count} calls"
    await client.close()


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=20, deadline=None)
@given(method=st.sampled_from(sorted(ALL_METHODS)))
@pytest.mark.asyncio
async def test_connect_error_is_retried_for_every_method(method: str) -> None:
    """A ``ConnectError`` is always retried — the request never reached the server,
    so double-execution is not possible. Holds for every method.
    """
    client = BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=3)
    with respx.mock(base_url="https://api.gandi.net") as mock:
        route = mock.request(method, "/v5/dummy").mock(side_effect=httpx.ConnectError("dns"))
        with pytest.raises(GandiConnectionError):
            await client._request(method, "/v5/dummy")
        assert route.call_count == 3, f"{method} did not retry on ConnectError: {route.call_count} calls"
    await client.close()
