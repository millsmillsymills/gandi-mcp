"""Pipeline smoke test for the contract tier.

This is the only test in PR A. Its job is to prove the record + replay pipeline
works end-to-end before PR B starts recording the full API surface.

The cassette ``tests/contract/cassettes/test_user_info_smoke.yaml`` must be
recorded locally before merge via ``make refresh-cassettes``. Until it exists,
this test is skipped in CI (replay-only) — the maintainer records once and the
skipif drops.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from gandi_mcp.clients.gandi import GandiClient

pytestmark = pytest.mark.contract

_CASSETTE = Path(__file__).parent / "cassettes" / "test_user_info_smoke.yaml"


@pytest.mark.skipif(not _CASSETTE.exists(), reason="smoke cassette not yet recorded (maintainer Task 10)")
@pytest.mark.vcr
async def test_user_info_smoke(client: GandiClient) -> None:
    """A bare round-trip against /v5/organization/user-info.

    Asserts only the *shape* of the response, not specific identifiers:
    Gandi may rotate UUIDs, change customer-id formatting, etc., and the
    redactor scrubs ``customer.id``/``owner.id`` anyway. Shape-level
    assertions are the contract.
    """
    info = await client.get_user_info()
    assert isinstance(info, dict)
    assert "username" in info
    assert isinstance(info["username"], str)
    assert info["username"]
