"""Unit tests for scripts/cassette_drift.py — pure functions."""

from __future__ import annotations

from scripts.cassette_drift import extract_shape, merge_list_shape


class TestExtractShape:
    def test_string_scalar(self) -> None:
        assert extract_shape("hello") == "str"

    def test_int_scalar(self) -> None:
        assert extract_shape(42) == "int"

    def test_float_scalar(self) -> None:
        assert extract_shape(1.5) == "float"

    def test_bool_scalar(self) -> None:
        # bool must be reported as "bool", not "int" (despite Python's bool <: int).
        assert extract_shape(True) == "bool"
        assert extract_shape(False) == "bool"

    def test_null_scalar(self) -> None:
        assert extract_shape(None) == "null"

    def test_flat_dict(self) -> None:
        shape = extract_shape({"name": "x", "count": 1})
        assert shape == frozenset({("count", "int"), ("name", "str")})

    def test_nested_dict(self) -> None:
        shape = extract_shape({"outer": {"inner": "x"}})
        assert shape == frozenset({("outer", frozenset({("inner", "str")}))})

    def test_empty_list(self) -> None:
        assert extract_shape([]) == ("list", 0, 0, None)

    def test_list_homogeneous_scalars(self) -> None:
        assert extract_shape(["a", "b", "c"]) == ("list", 3, 3, "str")

    def test_list_of_dicts(self) -> None:
        shape = extract_shape([{"id": "x"}, {"id": "y"}])
        assert shape == ("list", 2, 2, frozenset({("id", "str")}))

    def test_no_value_survives_extraction(self) -> None:
        # Walk the shape and assert no original value (the literal "hello" or 42) is present.
        shape = extract_shape({"name": "hello", "count": 42, "tags": ["a", "b"]})
        flat = repr(shape)
        assert "hello" not in flat
        assert "42" not in flat
        assert "'a'" not in flat


class TestMergeListShape:
    def test_empty_input(self) -> None:
        assert merge_list_shape([]) == ("list", 0, 0, None)

    def test_single_type_list(self) -> None:
        assert merge_list_shape(["str", "str", "str"]) == ("list", 3, 3, "str")

    def test_mixed_scalar_types_become_union(self) -> None:
        result = merge_list_shape(["str", "int", "str"])
        assert result == ("list", 3, 3, ("union", frozenset({"str", "int"})))

    def test_mixed_dict_shapes_become_union(self) -> None:
        a = frozenset({("id", "str")})
        b = frozenset({("id", "str"), ("name", "str")})
        result = merge_list_shape([a, b])
        assert result == ("list", 2, 2, ("union", frozenset({a, b})))

    def test_cardinality_bounds_reflect_input(self) -> None:
        # Input is the list-of-shapes that extract_shape has already turned into shapes;
        # bounds equal (min, max) of input list length. For a freshly-walked list
        # both are len(items); the (min<max) case only arises after later
        # diff-side merging — for now both equal len(items).
        result = merge_list_shape(["str"] * 5)
        assert result == ("list", 5, 5, "str")
