"""Exception hierarchy and error mapping for Gandi MCP server."""

from __future__ import annotations

import logging
from typing import NoReturn

from fastmcp.exceptions import ToolError

logger = logging.getLogger(__name__)


class GandiError(Exception):
    """Base exception for all Gandi API errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
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
    """Rate limit exceeded (429)."""


class GandiServerError(GandiError):
    """Upstream server failure (5xx)."""


class GandiConnectionError(GandiError):
    """Connection failure (DNS, network, TCP reset)."""


class GandiTimeoutError(GandiConnectionError):
    """Request exceeded the configured timeout."""


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
        raise ToolError(f"Rate limit exceeded: {error}. Try again later.") from error
    if isinstance(error, GandiServerError):
        raise ToolError(f"Gandi server error: {error}. The Gandi API may be unhealthy.") from error
    if isinstance(error, GandiTimeoutError):
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
