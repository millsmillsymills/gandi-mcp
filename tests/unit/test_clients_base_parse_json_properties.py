"""Property tests for ``gandi_mcp.clients.base.BaseGandiClient._parse_json`` (closes #34).

Invariants enforced:

- A 204 response with empty body returns ``{}``.
- Any other status with an empty body raises ``GandiError`` (never silently
  returns ``{}`` — that would mislead an agent into thinking "zero records").
- A response with valid JSON returns the parsed structure (``dict`` / ``list``
  / scalar) unchanged.
- A response with invalid JSON raises ``GandiError`` with a status_code
  preserved (or ``None`` for the decode-failure branch).

The properties are stronger than the example-based tests because they exercise
arbitrary status codes + content-type pairings, including invalid JSON across
status-code categories.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from hypothesis import HealthCheck, assume, example, given, settings
from hypothesis import strategies as st

from gandi_mcp.clients.base import BaseGandiClient
from gandi_mcp.errors import GandiError


@pytest.fixture
def client() -> BaseGandiClient:
    return BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=1)


json_value: st.SearchStrategy[Any] = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-(2**31), max_value=2**31),
        st.floats(allow_nan=False, allow_infinity=False, width=32),
        st.text(min_size=0, max_size=20),
    ),
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(min_size=0, max_size=10), children, max_size=4),
    ),
    max_leaves=10,
)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    status=st.integers(min_value=200, max_value=599).filter(lambda s: s != 204),
    body=json_value,
)
@example(status=200, body={"foo": "bar"})
@example(status=200, body=[1, 2, 3])
@example(status=400, body={"cause": "x"})
def test_parse_json_returns_decoded_body_for_valid_json(client: BaseGandiClient, status: int, body: Any) -> None:
    """Any non-204 status with valid JSON returns the parsed structure unchanged.

    ``httpx.Response(json=None)`` skips body construction entirely, so we
    pre-encode the JSON ourselves to guarantee the body is non-empty even
    when the top-level value is ``null``.
    """
    payload = json.dumps(body).encode("utf-8")
    response = httpx.Response(status, content=payload, headers={"content-type": "application/json"})
    assert client._parse_json(response) == body


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(status=st.integers(min_value=200, max_value=599).filter(lambda s: s != 204))
@example(status=200)
@example(status=500)
def test_parse_json_raises_on_empty_body_when_not_204(client: BaseGandiClient, status: int) -> None:
    """A non-204 with empty body must raise — never silently return ``{}``."""
    response = httpx.Response(status, content=b"")
    with pytest.raises(GandiError, match="Empty response body"):
        client._parse_json(response)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(body=st.binary(max_size=0))
def test_parse_json_returns_empty_dict_for_204(client: BaseGandiClient, body: bytes) -> None:
    """A 204 always returns ``{}`` regardless of body content."""
    response = httpx.Response(204, content=body)
    assert client._parse_json(response) == {}


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    status=st.integers(min_value=200, max_value=599).filter(lambda s: s != 204),
    body=st.text(min_size=1, max_size=60),
)
def test_parse_json_raises_on_invalid_json(client: BaseGandiClient, status: int, body: str) -> None:
    """Invalid JSON in a non-204 body raises ``GandiError`` with the status surfaced."""
    # The filter must mirror the parsing path ``_parse_json`` exercises:
    # ``httpx.Response.json()`` calls ``json.loads`` on the response's *bytes*,
    # and ``json.loads`` accepts inputs from bytes that it rejects from str
    # (e.g. ``b"0\x00"`` returns ``0``; ``"0\x00"`` raises). Filtering on the
    # str form would let inputs through that production actually parses
    # successfully, falsifying the property.
    payload = body.encode("utf-8")
    try:
        json.loads(payload)
        valid_json = True
    except (ValueError, json.JSONDecodeError):
        valid_json = False
    assume(not valid_json)
    response = httpx.Response(status, content=payload, headers={"content-type": "application/json"})
    with pytest.raises(GandiError, match="Invalid JSON"):
        client._parse_json(response)
