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

from gandi_mcp import __version__
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
                "User-Agent": f"gandi-mcp/{__version__} (+https://github.com/millsmillsymills/gandi-mcp)",
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

    # Safe allowlist for error-body fields surfaced to the agent. Confused-deputy
    # responses (e.g. a 403 listing owning org/customer info) could otherwise leak
    # another tenant's identifiers through `GandiError.details`.
    _ERROR_DETAIL_ALLOWED_KEYS = frozenset({"code", "cause", "message", "status", "object"})

    @classmethod
    def _parse_error_body(cls, response: httpx.Response) -> tuple[str, dict[str, Any] | None]:
        """Extract a readable message and a scrubbed dict from an error response.

        Returns ``(message, details)`` where ``message`` is the preferred human
        description (Gandi's ``cause`` or ``message`` when available, else the
        raw body truncated to 500 chars) and ``details`` is the parsed JSON
        body filtered to ``_ERROR_DETAIL_ALLOWED_KEYS``, or ``None`` when the
        body wasn't JSON.
        """
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type and response.content:
            try:
                parsed = response.json()
            except ValueError:
                return response.text[:500], None
            if isinstance(parsed, dict):
                parts = [str(parsed[k]) for k in ("cause", "message") if parsed.get(k)]
                message = " — ".join(parts) if parts else response.text[:500]
                details = {k: v for k, v in parsed.items() if k in cls._ERROR_DETAIL_ALLOWED_KEYS}
                return message, details
            return response.text[:500], None
        return response.text[:500], None

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> int | None:
        """Parse ``Retry-After`` as seconds. HTTP-date form is not honored."""
        raw = response.headers.get("retry-after")
        if not raw:
            return None
        try:
            return max(0, int(raw))
        except ValueError:
            return None

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Map HTTP status codes to typed exceptions.

        Parses JSON error bodies (when the server sends them) to surface
        Gandi's structured ``cause`` / ``message`` fields and attach the full
        parsed dict as ``details`` on the raised exception. Non-JSON bodies
        fall back to a truncated raw-text representation.
        """
        if response.is_success:
            return
        status = response.status_code
        body, details = self._parse_error_body(response)
        message = f"HTTP {status}: {body}"

        if status == 400:
            raise GandiBadRequestError(message, status_code=status, details=details)
        if status in (401, 403):
            raise GandiAuthError(message, status_code=status, details=details)
        if status == 404:
            raise GandiNotFoundError(message, status_code=status, details=details)
        if status == 409:
            raise GandiConflictError(message, status_code=status, details=details)
        if status == 429:
            raise GandiRateLimitError(
                message,
                status_code=status,
                details=details,
                retry_after=self._parse_retry_after(response),
            )
        if 500 <= status < 600:
            raise GandiServerError(message, status_code=status, details=details)
        raise GandiError(message, status_code=status, details=details)

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
            raise GandiTimeoutError(str(exc), method=method) from exc
        except httpx.ConnectError as exc:
            raise GandiConnectionError(str(exc)) from exc
        except httpx.HTTPError as exc:
            # Catches WriteError, ReadError, RemoteProtocolError, PoolTimeout,
            # NetworkError, etc. — anything below httpx.HTTPError that isn't
            # timeout or connect. Without this, tools surface "Unexpected
            # error" for routine transport failures.
            raise GandiConnectionError(str(exc)) from exc

        self._raise_for_status(response)
        return response

    def _parse_json(self, response: httpx.Response) -> Any:
        """Parse JSON response body, wrapping decode errors as GandiError.

        Only 204 is allowed to return ``{}``. Any other status with an empty
        body is surfaced as an error — a 200 with no content most often means
        a proxy / CDN stripped or truncated the upstream response, and
        returning ``{}`` would silently mislead the agent (e.g. "zero
        records").
        """
        if response.status_code == 204:
            return {}
        if not response.content:
            raise GandiError(
                f"Empty response body from HTTP {response.status_code}",
                status_code=response.status_code,
            )
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

    async def validate_connection(self) -> None:
        """Validate connectivity + authentication by fetching user info.

        Raises the underlying typed ``GandiError`` (or ``httpx.HTTPError``) on
        failure so the caller can distinguish between auth failures, network
        problems, and upstream 5xx. Returns ``None`` on success.

        ``/v5/organization/user-info`` is a tiny GET commonly reachable with
        a valid PAT; scoped PATs may not reach it, in which case startup
        falsely reports a disabled server. Revisit if that becomes a real
        operator complaint.
        """
        await self.get("/v5/organization/user-info")

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
