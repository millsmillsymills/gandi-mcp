"""Exception hierarchy and error mapping for Gandi MCP server."""

from __future__ import annotations

import logging
from typing import Any, NoReturn

from fastmcp.exceptions import ToolError

logger = logging.getLogger(__name__)

# HTTP methods that are not idempotent — a timeout mid-request may leave the
# server in a partially-written state, so retrying could double-execute.
_NON_IDEMPOTENT_METHODS = frozenset({"POST", "PATCH"})


class GandiError(Exception):
    """Base exception for all Gandi API errors.

    ``details`` carries the parsed JSON error body from Gandi (when the
    response had ``Content-Type: application/json``) so operators and the
    agent can inspect structured fields like ``code`` / ``cause`` / ``object``
    without re-parsing the message string.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class GandiAuthError(GandiError):
    """Authentication or authorization failure (401/403)."""


class GandiBadRequestError(GandiError):
    """Malformed or invalid request payload (400)."""


class GandiNotFoundError(GandiError):
    """Resource not found (404)."""


class GandiConflictError(GandiError):
    """State conflict — already exists / not deletable / etc. (409)."""


class GandiRateLimitError(GandiError):
    """Rate limit exceeded (429).

    ``retry_after`` is the parsed value of the ``Retry-After`` response header
    in seconds when present. Agents should back off at least this long before
    retrying.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
        retry_after: int | None = None,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(message, status_code=status_code, details=details)


class GandiServerError(GandiError):
    """Upstream server failure (5xx)."""


class GandiConnectionError(GandiError):
    """Connection failure (DNS, network, TCP reset)."""


class GandiTimeoutError(GandiConnectionError):
    """Request exceeded the configured timeout.

    ``method`` is the HTTP method of the request that timed out. Non-idempotent
    methods (POST, PATCH) may have been partially processed server-side before
    the response was lost; the error message surfaced to the agent calls this
    out so it can check state before retrying a purchase-bearing endpoint.
    """

    def __init__(self, message: str, method: str | None = None) -> None:
        self.method = method.upper() if method else None
        super().__init__(message)


class GandiReadOnlyError(GandiError):
    """Write operation attempted in read-only mode."""


class GandiPurchaseBlockedError(GandiError):
    """Purchase operation attempted while purchases are disabled.

    Independent of read-only mode — purchases are blocked unless the operator
    sets ``GANDI_ALLOW_PURCHASES=true`` AND ``GANDI_MODE=readwrite``. The two
    gates are defense-in-depth against the agent spending money.
    """


def handle_client_error(error: Exception) -> NoReturn:
    """Map Gandi exceptions to FastMCP ToolError with agent-readable messages.

    Raises:
        ToolError: Always raised with a descriptive message.
    """
    if isinstance(error, GandiAuthError):
        raise ToolError(f"Authentication failed: {error}. Check GANDI_TOKEN.") from error
    if isinstance(error, GandiBadRequestError):
        raise ToolError(f"Invalid request: {error}.") from error
    if isinstance(error, GandiNotFoundError):
        raise ToolError(f"Resource not found: {error}") from error
    if isinstance(error, GandiConflictError):
        raise ToolError(f"State conflict: {error}") from error
    if isinstance(error, GandiRateLimitError):
        hint = f" Retry after {error.retry_after}s." if error.retry_after is not None else " Try again later."
        raise ToolError(f"Rate limit exceeded: {error}.{hint}") from error
    if isinstance(error, GandiServerError):
        raise ToolError(f"Gandi server error: {error}. The Gandi API may be unhealthy.") from error
    if isinstance(error, GandiTimeoutError):
        if error.method in _NON_IDEMPOTENT_METHODS:
            raise ToolError(
                f"Request timed out during {error.method}: {error}. The write may or may not "
                "have taken effect on the server — check state before retrying."
            ) from error
        raise ToolError(f"Request timed out: {error}. The Gandi API did not respond in time.") from error
    if isinstance(error, GandiConnectionError):
        raise ToolError(f"Connection failed: {error}. Check network connectivity to api.gandi.net.") from error
    if isinstance(error, GandiReadOnlyError):
        raise ToolError(f"Write operation blocked: {error}. Server is in read-only mode.") from error
    if isinstance(error, GandiPurchaseBlockedError):
        raise ToolError(
            f"Purchase blocked: {error}. Set GANDI_ALLOW_PURCHASES=true AND GANDI_MODE=readwrite to enable."
        ) from error
    if isinstance(error, GandiError):
        raise ToolError(f"Gandi API error: {error}") from error
    # Unexpected errors
    logger.exception("Unexpected error in tool execution")
    raise ToolError(f"Unexpected error: {error}") from error
