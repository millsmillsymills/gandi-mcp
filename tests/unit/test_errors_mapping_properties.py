"""Property tests for ``BaseGandiClient._raise_for_status`` status mapping (closes #34).

Invariants enforced:

- Every documented status code (400 / 401 / 403 / 404 / 409 / 429 / 5xx)
  maps to its dedicated typed exception.
- Any other 4xx surfaces as the generic ``GandiError`` — never silently
  succeeds, never crashes.
- A 2xx response is a no-op regardless of body (``is_success`` short-circuits).
- The ``status_code`` attribute of the raised exception matches the response
  status — load-bearing for ``handle_client_error``'s branching.
"""

from __future__ import annotations

import httpx
import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from gandi_mcp.clients.base import BaseGandiClient
from gandi_mcp.errors import (
    GandiAuthError,
    GandiBadRequestError,
    GandiConflictError,
    GandiError,
    GandiNotFoundError,
    GandiRateLimitError,
    GandiServerError,
)


@pytest.fixture
def client() -> BaseGandiClient:
    return BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=1)


DOCUMENTED_MAPPINGS = {
    400: GandiBadRequestError,
    401: GandiAuthError,
    403: GandiAuthError,
    404: GandiNotFoundError,
    409: GandiConflictError,
    429: GandiRateLimitError,
}


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(status=st.sampled_from(sorted(DOCUMENTED_MAPPINGS)))
def test_documented_4xx_maps_to_typed_exception(client: BaseGandiClient, status: int) -> None:
    """Each documented status code raises its dedicated subclass."""
    expected_type = DOCUMENTED_MAPPINGS[status]
    response = httpx.Response(status, json={"cause": "x"})
    with pytest.raises(expected_type) as exc_info:
        client._raise_for_status(response)
    assert exc_info.value.status_code == status


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(status=st.integers(min_value=500, max_value=599))
@example(status=500)
@example(status=503)
@example(status=599)
def test_5xx_maps_to_server_error(client: BaseGandiClient, status: int) -> None:
    """Every 5xx surfaces as ``GandiServerError`` with the status preserved."""
    response = httpx.Response(status, json={"cause": "x"})
    with pytest.raises(GandiServerError) as exc_info:
        client._raise_for_status(response)
    assert exc_info.value.status_code == status


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(status=st.integers(min_value=400, max_value=499).filter(lambda s: s not in DOCUMENTED_MAPPINGS))
@example(status=402)  # Payment Required
@example(status=418)  # I'm a teapot
@example(status=451)  # Unavailable for legal reasons
def test_undocumented_4xx_falls_back_to_generic_error(client: BaseGandiClient, status: int) -> None:
    """An undocumented 4xx surfaces as the generic ``GandiError``, never crashes.

    The mapping is total — a future Gandi status code can't crash the client
    by hitting an ``elif`` ladder that has no terminal branch.
    """
    response = httpx.Response(status, json={"cause": "x"})
    with pytest.raises(GandiError) as exc_info:
        client._raise_for_status(response)
    # Must not be one of the typed subclasses for this branch.
    assert type(exc_info.value) is GandiError
    assert exc_info.value.status_code == status


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(status=st.integers(min_value=200, max_value=299))
def test_2xx_is_noop(client: BaseGandiClient, status: int) -> None:
    """Any 2xx response is a successful no-op — never raises."""
    response = httpx.Response(status, json={})
    client._raise_for_status(response)  # must not raise


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(status=st.integers(min_value=300, max_value=399))
def test_3xx_surfaces_as_generic_error(client: BaseGandiClient, status: int) -> None:
    """A 3xx (Gandi shouldn't return one, but if it did) surfaces as a generic error,
    not as a silent success."""
    # httpx treats 3xx as not success when followed redirects are disabled —
    # the client doesn't follow redirects, so we surface it.
    response = httpx.Response(status, json={"cause": "x"})
    with pytest.raises(GandiError):
        client._raise_for_status(response)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(retry_after=st.integers(min_value=0, max_value=3600))
@example(retry_after=0)
@example(retry_after=60)
def test_rate_limit_preserves_retry_after(client: BaseGandiClient, retry_after: int) -> None:
    """``GandiRateLimitError.retry_after`` mirrors the ``Retry-After`` header value."""
    response = httpx.Response(429, headers={"Retry-After": str(retry_after)}, json={"cause": "x"})
    with pytest.raises(GandiRateLimitError) as exc_info:
        client._raise_for_status(response)
    assert exc_info.value.retry_after == retry_after
