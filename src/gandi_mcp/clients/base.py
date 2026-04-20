"""Base Gandi API client with retry, auth, and error mapping."""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from gandi_mcp.errors import (
    GandiAuthError,
    GandiBadRequestError,
    GandiConflictError,
    GandiConnectionError,
    GandiError,
    GandiNotFoundError,
    GandiRateLimitError,
    GandiServerError,
    GandiTimeoutError,
)


class BaseGandiClient:
    """Async httpx client for the Gandi v5 API.

    Uses Bearer authentication with a Personal Access Token. A ``sharing_id``,
    if configured, is attached to every request as a query parameter so
    reseller / multi-org accounts scope reads and writes to the chosen org.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        sharing_id: str | None = None,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        self._sharing_id = sharing_id
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "gandi-mcp/0.1.0 (+https://github.com/millsmillsymills/gandi-mcp)",
            },
            timeout=httpx.Timeout(timeout),
        )

    # ── HTTP helpers ────────────────────────────────────────────────────

    def _merge_sharing_id(self, params: dict[str, Any] | None) -> dict[str, Any] | None:
        """Inject ``sharing_id`` into a request's query params when configured.

        Returns ``None`` when there are no params and no sharing_id, so we
        don't send an empty ``?`` suffix. When ``sharing_id`` is configured,
        it unconditionally overrides any caller-supplied value — operator
        scoping is load-bearing for reseller / multi-org accounts and cannot
        be bypassed by a per-call kwarg.
        """
        if self._sharing_id is None:
            return params
        merged = dict(params) if params else {}
        if "sharing_id" in merged and merged["sharing_id"] != self._sharing_id:
            raise ValueError("sharing_id is managed by GANDI_SHARING_ID; do not pass it per-request")
        merged["sharing_id"] = self._sharing_id
        return merged

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Map HTTP status codes to typed exceptions."""
        if response.is_success:
            return
        status = response.status_code
        body = response.text[:500]
        if status == 400:
            raise GandiBadRequestError(f"HTTP {status}: {body}", status_code=status)
        if status in (401, 403):
            raise GandiAuthError(f"HTTP {status}: {body}", status_code=status)
        if status == 404:
            raise GandiNotFoundError(f"HTTP {status}: {body}", status_code=status)
        if status == 409:
            raise GandiConflictError(f"HTTP {status}: {body}", status_code=status)
        if status == 429:
            raise GandiRateLimitError(f"HTTP {status}: {body}", status_code=status)
        if 500 <= status < 600:
            raise GandiServerError(f"HTTP {status}: {body}", status_code=status)
        raise GandiError(f"HTTP {status}: {body}", status_code=status)

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Execute an HTTP request with retry on transient errors.

        ConnectError is always retried (the request never reached the server).
        TimeoutException is only retried for GET/HEAD — for POST/PUT/DELETE/PATCH
        the server may have processed the write before the response was lost,
        and a retry would cause double-execution (a particularly bad outcome
        for purchase-bearing endpoints).
        """
        kwargs["params"] = self._merge_sharing_id(kwargs.get("params"))

        retry_on: tuple[type[BaseException], ...] = (httpx.ConnectError,)
        if method.upper() in ("GET", "HEAD"):
            retry_on = (httpx.ConnectError, httpx.TimeoutException)

        @retry(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(retry_on),
            reraise=True,
        )
        async def _do() -> httpx.Response:
            return await self._client.request(method, path, **kwargs)

        try:
            response = await _do()
        except httpx.TimeoutException as exc:
            raise GandiTimeoutError(str(exc)) from exc
        except httpx.ConnectError as exc:
            raise GandiConnectionError(str(exc)) from exc

        self._raise_for_status(response)
        return response

    def _parse_json(self, response: httpx.Response) -> Any:
        """Parse JSON response body, wrapping decode errors as GandiError."""
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            body = response.text[:200]
            raise GandiError(
                f"Invalid JSON in response (HTTP {response.status_code}): {body}",
                status_code=None,
            ) from exc

    async def get(self, path: str, **kwargs: Any) -> Any:
        """HTTP GET, returns parsed JSON."""
        response = await self._request("GET", path, **kwargs)
        return self._parse_json(response)

    async def post(self, path: str, **kwargs: Any) -> Any:
        """HTTP POST, returns parsed JSON."""
        response = await self._request("POST", path, **kwargs)
        return self._parse_json(response)

    async def put(self, path: str, **kwargs: Any) -> Any:
        """HTTP PUT, returns parsed JSON."""
        response = await self._request("PUT", path, **kwargs)
        return self._parse_json(response)

    async def patch(self, path: str, **kwargs: Any) -> Any:
        """HTTP PATCH, returns parsed JSON."""
        response = await self._request("PATCH", path, **kwargs)
        return self._parse_json(response)

    async def delete(self, path: str, **kwargs: Any) -> Any:
        """HTTP DELETE, returns parsed JSON or empty dict."""
        response = await self._request("DELETE", path, **kwargs)
        return self._parse_json(response)

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def validate_connection(self) -> bool:
        """Validate connectivity + authentication by fetching user info.

        ``/v5/organization/user-info`` is a tiny GET that every valid PAT can
        reach regardless of scope, making it the right probe for startup
        validation.
        """
        try:
            await self.get("/v5/organization/user-info")
        except (GandiError, httpx.HTTPError):
            return False
        else:
            return True

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
