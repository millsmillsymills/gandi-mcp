"""Unit tests for scripts/cassette_drift.py — pure functions."""

from __future__ import annotations

from scripts.cassette_drift import DriftEntry, diff_shapes, extract_shape, merge_list_shape, render_report


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


class TestDiffShapes:
    def test_identical_shapes_no_drift(self) -> None:
        a = frozenset({("foo", "str")})
        assert diff_shapes(a, a) == []

    def test_added_key(self) -> None:
        old = frozenset({("foo", "str")})
        new = frozenset({("foo", "str"), ("bar", "int")})
        entries = diff_shapes(old, new)
        assert entries == [DriftEntry(kind="added", path=".bar", old=None, new="int")]

    def test_removed_key(self) -> None:
        old = frozenset({("foo", "str"), ("bar", "int")})
        new = frozenset({("foo", "str")})
        entries = diff_shapes(old, new)
        assert entries == [DriftEntry(kind="removed", path=".bar", old="int", new=None)]

    def test_type_changed_scalar(self) -> None:
        old = frozenset({("foo", "int")})
        new = frozenset({("foo", "str")})
        entries = diff_shapes(old, new)
        assert entries == [DriftEntry(kind="type_changed", path=".foo", old="int", new="str")]

    def test_cardinality_widened(self) -> None:
        old = ("list", 3, 3, "str")
        new = ("list", 0, 50, "str")
        entries = diff_shapes(old, new)
        assert entries == [
            DriftEntry(kind="cardinality_changed", path="", old="3..3", new="0..50"),
        ]

    def test_nested_dict_added(self) -> None:
        old = frozenset({("outer", frozenset({("a", "str")}))})
        new = frozenset({("outer", frozenset({("a", "str"), ("b", "int")}))})
        entries = diff_shapes(old, new)
        assert entries == [DriftEntry(kind="added", path=".outer.b", old=None, new="int")]

    def test_list_item_type_change(self) -> None:
        old = ("list", 2, 2, "str")
        new = ("list", 2, 2, "int")
        entries = diff_shapes(old, new)
        assert entries == [DriftEntry(kind="type_changed", path="[]", old="str", new="int")]

    def test_union_member_added(self) -> None:
        old = ("union", frozenset({"str"}))
        new = ("union", frozenset({"str", "int"}))
        entries = diff_shapes(old, new)
        assert entries == [DriftEntry(kind="union_changed", path="", old="{str}", new="{int, str}")]

    def test_union_member_removed(self) -> None:
        old = ("union", frozenset({"str", "int"}))
        new = ("union", frozenset({"str"}))
        entries = diff_shapes(old, new)
        assert entries == [DriftEntry(kind="union_changed", path="", old="{int, str}", new="{str}")]

    def test_jq_path_deeply_nested(self) -> None:
        old = frozenset({("a", frozenset({("b", frozenset({("c", "str")}))}))})
        new = frozenset({("a", frozenset({("b", frozenset({("c", "int")}))}))})
        entries = diff_shapes(old, new)
        assert entries == [DriftEntry(kind="type_changed", path=".a.b.c", old="str", new="int")]

    def test_entries_sorted_by_path_for_determinism(self) -> None:
        old = frozenset({("a", "str"), ("z", "str")})
        new = frozenset({("a", "int"), ("z", "int")})
        entries = diff_shapes(old, new)
        # Determinism: paths must come out in sorted order regardless of frozenset iteration.
        assert [e.path for e in entries] == [".a", ".z"]


class TestRenderReport:
    def test_empty_entries_returns_empty_string(self) -> None:
        assert render_report("cassette.yaml", [], fmt="text") == ""

    def test_added_entry_text_format(self) -> None:
        entries = [DriftEntry("added", ".foo.bar", None, "str")]
        report = render_report("cassette.yaml", entries, fmt="text")
        assert "cassette.yaml" in report
        assert "+ added .foo.bar (str)" in report

    def test_removed_entry_text_format(self) -> None:
        entries = [DriftEntry("removed", ".foo.bar", "str", None)]
        report = render_report("cassette.yaml", entries, fmt="text")
        assert "- removed .foo.bar (str)" in report

    def test_type_changed_entry_text_format(self) -> None:
        entries = [DriftEntry("type_changed", ".foo", "int", "str")]
        report = render_report("cassette.yaml", entries, fmt="text")
        assert "~ .foo: int → str" in report

    def test_cardinality_changed_entry_text_format(self) -> None:
        entries = [DriftEntry("cardinality_changed", ".items", "0..3", "0..50")]
        report = render_report("cassette.yaml", entries, fmt="text")
        assert "! list .items: 0..3 → 0..50" in report

    def test_union_changed_entry_text_format(self) -> None:
        entries = [DriftEntry("union_changed", ".x", "{str}", "{int, str}")]
        report = render_report("cassette.yaml", entries, fmt="text")
        assert "~ union .x: {str} → {int, str}" in report

    def test_markdown_format_has_fenced_block_and_heading(self) -> None:
        entries = [DriftEntry("added", ".foo", None, "str")]
        report = render_report("cassette.yaml", entries, fmt="md")
        assert "## cassette.yaml" in report
        assert "```" in report
        assert "+ added .foo (str)" in report

    def test_report_is_deterministic_sorted_by_path(self) -> None:
        # Pre-shuffled input — render must sort by path so output is reproducible.
        entries = [
            DriftEntry("added", ".z", None, "str"),
            DriftEntry("added", ".a", None, "str"),
            DriftEntry("added", ".m", None, "str"),
        ]
        report = render_report("cassette.yaml", entries, fmt="text")
        idx_a = report.index(".a")
        idx_m = report.index(".m")
        idx_z = report.index(".z")
        assert idx_a < idx_m < idx_z
