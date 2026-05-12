"""Targeted tests for ``BaseGandiClient`` HTTP-method wrapper survivors (#83).

The five wrappers (``get`` / ``post`` / ``put`` / ``patch`` / ``delete``) are
each a single line: ``await self._request(METHOD, path, **kwargs)`` followed by
``return self._parse_json(response)``. Mutmut generates two interesting
survivors per wrapper:

- ``__mutmut_6`` -- ``**kwargs`` is dropped from the ``_request`` call. A
  caller passing ``params=`` or ``json=`` would silently see them swallowed.
- ``__mutmut_9`` (put/patch only) -- ``self._parse_json(response)`` becomes
  ``self._parse_json(None)``, which then ``AttributeError``s on
  ``None.status_code``.

The ``__mutmut_8`` variants (``"GET"`` -> ``"get"`` etc.) are behaviourally
equivalent at every observable surface: ``_request`` normalises with
``method.upper()`` before its retry decision, ``httpx.Request`` uppercases the
method before sending, and ``GandiTimeoutError`` uppercases ``method`` in
``__init__`` -- documented in CONTRIBUTING.md.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
import pytest
import respx

from gandi_mcp.clients.base import BaseGandiClient

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@asynccontextmanager
async def make_client() -> AsyncIterator[BaseGandiClient]:
    c = BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=1)
    try:
        yield c
    finally:
        await c.close()


class TestKwargsPropagate:
    """Each wrapper forwards ``**kwargs`` to ``_request``.

    Kills the ``__mutmut_6`` variant for every wrapper. The mutant rewrites
    the call to ``self._request("METHOD", path, )`` -- swallowing any caller
    kwargs (``params``, ``json``, ``headers``). We exercise the realistic
    surfaces:

    - ``params=`` -- the wire URL must carry the query string.
    - ``json=`` -- the wire body must be the encoded JSON document.
    """

    @pytest.mark.asyncio
    async def test_get_forwards_params(self) -> None:
        async with make_client() as client, respx.mock(base_url="https://api.gandi.net") as mock:
            route = mock.get("/v5/organization/user-info").mock(return_value=httpx.Response(200, json={"ok": True}))
            result = await client.get("/v5/organization/user-info", params={"per_page": 50})
            assert result == {"ok": True}
            assert route.called
            assert route.calls.last.request.url.params["per_page"] == "50"

    @pytest.mark.asyncio
    async def test_post_forwards_json_body(self) -> None:
        payload = {"fqdn": "example.com", "owner": {"email": "a@b.test"}}
        async with make_client() as client, respx.mock(base_url="https://api.gandi.net") as mock:
            route = mock.post("/v5/domain/domains").mock(return_value=httpx.Response(201, json={"id": "abc"}))
            result = await client.post("/v5/domain/domains", json=payload)
            assert result == {"id": "abc"}
            assert route.called
            assert json.loads(route.calls.last.request.content) == payload

    @pytest.mark.asyncio
    async def test_put_forwards_json_body(self) -> None:
        payload = {"rrset_values": ["1.2.3.4"], "rrset_ttl": 300}
        async with make_client() as client, respx.mock(base_url="https://api.gandi.net") as mock:
            route = mock.put("/v5/livedns/domains/example.com/records/www/A").mock(
                return_value=httpx.Response(200, json={"message": "ok"}),
            )
            result = await client.put(
                "/v5/livedns/domains/example.com/records/www/A",
                json=payload,
            )
            assert result == {"message": "ok"}
            assert route.called
            assert json.loads(route.calls.last.request.content) == payload

    @pytest.mark.asyncio
    async def test_patch_forwards_json_body(self) -> None:
        payload = {"autorenew": {"enabled": True, "duration": 1}}
        async with make_client() as client, respx.mock(base_url="https://api.gandi.net") as mock:
            route = mock.patch("/v5/domain/domains/example.com/autorenew").mock(
                return_value=httpx.Response(200, json={"message": "ok"}),
            )
            result = await client.patch(
                "/v5/domain/domains/example.com/autorenew",
                json=payload,
            )
            assert result == {"message": "ok"}
            assert route.called
            assert json.loads(route.calls.last.request.content) == payload

    @pytest.mark.asyncio
    async def test_delete_forwards_params(self) -> None:
        async with make_client() as client, respx.mock(base_url="https://api.gandi.net") as mock:
            route = mock.delete("/v5/livedns/domains/example.com/records").mock(
                return_value=httpx.Response(204),
            )
            result = await client.delete(
                "/v5/livedns/domains/example.com/records",
                params={"rrset_type": "A"},
            )
            assert result == {}
            assert route.called
            assert route.calls.last.request.url.params["rrset_type"] == "A"


class TestParseJsonResponseIsForwarded:
    """Each wrapper passes the real response to ``_parse_json`` (not ``None``).

    Kills the ``__mutmut_9`` variants for ``put`` and ``patch``. The mutant
    rewrites ``return self._parse_json(response)`` to
    ``self._parse_json(None)``, which ``AttributeError``s on
    ``None.status_code`` inside ``_parse_json``. The general-coverage
    assertions also lock the wrapper return value to the parsed body.
    """

    @pytest.mark.asyncio
    async def test_put_returns_parsed_body(self) -> None:
        async with make_client() as client, respx.mock(base_url="https://api.gandi.net") as mock:
            mock.put("/v5/domain/domains/example.com/authinfo").mock(
                return_value=httpx.Response(200, json={"authinfo": "secret-token"}),
            )
            assert await client.put("/v5/domain/domains/example.com/authinfo") == {"authinfo": "secret-token"}

    @pytest.mark.asyncio
    async def test_patch_returns_parsed_body(self) -> None:
        async with make_client() as client, respx.mock(base_url="https://api.gandi.net") as mock:
            mock.patch("/v5/domain/domains/example.com/autorenew").mock(
                return_value=httpx.Response(200, json={"message": "renewed"}),
            )
            result = await client.patch(
                "/v5/domain/domains/example.com/autorenew",
                json={"autorenew": {"enabled": True}},
            )
            assert result == {"message": "renewed"}

    @pytest.mark.asyncio
    async def test_get_returns_parsed_body(self) -> None:
        async with make_client() as client, respx.mock(base_url="https://api.gandi.net") as mock:
            mock.get("/v5/organization/user-info").mock(
                return_value=httpx.Response(200, json={"username": "demo"}),
            )
            assert await client.get("/v5/organization/user-info") == {"username": "demo"}

    @pytest.mark.asyncio
    async def test_post_returns_parsed_body(self) -> None:
        async with make_client() as client, respx.mock(base_url="https://api.gandi.net") as mock:
            mock.post("/v5/domain/domains").mock(
                return_value=httpx.Response(201, json={"id": "new-domain"}),
            )
            assert await client.post("/v5/domain/domains", json={}) == {"id": "new-domain"}

    @pytest.mark.asyncio
    async def test_delete_returns_parsed_body(self) -> None:
        async with make_client() as client, respx.mock(base_url="https://api.gandi.net") as mock:
            mock.delete("/v5/domain/domains/example.com").mock(
                return_value=httpx.Response(200, json={"message": "deleted"}),
            )
            assert await client.delete("/v5/domain/domains/example.com") == {"message": "deleted"}


class TestMethodOnTheWire:
    """Each wrapper sends the correct HTTP method.

    Sanity check that nobody accidentally swapped two wrappers (e.g. ``put``
    sending ``POST``). The ``__mutmut_8`` lowercase variants pass this check
    because both ``httpx`` and ``respx`` normalise the method to uppercase
    before comparison -- documented as equivalent in CONTRIBUTING.md.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("verb", "path"),
        [
            ("get", "/v5/organization/user-info"),
            ("post", "/v5/domain/domains"),
            ("put", "/v5/livedns/domains/example.com/records/www/A"),
            ("patch", "/v5/domain/domains/example.com/autorenew"),
            ("delete", "/v5/domain/domains/example.com"),
        ],
    )
    async def test_wrapper_sends_matching_method(self, verb: str, path: str) -> None:
        async with make_client() as client, respx.mock(base_url="https://api.gandi.net") as mock:
            route = getattr(mock, verb)(path).mock(return_value=httpx.Response(200, json={}))
            await getattr(client, verb)(path)
            assert route.called
            assert route.calls.last.request.method == verb.upper()
