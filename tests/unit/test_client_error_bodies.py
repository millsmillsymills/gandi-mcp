"""Tests for structured error-body parsing, Retry-After, and POST-timeout messaging."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from gandi_mcp.clients.base import BaseGandiClient
from gandi_mcp.errors import (
    GandiBadRequestError,
    GandiRateLimitError,
    GandiTimeoutError,
    handle_client_error,
)


@pytest.fixture
def client() -> BaseGandiClient:
    return BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=1)


class TestStructuredErrorBody:
    """Gandi JSON error bodies surface cause/message and attach full dict as details."""

    @pytest.mark.asyncio
    async def test_json_error_surfaces_cause_and_message(self, client: BaseGandiClient) -> None:
        body = {"code": 400, "cause": "Invalid request", "message": "fqdn is required", "object": "domain"}
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.get("/v5/domain/domains").mock(
                return_value=httpx.Response(400, json=body, headers={"content-type": "application/json"}),
            )
            with pytest.raises(GandiBadRequestError) as exc_info:
                await client.get("/v5/domain/domains")
            # Human message includes cause + message.
            assert "Invalid request" in str(exc_info.value)
            assert "fqdn is required" in str(exc_info.value)
            # Full body preserved for programmatic inspection.
            assert exc_info.value.details == body
        await client.close()

    @pytest.mark.asyncio
    async def test_non_json_body_falls_back_to_raw_text(self, client: BaseGandiClient) -> None:
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.get("/v5/domain/domains").mock(
                return_value=httpx.Response(500, text="upstream unavailable", headers={"content-type": "text/plain"}),
            )
            with pytest.raises(Exception) as exc_info:  # noqa: PT011
                await client.get("/v5/domain/domains")
            assert "upstream unavailable" in str(exc_info.value)
            assert exc_info.value.details is None  # type: ignore[attr-defined]
        await client.close()

    @pytest.mark.asyncio
    async def test_malformed_json_falls_back_cleanly(self, client: BaseGandiClient) -> None:
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.get("/v5/domain/domains").mock(
                return_value=httpx.Response(400, text="not json", headers={"content-type": "application/json"}),
            )
            with pytest.raises(GandiBadRequestError) as exc_info:
                await client.get("/v5/domain/domains")
            # No crash — message falls back to raw body, details stays None.
            assert exc_info.value.details is None
        await client.close()


class TestRetryAfterHeader:
    @pytest.mark.asyncio
    async def test_retry_after_seconds_parsed(self, client: BaseGandiClient) -> None:
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.get("/v5/domain/domains").mock(
                return_value=httpx.Response(429, text="too many requests", headers={"retry-after": "42"}),
            )
            with pytest.raises(GandiRateLimitError) as exc_info:
                await client.get("/v5/domain/domains")
            assert exc_info.value.retry_after == 42
        await client.close()

    @pytest.mark.asyncio
    async def test_retry_after_missing_is_none(self, client: BaseGandiClient) -> None:
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.get("/v5/domain/domains").mock(return_value=httpx.Response(429, text="slow down"))
            with pytest.raises(GandiRateLimitError) as exc_info:
                await client.get("/v5/domain/domains")
            assert exc_info.value.retry_after is None
        await client.close()

    @pytest.mark.asyncio
    async def test_retry_after_http_date_ignored(self, client: BaseGandiClient) -> None:
        """HTTP-date form isn't parsed (rare in practice); surfaces as None, not a crash."""
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.get("/v5/domain/domains").mock(
                return_value=httpx.Response(429, text="slow", headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}),
            )
            with pytest.raises(GandiRateLimitError) as exc_info:
                await client.get("/v5/domain/domains")
            assert exc_info.value.retry_after is None
        await client.close()

    def test_tool_error_message_includes_retry_after(self) -> None:
        err = GandiRateLimitError("HTTP 429: slow", status_code=429, retry_after=30)
        with pytest.raises(ToolError, match="Retry after 30s"):
            handle_client_error(err)

    def test_tool_error_message_without_retry_after(self) -> None:
        err = GandiRateLimitError("HTTP 429: slow", status_code=429)
        with pytest.raises(ToolError, match="Try again later"):
            handle_client_error(err)


class TestTimeoutMethod:
    @pytest.mark.asyncio
    async def test_post_timeout_records_method(self) -> None:
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=1)
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.post("/v5/domain/domains").mock(side_effect=httpx.ReadTimeout("timeout"))
            with pytest.raises(GandiTimeoutError) as exc_info:
                await client.post("/v5/domain/domains", json={})
            assert exc_info.value.method == "POST"
        await client.close()

    @pytest.mark.asyncio
    async def test_get_timeout_records_method(self) -> None:
        client = BaseGandiClient(base_url="https://api.gandi.net", token="t", max_retries=1)
        with respx.mock(base_url="https://api.gandi.net") as mock:
            mock.get("/v5/organization/user-info").mock(side_effect=httpx.ReadTimeout("timeout"))
            with pytest.raises(GandiTimeoutError) as exc_info:
                await client.get("/v5/organization/user-info")
            assert exc_info.value.method == "GET"
        await client.close()

    def test_post_timeout_tool_error_warns_about_possible_server_write(self) -> None:
        err = GandiTimeoutError("read timeout", method="POST")
        with pytest.raises(ToolError, match="check state before retrying"):
            handle_client_error(err)

    def test_patch_timeout_tool_error_warns_about_possible_server_write(self) -> None:
        err = GandiTimeoutError("read timeout", method="PATCH")
        with pytest.raises(ToolError, match="check state before retrying"):
            handle_client_error(err)

    def test_get_timeout_tool_error_does_not_warn(self) -> None:
        err = GandiTimeoutError("read timeout", method="GET")
        with pytest.raises(ToolError, match="did not respond in time"):
            handle_client_error(err)

    def test_timeout_without_method_does_not_warn(self) -> None:
        err = GandiTimeoutError("read timeout")
        with pytest.raises(ToolError, match="did not respond in time"):
            handle_client_error(err)
