"""Configuration management for Gandi MCP server using pydantic-settings."""

from __future__ import annotations

import enum
import logging

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class GandiMode(enum.StrEnum):
    """Server operation mode."""

    READONLY = "readonly"
    READWRITE = "readwrite"


class GandiConfig(BaseSettings):
    """Configuration loaded from environment variables and .env file."""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # Authentication
    gandi_token: SecretStr | None = None
    gandi_sharing_id: str | None = None

    # Safety gates
    gandi_mode: GandiMode = GandiMode.READONLY
    gandi_allow_purchases: bool = False

    # General
    gandi_api_base_url: str = "https://api.gandi.net"
    gandi_request_timeout: int = Field(default=30, gt=0)
    gandi_max_retries: int = Field(
        default=3,
        ge=1,
        description="Total request attempts including the first (1 = no retry).",
    )

    @property
    def is_readwrite(self) -> bool:
        """Whether the server is in read-write mode."""
        return self.gandi_mode == GandiMode.READWRITE

    @property
    def purchases_enabled(self) -> bool:
        """Purchases require BOTH readwrite mode AND an explicit opt-in."""
        return self.is_readwrite and self.gandi_allow_purchases

    @property
    def authenticated(self) -> bool:
        """Whether a Gandi token has been configured."""
        return self.gandi_token is not None
