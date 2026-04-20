"""Tests for Gandi MCP configuration and safety-gate logic."""

import pytest
from pydantic import ValidationError

from gandi_mcp.config import GandiConfig, GandiMode
from gandi_mcp.errors import (
    GandiAuthError,
    GandiConflictError,
    GandiConnectionError,
    GandiError,
    GandiNotFoundError,
    GandiPurchaseBlockedError,
    GandiRateLimitError,
    GandiReadOnlyError,
    handle_client_error,
)


class TestGandiMode:
    def test_readonly_is_default(self):
        config = GandiConfig(_env_file=None)
        assert config.gandi_mode == GandiMode.READONLY
        assert config.is_readwrite is False

    def test_readwrite_mode(self):
        config = GandiConfig(_env_file=None, gandi_mode=GandiMode.READWRITE)
        assert config.is_readwrite is True

    def test_invalid_mode_raises_validation_error(self):
        with pytest.raises(ValidationError):
            GandiConfig(_env_file=None, gandi_mode="bogus")


class TestPurchaseGate:
    def test_purchases_disabled_by_default(self):
        config = GandiConfig(_env_file=None)
        assert config.gandi_allow_purchases is False
        assert config.purchases_enabled is False

    def test_purchases_require_readwrite_even_if_flag_set(self):
        # Explicitly opted in but still readonly — purchases must stay blocked.
        config = GandiConfig(
            _env_file=None,
            gandi_mode=GandiMode.READONLY,
            gandi_allow_purchases=True,
        )
        assert config.purchases_enabled is False

    def test_purchases_require_flag_even_if_readwrite(self):
        config = GandiConfig(
            _env_file=None,
            gandi_mode=GandiMode.READWRITE,
            gandi_allow_purchases=False,
        )
        assert config.purchases_enabled is False

    def test_purchases_enabled_when_both_set(self):
        config = GandiConfig(
            _env_file=None,
            gandi_mode=GandiMode.READWRITE,
            gandi_allow_purchases=True,
        )
        assert config.purchases_enabled is True


class TestAuthenticatedFlag:
    def test_authenticated_false_when_no_token(self):
        config = GandiConfig(_env_file=None, gandi_token=None)
        assert config.authenticated is False

    def test_authenticated_true_when_token_set(self):
        config = GandiConfig(_env_file=None, gandi_token="test")
        assert config.authenticated is True

    def test_authenticated_false_when_token_empty_string(self):
        # Misconfigured .env with GANDI_TOKEN= produces SecretStr("") — not None
        # but still unusable. Must fail closed so lifespan surfaces the clean
        # "token not configured" branch rather than a 401 from the API.
        config = GandiConfig(_env_file=None, gandi_token="")
        assert config.authenticated is False


class TestDefaults:
    def test_default_base_url(self):
        config = GandiConfig(_env_file=None)
        assert config.gandi_api_base_url == "https://api.gandi.net"

    def test_default_timeout(self):
        config = GandiConfig(_env_file=None)
        assert config.gandi_request_timeout == 30

    def test_default_max_retries(self):
        config = GandiConfig(_env_file=None)
        assert config.gandi_max_retries == 3


class TestFieldConstraints:
    def test_timeout_zero_rejected(self):
        with pytest.raises(ValidationError, match="greater than 0"):
            GandiConfig(_env_file=None, gandi_request_timeout=0)

    def test_max_retries_negative_rejected(self):
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            GandiConfig(_env_file=None, gandi_max_retries=-1)

    def test_max_retries_zero_accepted(self):
        config = GandiConfig(_env_file=None, gandi_max_retries=0)
        assert config.gandi_max_retries == 0


class TestHandleClientError:
    def test_auth_error_mapping(self):
        with pytest.raises(Exception, match="Authentication failed"):
            handle_client_error(GandiAuthError("bad token", status_code=401))

    def test_not_found_error_mapping(self):
        with pytest.raises(Exception, match="Resource not found"):
            handle_client_error(GandiNotFoundError("no such domain", status_code=404))

    def test_conflict_error_mapping(self):
        with pytest.raises(Exception, match="State conflict"):
            handle_client_error(GandiConflictError("already exists", status_code=409))

    def test_rate_limit_error_mapping(self):
        with pytest.raises(Exception, match="Rate limit exceeded"):
            handle_client_error(GandiRateLimitError("slow down", status_code=429))

    def test_connection_error_mapping(self):
        with pytest.raises(Exception, match="Connection failed"):
            handle_client_error(GandiConnectionError("dns fail"))

    def test_readonly_error_mapping(self):
        with pytest.raises(Exception, match="Write operation blocked"):
            handle_client_error(GandiReadOnlyError("no writes"))

    def test_purchase_blocked_error_mapping(self):
        with pytest.raises(Exception, match="Purchase blocked"):
            handle_client_error(GandiPurchaseBlockedError("no spending"))

    def test_generic_gandi_error_mapping(self):
        with pytest.raises(Exception, match="Gandi API error"):
            handle_client_error(GandiError("boom", status_code=500))

    def test_unexpected_error_mapping(self):
        with pytest.raises(Exception, match="Unexpected error"):
            handle_client_error(RuntimeError("surprise"))
