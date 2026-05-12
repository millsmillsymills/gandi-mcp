"""Pin the agent-facing wording produced by ``handle_client_error`` (#84).

``handle_client_error`` translates each typed Gandi exception into a
``ToolError`` whose ``message`` is what the MCP client (and the agent
driving it) actually sees. The typed exception class is asserted elsewhere;
this module asserts the *message content* — env-var names, recovery hints,
retry guidance — because mutmut surfaced that the wording drifted under
mutation without any test catching it.

Each substring asserted here corresponds to a survived mutant in the
baseline. Removing the substring assertion would re-introduce the gap.
"""

from __future__ import annotations

import logging

import pytest
from fastmcp.exceptions import ToolError

from gandi_mcp.errors import (
    GandiAuthError,
    GandiBadRequestError,
    GandiConflictError,
    GandiConnectionError,
    GandiError,
    GandiNotFoundError,
    GandiPurchaseBlockedError,
    GandiRateLimitError,
    GandiReadOnlyError,
    GandiServerError,
    GandiTimeoutError,
    handle_client_error,
)


def _raise(error: Exception) -> ToolError:
    """Run the mapper and surface the resulting ``ToolError`` for inspection."""
    try:
        handle_client_error(error)
    except ToolError as exc:
        return exc
    raise AssertionError("handle_client_error did not raise")  # pragma: no cover


class TestAuthErrorMessage:
    def test_message_names_token_env_var(self) -> None:
        """The auth-error hint names ``GANDI_TOKEN`` so an operator can fix it."""
        tool_error = _raise(GandiAuthError("HTTP 401: bad token"))
        assert "GANDI_TOKEN" in str(tool_error)

    def test_message_starts_with_authentication_failed(self) -> None:
        tool_error = _raise(GandiAuthError("HTTP 401: bad token"))
        assert "Authentication failed" in str(tool_error)


class TestBadRequestMessage:
    def test_message_includes_invalid_request_label(self) -> None:
        """``ToolError(None)`` was a survived mutant — pin the wording."""
        tool_error = _raise(GandiBadRequestError("HTTP 400: missing field"))
        assert "Invalid request" in str(tool_error)
        assert "missing field" in str(tool_error)


class TestNotFoundMessage:
    def test_message_includes_resource_not_found(self) -> None:
        tool_error = _raise(GandiNotFoundError("HTTP 404: domain not found"))
        assert "Resource not found" in str(tool_error)


class TestConflictMessage:
    def test_message_includes_state_conflict(self) -> None:
        tool_error = _raise(GandiConflictError("HTTP 409: already exists"))
        assert "State conflict" in str(tool_error)


class TestRateLimitMessage:
    def test_retry_after_value_in_hint_when_present(self) -> None:
        """When the server sent ``Retry-After``, the hint surfaces the seconds value."""
        err = GandiRateLimitError("HTTP 429", retry_after=42)
        tool_error = _raise(err)
        message = str(tool_error)
        assert "Retry after 42s" in message
        assert "Rate limit exceeded" in message

    def test_fallback_hint_when_retry_after_absent(self) -> None:
        """No ``Retry-After`` → the agent sees a generic ``Try again later`` hint.

        Anchored at the end of the message so mutations wrapping the literal
        (``"XX Try again later.XX"``) still fail the assertion — substring
        ``Try again later`` matches the wrapped form, but ``endswith`` does
        not.
        """
        err = GandiRateLimitError("HTTP 429", retry_after=None)
        message = str(_raise(err))
        assert message.endswith(" Try again later.")

    def test_retry_after_uses_lowercase_s_unit(self) -> None:
        """The unit suffix is the lowercase ``s`` (seconds) — pinned to catch unit drift."""
        err = GandiRateLimitError("HTTP 429", retry_after=7)
        assert "Retry after 7s." in str(_raise(err))


class TestServerErrorMessage:
    def test_message_includes_gandi_server_error(self) -> None:
        """``ToolError(None)`` was a survived mutant — pin the wording."""
        tool_error = _raise(GandiServerError("HTTP 503"))
        assert "Gandi server error" in str(tool_error)

    def test_message_warns_api_may_be_unhealthy(self) -> None:
        """The hint nudges an operator to check Gandi's status before blaming code."""
        tool_error = _raise(GandiServerError("HTTP 503"))
        assert "Gandi API may be unhealthy" in str(tool_error)


class TestTimeoutMessage:
    def test_timeout_on_post_warns_about_partial_writes(self) -> None:
        """The non-idempotent-timeout message tells the agent to check state.

        The cross-literal substring ``may or may not have taken`` straddles
        the two adjacent string-literal halves of the message. A mutation
        that wraps the second half (``XXhave taken effect...XX``) breaks
        the cross-boundary phrase and fails the assertion. Substring-only
        checks on either half alone survived the mutation.
        """
        err = GandiTimeoutError("server did not respond", method="POST")
        tool_error = _raise(err)
        message = str(tool_error)
        assert "Request timed out during POST" in message
        assert "may or may not have taken effect on the server" in message
        assert "check state before retrying." in message

    def test_timeout_on_patch_also_warns(self) -> None:
        """PATCH shares the non-idempotent message — same hint required."""
        err = GandiTimeoutError("server did not respond", method="PATCH")
        assert "may or may not have taken effect on the server" in str(_raise(err))

    def test_timeout_on_get_uses_generic_message(self) -> None:
        """GET is idempotent — the partial-write warning is absent on this branch."""
        err = GandiTimeoutError("server did not respond", method="GET")
        message = str(_raise(err))
        assert "did not respond in time" in message
        assert "have taken effect" not in message


class TestConnectionErrorMessage:
    def test_message_includes_network_check_hint(self) -> None:
        """The hint points operators at the Gandi hostname."""
        tool_error = _raise(GandiConnectionError("dns lookup failed"))
        assert "api.gandi.net" in str(tool_error)


class TestReadOnlyMessage:
    def test_message_names_readonly_mode(self) -> None:
        tool_error = _raise(GandiReadOnlyError("Cannot register domain in read-only mode"))
        assert "read-only mode" in str(tool_error)
        assert "blocked" in str(tool_error)


class TestPurchaseBlockedMessage:
    def test_message_names_both_required_env_flags(self) -> None:
        """Both env vars must be named — operator can't enable purchases without either."""
        tool_error = _raise(GandiPurchaseBlockedError("Cannot register domain — purchases disabled"))
        message = str(tool_error)
        assert "GANDI_ALLOW_PURCHASES=true" in message
        assert "GANDI_MODE=readwrite" in message


class TestGenericGandiErrorMessage:
    def test_message_prefixed_with_gandi_api_error(self) -> None:
        tool_error = _raise(GandiError("HTTP 418: I'm a teapot"))
        assert "Gandi API error" in str(tool_error)


class TestUnexpectedErrorLogging:
    def test_unexpected_error_logs_canonical_message(self, caplog: pytest.LogCaptureFixture) -> None:
        """The logger sees the exact canonical message — case and wording pinned.

        Three survived mutants targeted this single log call (``None`` argument,
        ``XX..XX`` wrappers, lowercased text, ALLCAPS). Asserting the exact
        string kills all three at once.
        """
        with (
            caplog.at_level(logging.ERROR, logger="gandi_mcp.errors"),
            pytest.raises(ToolError, match="Unexpected error"),
        ):
            handle_client_error(RuntimeError("something exotic"))
        messages = [r.message for r in caplog.records]
        assert "Unexpected error in tool execution" in messages

    def test_unexpected_error_tool_message_includes_original(self) -> None:
        tool_error = _raise(RuntimeError("custom failure"))
        assert "Unexpected error" in str(tool_error)
        assert "custom failure" in str(tool_error)


class TestRateLimitErrorPreservesDetails:
    """``GandiRateLimitError.__init__`` had two survived mutants that dropped ``details``.

    The agent reads ``details`` for structured fields (``cause``, ``object``);
    silently losing them on rate-limit responses would mask which endpoint
    triggered the limit.
    """

    def test_details_kwarg_is_forwarded_to_base(self) -> None:
        err = GandiRateLimitError(
            "HTTP 429",
            status_code=429,
            details={"cause": "throttled", "object": "domain"},
            retry_after=10,
        )
        assert err.details == {"cause": "throttled", "object": "domain"}

    def test_details_can_be_none(self) -> None:
        err = GandiRateLimitError("HTTP 429", status_code=429, details=None, retry_after=10)
        assert err.details is None


class TestTimeoutErrorPreservesMessage:
    """``GandiTimeoutError.__init__`` survived the ``super().__init__(None)`` mutation.

    The mapper later interpolates ``{error}`` into the ``ToolError`` text; if
    the message string was wiped at construction time the agent would see
    only an empty diagnostic.
    """

    def test_message_survives_construction(self) -> None:
        err = GandiTimeoutError("server did not respond", method="POST")
        assert str(err) == "server did not respond"

    def test_message_appears_in_handle_client_error_output(self) -> None:
        err = GandiTimeoutError("server did not respond", method="POST")
        assert "server did not respond" in str(_raise(err))
