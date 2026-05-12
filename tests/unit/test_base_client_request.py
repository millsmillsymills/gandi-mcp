"""Tight assertions for ``BaseGandiClient._request`` (closes #83).

These tests pin the surviving baseline mutants in the request-plumbing
cluster. The two areas are:

1. Caller-supplied ``params`` survive the ``_merge_sharing_id`` step.
   The mutants replace ``kwargs.get("params")`` with ``None`` (or a wrong
   key like ``"PARAMS"``), which silently drops the caller's query params.
   Pinning that callers-can-pass-params end-to-end kills the whole cluster.

2. The underlying httpx exception text survives the rewrap into
   ``GandiTimeoutError`` / ``GandiConnectionError``. Mutants replace
   ``str(exc)`` with ``None`` (so the message becomes the empty string or
   ``"None"``), losing the operator's only clue about what failed.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from gandi_mcp.clients.base import BaseGandiClient
from gandi_mcp.errors import GandiConnectionError, GandiTimeoutError


@pytest.fixture
def client() -> BaseGandiClient:
    return BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=1)


class TestCallerParamsReachTheWire:
    """``_request`` must forward caller-supplied ``params`` to httpx.

    Pins mutants that turn ``kwargs.get("params")`` into ``None`` /
    ``kwargs.get(None)`` / ``kwargs.get("PARAMS")`` etc. -- all of which
    silently drop the caller's query string.
    """

    @pytest.mark.asyncio
    async def test_caller_params_appear_on_request_url(self, client: BaseGandiClient) -> None:
        """A caller passing ``params={...}`` lands on the wire untouched."""
        with respx.mock(base_url="https://api.gandi.net") as mock:
            route = mock.get("/v5/domain/domains").mock(return_value=httpx.Response(200, json=[]))
            await client.get("/v5/domain/domains", params={"per_page": "50", "page": "1"})
            assert route.called
            qs = route.calls.last.request.url.params
            assert qs["per_page"] == "50"
            assert qs["page"] == "1"
        await client.close()

    @pytest.mark.asyncio
    async def test_caller_params_coexist_with_sharing_id(self) -> None:
        """Sharing-id injection composes with caller params (does not displace them)."""
        client = BaseGandiClient(
            base_url="https://api.gandi.net",
            token="t",
            sharing_id="org-uuid",
            max_retries=1,
        )
        with respx.mock(base_url="https://api.gandi.net") as mock:
            route = mock.get("/v5/domain/domains").mock(return_value=httpx.Response(200, json=[]))
            await client.get("/v5/domain/domains", params={"per_page": "25"})
            qs = route.calls.last.request.url.params
            assert qs["per_page"] == "25"
            assert qs["sharing_id"] == "org-uuid"
        await client.close()


class TestRewrappedExceptionPreservesMessage:
    """The underlying httpx exception text survives the rewrap.

    Pins mutants that drop the original ``str(exc)`` -- without these
    assertions an operator sees an empty / ``"None"`` message and has no
    clue what actually failed.
    """

    @pytest.mark.asyncio
    async def test_timeout_message_carries_underlying_text(self, client: BaseGandiClient) -> None:
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.get("/v5/organization/user-info").mock(side_effect=httpx.ReadTimeout("slow upstream"))
            with pytest.raises(GandiTimeoutError, match="slow upstream") as exc_info:
                await client.get("/v5/organization/user-info")
            # Defense-in-depth: the rewrapped message must not be the literal
            # ``"None"`` produced by ``str(None)``.
            assert str(exc_info.value) != "None"
        await client.close()

    @pytest.mark.asyncio
    async def test_connect_error_message_carries_underlying_text(self, client: BaseGandiClient) -> None:
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.get("/v5/organization/user-info").mock(side_effect=httpx.ConnectError("dns failure"))
            with pytest.raises(GandiConnectionError, match="dns failure") as exc_info:
                await client.get("/v5/organization/user-info")
            assert str(exc_info.value) != "None"
        await client.close()
