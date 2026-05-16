"""Structural drift detector for VCR cassettes.

Compares response shapes between two cassette directories (typically the
committed ``tests/contract/cassettes/`` and a freshly-recorded
``tests/contract/cassettes.new/``). Emits ``+/-/~/!`` entries for keys
added/removed, types changed, and list cardinality bounds changed.

Run via ``make check-drift`` after PR #100 lands. See
``docs/superpowers/specs/2026-05-15-cassette-drift-detection-design.md``.
"""

from __future__ import annotations

from typing import Any

# A "shape" is one of:
#   - a string scalar tag: "str" / "int" / "float" / "bool" / "null"
#   - a frozenset of (key, child_shape) pairs (dict)
#   - a tuple ("list", min_len, max_len, item_shape)
#   - a tuple ("union", frozenset_of_member_shapes)
# Shapes are hashable so frozensets can hold them.
Shape = Any


def extract_shape(value: Any) -> Shape:  # noqa: PLR0911 — one return per JSON type tag; flatter than dispatch dict
    """Walk ``value`` and return its normalized shape, discarding all values."""
    # bool must be checked before int because bool is a subclass of int in Python.
    if isinstance(value, bool):
        return "bool"
    if value is None:
        return "null"
    if isinstance(value, str):
        return "str"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, dict):
        return frozenset((k, extract_shape(v)) for k, v in value.items())
    if isinstance(value, list):
        return merge_list_shape([extract_shape(item) for item in value])
    # Bytes / unknown types fall through to a tag we can compare on.
    return type(value).__name__


def merge_list_shape(items: list[Shape]) -> Shape:
    """Fold a list of item shapes into ``("list", min, max, item_shape)``.

    Mixed item shapes collapse into ``("union", frozenset)``.
    """
    n = len(items)
    if n == 0:
        return ("list", 0, 0, None)
    distinct = frozenset(items)
    if len(distinct) == 1:
        return ("list", n, n, next(iter(distinct)))
    return ("list", n, n, ("union", distinct))
