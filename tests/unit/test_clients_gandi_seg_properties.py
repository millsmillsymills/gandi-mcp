"""Property tests for ``gandi_mcp.clients.gandi._seg`` (closes #34).

Invariant: ``_seg(s)`` produces a URL path segment that cannot shift into a
different API path or query for ANY string input. The encoded output must
exclude every character that has structural meaning in a URL — slashes,
question marks, hashes, ampersands, equals signs, control characters, raw
spaces, etc. Path traversal (``../``) must encode rather than escape.

These properties guard the safety invariant documented in ``CLAUDE.md``:
"Path segments are percent-encoded via ``_seg()``. Raw interpolation into URL
paths is a regression — the helper is there to prevent ``/`` or ``?`` in a
DNS record name from shifting into a different API path."
"""

from __future__ import annotations

from urllib.parse import unquote

from hypothesis import example, given
from hypothesis import strategies as st

from gandi_mcp.clients.gandi import _seg

# RFC 3986 unreserved set + the percent-encoding introducer.
SAFE_OUTPUT_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~%")
CONTROL_CHARS = frozenset(chr(c) for c in range(32)) | {chr(127)}


@given(value=st.text())
@example(value="../../../etc/passwd")
@example(value="example.com")
@example(value="record/with/slash")
@example(value="a?b")
@example(value="a#b")
@example(value="a&b=c")
@example(value="")
@example(value="\x00")
@example(value="\n")
@example(value="space here")
@example(value="résumé.fr")
@example(value="日本.jp")
def test_seg_output_only_contains_safe_chars(value: str) -> None:
    """The encoded segment contains only RFC-3986 unreserved chars plus ``%``.

    Anything outside that set — slashes, queries, ampersands, control chars,
    unicode — must be percent-encoded.
    """
    encoded = _seg(value)
    bad = [ch for ch in encoded if ch not in SAFE_OUTPUT_CHARS]
    assert not bad, f"unsafe chars {bad!r} survived in _seg({value!r}) = {encoded!r}"


@given(value=st.text())
@example(value="\x00\x01\x1f")
@example(value="\n\r\t")
def test_seg_output_has_no_control_chars(value: str) -> None:
    """Control characters (including NUL, newline, CR, tab, DEL) must be encoded."""
    encoded = _seg(value)
    for ch in encoded:
        assert ch not in CONTROL_CHARS, f"control char {ord(ch):#04x} survived in _seg({value!r}) = {encoded!r}"


@given(value=st.text(alphabet=st.characters(min_codepoint=0, max_codepoint=0x10FFFF, blacklist_categories=("Cs",))))
def test_seg_output_is_ascii(value: str) -> None:
    """Encoded segments are pure ASCII — unicode must be percent-encoded.

    Lone surrogates (``Cs`` category) are excluded: ``urllib.parse.quote``
    re-encodes the string as UTF-8 first, and a lone surrogate raises
    ``UnicodeEncodeError``. Real MCP path segments are valid Python strings
    (no lone surrogates), so this property targets the well-formed-input
    contract. See follow-up for the surrogate edge case.
    """
    encoded = _seg(value)
    assert encoded.isascii(), f"non-ASCII survived in _seg({value!r}) = {encoded!r}"


@given(value=st.text())
@example(value="/")
@example(value="?")
@example(value="#")
@example(value="example.com/leak")
def test_seg_is_roundtrippable(value: str) -> None:
    """``unquote(_seg(x)) == x`` — encoding is lossless so the server still sees the intended value."""
    encoded = _seg(value)
    assert unquote(encoded) == value


@given(value=st.text(min_size=1))
def test_seg_output_is_never_just_slash(value: str) -> None:
    """No input may produce a bare ``/`` that would collapse the URL.

    The hand-picked examples cover slashes, but the property over arbitrary
    text ensures a future change to ``quote()``'s ``safe`` arg can't slip in.
    """
    assert _seg(value) != "/"
    assert "/" not in _seg(value)
