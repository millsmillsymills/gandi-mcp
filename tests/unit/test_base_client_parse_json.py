"""Targeted tests for ``BaseGandiClient._parse_json`` mutmut survivors (#83).

These pin behaviours not asserted by the example-based or property tests in
``test_client_parse_json.py`` / ``test_clients_base_parse_json_properties.py``:

- The empty-body ``GandiError`` carries ``status_code == response.status_code``
  (not ``None``) so the agent can distinguish a stripped-200 from a stripped-500.
- The invalid-JSON ``GandiError`` message contains the raw body, truncated to
  exactly 200 characters (not 201, not ``None``).
- The invalid-JSON ``GandiError`` carries ``status_code is None`` because the
  decode failure means we cannot trust the HTTP framing either.
"""

from __future__ import annotations

import httpx
import pytest

from gandi_mcp.clients.base import BaseGandiClient
from gandi_mcp.errors import GandiError


@pytest.fixture
def client() -> BaseGandiClient:
    return BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=1)


class TestEmptyBodyStatusCode:
    """The empty-body branch must echo the response's HTTP status code.

    Kills mutmut survivors ``_parse_json__mutmut_5`` (status_code=None) and
    ``_parse_json__mutmut_7`` (status_code kwarg dropped, defaults to None).
    """

    @pytest.mark.parametrize("status", [200, 201, 202, 418, 500, 503])
    def test_empty_body_error_carries_response_status(self, client: BaseGandiClient, status: int) -> None:
        response = httpx.Response(status, content=b"")
        with pytest.raises(GandiError) as exc_info:
            client._parse_json(response)
        assert exc_info.value.status_code == status


class TestInvalidJsonBody:
    """The invalid-JSON branch must include the body (truncated to 200 chars).

    Kills:
    - ``_parse_json__mutmut_8`` -- ``body = None`` instead of ``response.text[:200]``.
    - ``_parse_json__mutmut_9`` -- ``[:201]`` instead of ``[:200]``.
    """

    def test_invalid_json_message_contains_body_prefix(self, client: BaseGandiClient) -> None:
        body = "<<not-json-payload-XYZ>>"
        response = httpx.Response(
            200,
            content=body.encode("utf-8"),
            headers={"content-type": "application/json"},
        )
        with pytest.raises(GandiError) as exc_info:
            client._parse_json(response)
        message = str(exc_info.value)
        assert body in message
        # Defensive: the mutant that sets body=None would produce 'None' in the message.
        assert ": None" not in message

    def test_invalid_json_body_truncated_to_exactly_200_chars(self, client: BaseGandiClient) -> None:
        # 201 chars: first 200 are 'A', the 201st char is a distinctive sentinel.
        body = ("A" * 200) + "Z"
        response = httpx.Response(
            200,
            content=body.encode("utf-8"),
            headers={"content-type": "application/json"},
        )
        with pytest.raises(GandiError) as exc_info:
            client._parse_json(response)
        message = str(exc_info.value)
        # The 200-char prefix must be present.
        assert "A" * 200 in message
        # The 201st char (Z) must NOT appear -- slicing is [:200], not [:201].
        assert "Z" not in message


class TestInvalidJsonStatusCode:
    """The invalid-JSON branch sets ``status_code=None``.

    The HTTP status arrived intact but the body didn't parse -- we cannot tell
    callers "this is a 200" because a corrupted 200 is no longer a 200 in any
    useful sense.

    No surviving mutant kills this distinctly (``_parse_json__mutmut_12`` only
    drops a redundant ``status_code=None`` kwarg, which is behaviourally
    equivalent -- documented in CONTRIBUTING.md). This test pins the invariant
    so a future refactor that *changes* it (e.g. propagating the status) is
    flagged at PR time.
    """

    def test_invalid_json_error_has_null_status_code(self, client: BaseGandiClient) -> None:
        response = httpx.Response(
            500,
            content=b"<<garbage>>",
            headers={"content-type": "application/json"},
        )
        with pytest.raises(GandiError) as exc_info:
            client._parse_json(response)
        assert exc_info.value.status_code is None
