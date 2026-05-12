"""Tier-3 contract-test fixtures.

These tests replay cassettes recorded against the live Gandi v5 API. In CI,
``record_mode='none'`` means a missing cassette is a hard failure (not a record
attempt). To re-record locally, run ``make refresh-cassettes`` — see
CONTRIBUTING.md "Recording contract cassettes".

Invariants enforced here:
- The test ``GandiClient`` is built with ``sharing_id=None`` because the
  cassette URLs have ``sharing_id`` stripped by ``filter_query_parameters``.
  Building the client with any other value would cause cassette-replay misses
  on the URL matcher.
- ``GANDI_TOKEN`` is only read at *record* time. At replay time the token can
  be any non-empty string; we hardcode ``"REDACTED"``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from gandi_mcp.clients.gandi import GandiClient
from tests.contract._redact import redact_response

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_DEFAULT_CASSETTE_DIR = "tests/contract/cassettes"


@pytest.fixture(scope="session")
def vcr_config() -> dict[str, object]:
    """pytest-recording session config — applies to every ``@pytest.mark.vcr`` test."""
    cassette_dir = os.environ.get("VCR_CASSETTE_DIR", _DEFAULT_CASSETTE_DIR)
    return {
        "cassette_library_dir": cassette_dir,
        "filter_headers": ["authorization", "x-api-key", "cookie", "set-cookie"],
        "filter_query_parameters": ["sharing_id"],
        "before_record_response": redact_response,
        "record_mode": "none",
        "match_on": ["method", "scheme", "host", "port", "path", "query"],
    }


@pytest.fixture
async def client() -> AsyncIterator[GandiClient]:
    """A GandiClient that matches the shape recorded in cassettes.

    sharing_id is None on purpose — see module docstring.
    """
    token = os.environ.get("GANDI_TOKEN", "REDACTED")
    c = GandiClient(
        base_url="https://api.gandi.net",
        token=token,
        sharing_id=None,
        timeout=10,
        max_retries=1,
    )
    try:
        yield c
    finally:
        await c.close()


@pytest.fixture(autouse=True)
def _ensure_cassette_dir_exists() -> None:
    """Make the cassette dir exist so a clean checkout doesn't error on first replay."""
    Path(_DEFAULT_CASSETTE_DIR).mkdir(parents=True, exist_ok=True)
