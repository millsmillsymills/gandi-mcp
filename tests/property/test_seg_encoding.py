"""Property tests for path-segment encoding in the Gandi v5 client.

``_seg()`` uses ``urllib.parse.quote(value, safe="")`` to encode every
reserved character — including ``/`` and ``?`` — so an attacker-controlled
DNS record name or mailbox ID cannot shift into a different API path or
query. These tests pin that contract under arbitrary unicode input.
"""

from __future__ import annotations

from urllib.parse import unquote

from hypothesis import given
from hypothesis import strategies as st

from gandi_mcp.clients.gandi import _seg


@given(value=st.text())
def test_seg_round_trips_through_unquote(value: str) -> None:
    """For any input string, ``unquote(_seg(value)) == value``."""
    assert unquote(_seg(value)) == value


@given(value=st.text(alphabet=st.characters(blacklist_categories=("Cs",))))
def test_seg_output_contains_no_path_or_query_separators(value: str) -> None:
    """The encoded segment must not contain ``/``, ``?``, or ``#``.

    These three characters would otherwise allow a malicious caller to
    pivot from one path component into another path or into the query
    string. ``quote(safe="")`` should percent-encode each one.
    """
    encoded = _seg(value)
    assert "/" not in encoded
    assert "?" not in encoded
    assert "#" not in encoded


@given(value=st.text(min_size=1))
def test_seg_is_idempotent_when_input_is_already_safe(value: str) -> None:
    """If the value is already a percent-encoded segment, encoding it
    again is a no-op modulo case-normalisation of hex digits.

    This is the practical invariant agent code relies on when forwarding
    pre-encoded identifiers (e.g. UUIDs, mailbox slot IDs)."""
    once = _seg(value)
    twice = _seg(unquote(once))
    assert once == twice
