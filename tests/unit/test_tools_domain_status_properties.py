"""Property tests for ``gandi_mcp.tools.domain._status_view`` (closes #34).

Invariant: regardless of what the Gandi API returns (or omits) under the
``status`` key of a domain record, ``_status_view`` always returns the same
five keys with sensible types. The agent calling ``gandi_domain_get_status``
must never see a missing key or a flag flipped to ``True`` when the
corresponding EPP flag is absent.
"""

from __future__ import annotations

from typing import Any

from hypothesis import example, given
from hypothesis import strategies as st

from gandi_mcp.tools.domain import _status_view

EPP_STATUSES = [
    "clientTransferProhibited",
    "clientUpdateProhibited",
    "clientDeleteProhibited",
    "clientHold",
    "clientRenewProhibited",
    "serverTransferProhibited",
    "serverUpdateProhibited",
    "serverDeleteProhibited",
    "ok",
    "inactive",
    "pendingDelete",
]

EXPECTED_KEYS = frozenset({"fqdn", "status", "transferLocked", "updateLocked", "deleteLocked"})


@st.composite
def epp_status_lists(draw: st.DrawFn) -> list[str]:
    """Generate plausible EPP-status lists, occasionally including unknown flags."""
    known = draw(st.lists(st.sampled_from(EPP_STATUSES), max_size=8, unique=True))
    extras = draw(st.lists(st.text(min_size=1, max_size=10), max_size=2))
    return known + extras


@given(status_list=epp_status_lists(), fqdn=st.text(min_size=1, max_size=64))
@example(status_list=[], fqdn="example.com")
@example(status_list=["clientTransferProhibited"], fqdn="example.com")
@example(status_list=["unknownFlag"], fqdn="example.com")
def test_status_view_always_returns_canonical_keys(status_list: list[str], fqdn: str) -> None:
    """The four documented keys plus ``fqdn`` are always present."""
    domain: dict[str, Any] = {"fqdn": fqdn, "status": status_list}
    view = _status_view(domain, fqdn)
    assert set(view.keys()) == EXPECTED_KEYS


@given(status_list=epp_status_lists(), fqdn=st.text(min_size=1, max_size=64))
def test_status_view_lock_flags_track_input(status_list: list[str], fqdn: str) -> None:
    """Each lock boolean is True iff the matching EPP flag is in the list."""
    domain: dict[str, Any] = {"fqdn": fqdn, "status": status_list}
    view = _status_view(domain, fqdn)
    assert view["transferLocked"] is ("clientTransferProhibited" in status_list)
    assert view["updateLocked"] is ("clientUpdateProhibited" in status_list)
    assert view["deleteLocked"] is ("clientDeleteProhibited" in status_list)


@given(fqdn=st.text(min_size=1, max_size=64))
@example(fqdn="example.com")
def test_status_view_tolerates_missing_status_key(fqdn: str) -> None:
    """A response that omits ``status`` entirely must not crash — treat as empty."""
    domain: dict[str, Any] = {"fqdn": fqdn}
    view = _status_view(domain, fqdn)
    assert view["status"] == []
    assert view["transferLocked"] is False
    assert view["updateLocked"] is False
    assert view["deleteLocked"] is False


@given(fqdn=st.text(min_size=1, max_size=64))
def test_status_view_tolerates_null_status(fqdn: str) -> None:
    """``status: null`` from the API is normalised to ``[]`` (not a crash)."""
    domain: dict[str, Any] = {"fqdn": fqdn, "status": None}
    view = _status_view(domain, fqdn)
    assert view["status"] == []


@given(passed_fqdn=st.text(min_size=1, max_size=64), api_fqdn=st.text(min_size=1, max_size=64))
def test_status_view_prefers_api_fqdn_when_present(passed_fqdn: str, api_fqdn: str) -> None:
    """When the API echoes a ``fqdn``, the view uses it (covers canonicalisation)."""
    domain: dict[str, Any] = {"fqdn": api_fqdn, "status": []}
    assert _status_view(domain, passed_fqdn)["fqdn"] == api_fqdn


@given(passed_fqdn=st.text(min_size=1, max_size=64))
def test_status_view_falls_back_to_passed_fqdn(passed_fqdn: str) -> None:
    """When the API omits ``fqdn``, the view uses the value the tool passed in."""
    domain: dict[str, Any] = {"status": []}
    assert _status_view(domain, passed_fqdn)["fqdn"] == passed_fqdn
