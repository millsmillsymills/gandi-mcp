# Cassette Drift Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `scripts/cassette_drift.py` + `make check-drift` + a dormant `workflow_dispatch` CI workflow that re-records contract cassettes against live Gandi, structurally diffs the new responses against the committed cassettes, and opens (or appends to) a `drift`-labeled GitHub issue when shape changes are detected.

**Architecture:** Single-file Python CLI under `scripts/` invoked from a new `Makefile` target. CLI parses VCR YAML, extracts per-response shape (keys, types, list cardinality bounds; values discarded), diffs old vs. new, renders a human-readable report, optionally creates/appends a GitHub issue via `gh` subprocess. Tests are pure unit + offline CLI integration — no live network, no real `gh` API calls.

**Tech Stack:** Python 3.13, `pyyaml` (already a transitive dep via vcrpy), pytest, ruff, ty, `gh` CLI (already used elsewhere in the project), `subprocess` (stdlib).

**Spec:** `docs/superpowers/specs/2026-05-15-cassette-drift-detection-design.md`

**Hard dependency:** PR #100 (contract scaffold) MUST be merged before this plan starts. It contributes `tests/contract/`, `Makefile`, `cassettes.new/` staging dir, and the redactor — Tasks 11 and 13 depend on the Makefile existing and the redactor running pre-disk.

---

## File Structure

| Path | Status | Responsibility |
|---|---|---|
| `scripts/__init__.py` | Create | Empty package marker so tests can `from scripts.cassette_drift import ...`. |
| `scripts/cassette_drift.py` | Create | Single-file CLI: argparse + 6 pure functions + `main()`. Outputs to stdout/stderr via `sys.stdout.write` / `sys.stderr.write` (the project's convention; T201 disallows `print()`). |
| `tests/unit/test_cassette_drift.py` | Create | Unit tests for the 6 pure functions. No subprocess, no filesystem beyond `tmp_path`. |
| `tests/unit/test_cassette_drift_cli.py` | Create | End-to-end CLI tests via `subprocess.run` against the script. Uses two `tmp_path` cassette dirs and a PATH-shadowed `gh` stub. |
| `Makefile` | Modify | Add `check-drift` target. Conditionally pass `--open-issue` based on `$(CASSETTE_DRIFT_OPEN_ISSUE)`. |
| `.github/workflows/drift-check.yml` | Create | `workflow_dispatch`-only. No cron. Required secret `GANDI_SANDBOX_PAT`, required label `drift`. `permissions: { contents: read, issues: write }`. `concurrency: { group: drift-check, cancel-in-progress: false }`. |
| `CONTRIBUTING.md` | Modify | Append a "Detecting cassette drift" section under the existing "Recording contract cassettes" section. |

The drift script and the workflow are decoupled: the script knows nothing about CI; the workflow knows nothing about the script's internals beyond `make check-drift CASSETTE_DRIFT_OPEN_ISSUE=1`.

---

## Task 1 — Bootstrap scripts as a Python package

**Files:**
- Create: `scripts/__init__.py`
- Modify: none

The existing `scripts/check_coverage_thresholds.py` is invoked as a top-level script and never imported. Drift logic is the same script-style invocation but ALSO needs to be importable from `tests/unit/`. Adding an empty `__init__.py` makes `from scripts.cassette_drift import extract_shape` work without sys.path tricks.

- [ ] **Step 1: Create the package marker**

Write `scripts/__init__.py` with empty content (zero bytes — matches `tests/integration/__init__.py`).

- [ ] **Step 2: Confirm the import resolves**

Run: `uv run python -c "import scripts; print(scripts.__file__)"`
Expected: prints the absolute path to `scripts/__init__.py`. No errors.

- [ ] **Step 3: Verify check_coverage_thresholds.py still works as a script**

Run: `uv run python scripts/check_coverage_thresholds.py 2>&1 | head -3`
Expected: prints `ERROR: coverage.json not found.` and exits 2 (or 1 — either is fine; the point is the script still runs).

- [ ] **Step 4: Commit**

```bash
git add scripts/__init__.py
git commit -m "chore: make scripts/ an importable package"
```

---

## Task 2 — TDD `extract_shape` and `merge_list_shape` (pure shape extraction)

**Files:**
- Create: `tests/unit/test_cassette_drift.py` (first section)
- Create: `scripts/cassette_drift.py` (skeleton with shape extraction)

The two functions are tightly coupled — `extract_shape` calls `merge_list_shape` for list inputs. Build them together.

Shape representation (frozen, hashable):
- Scalar → string: `"str"`, `"int"`, `"float"`, `"bool"`, `"null"`.
- `dict` → `frozenset` of `(key, child_shape)` pairs.
- `list` → tuple: `("list", min_len, max_len, item_shape)`.
- Mixed list-item types → `("union", frozenset_of_member_shapes)`.

- [ ] **Step 1: Write the failing tests**

Write `tests/unit/test_cassette_drift.py`:

```python
"""Unit tests for scripts/cassette_drift.py — pure functions."""

from __future__ import annotations

import pytest

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
```

- [ ] **Step 2: Run the tests, confirm they fail**

Run: `uv run pytest tests/unit/test_cassette_drift.py -v`
Expected: `ModuleNotFoundError: No module named 'scripts.cassette_drift'` on collection.

- [ ] **Step 3: Write the minimal implementation**

Write `scripts/cassette_drift.py`:

```python
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


def extract_shape(value: Any) -> Shape:
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
```

- [ ] **Step 4: Run the tests, confirm they pass**

Run: `uv run pytest tests/unit/test_cassette_drift.py -v`
Expected: 16 passed (11 in `TestExtractShape` + 5 in `TestMergeListShape`).

- [ ] **Step 5: Lint and format**

Run: `uv run ruff check scripts/cassette_drift.py tests/unit/test_cassette_drift.py && uv run ruff format --check scripts/cassette_drift.py tests/unit/test_cassette_drift.py`
Expected: `All checks passed!` and `2 files already formatted` (or run `uv run ruff format` to fix).

- [ ] **Step 6: Commit**

```bash
git add scripts/cassette_drift.py tests/unit/test_cassette_drift.py
git commit -m "feat(scripts): cassette_drift shape extraction (extract_shape + merge_list_shape)"
```

---

## Task 3 — TDD `diff_shapes`

**Files:**
- Modify: `tests/unit/test_cassette_drift.py` (append)
- Modify: `scripts/cassette_drift.py` (append)

`diff_shapes` walks two shapes recursively and returns a list of `DriftEntry` records describing the differences at jq-path locations.

`DriftEntry` is a small dataclass:

```python
@dataclass(frozen=True)
class DriftEntry:
    kind: str        # "added" | "removed" | "type_changed" | "cardinality_changed" | "union_changed"
    path: str        # jq-path: "" for root, ".foo.bar", ".items[]"
    old: str | None  # human-readable old representation, or None for "added"
    new: str | None  # human-readable new representation, or None for "removed"
```

- [ ] **Step 1: Append the failing tests**

Append to `tests/unit/test_cassette_drift.py`:

```python
from scripts.cassette_drift import DriftEntry, diff_shapes


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
```

- [ ] **Step 2: Run the tests, confirm they fail**

Run: `uv run pytest tests/unit/test_cassette_drift.py::TestDiffShapes -v`
Expected: `ImportError: cannot import name 'DriftEntry' from 'scripts.cassette_drift'`.

- [ ] **Step 3: Append the implementation**

Append to `scripts/cassette_drift.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class DriftEntry:
    kind: str
    path: str
    old: str | None
    new: str | None


def _render_shape(shape: Shape) -> str:
    """Compact human-readable rendering for diff messages."""
    if isinstance(shape, str):
        return shape
    if isinstance(shape, frozenset):
        # dict shape — render keyset for brevity
        keys = sorted(k for k, _ in shape)
        return "{" + ", ".join(keys) + "}"
    if isinstance(shape, tuple):
        tag = shape[0]
        if tag == "list":
            _, lo, hi, item = shape
            return f"list[{_render_shape(item) if item is not None else 'empty'}]({lo}..{hi})"
        if tag == "union":
            members = sorted(_render_shape(m) for m in shape[1])
            return "{" + ", ".join(members) + "}"
    return repr(shape)


def diff_shapes(old: Shape, new: Shape, path: str = "") -> list[DriftEntry]:
    """Walk two shapes and return drift entries sorted by jq-path for determinism."""
    entries: list[DriftEntry] = []

    if isinstance(old, frozenset) and isinstance(new, frozenset):
        old_keys = {k: v for k, v in old}
        new_keys = {k: v for k, v in new}
        for k in sorted(set(old_keys) | set(new_keys)):
            child_path = f"{path}.{k}"
            if k not in old_keys:
                entries.append(DriftEntry("added", child_path, None, _render_shape(new_keys[k])))
            elif k not in new_keys:
                entries.append(DriftEntry("removed", child_path, _render_shape(old_keys[k]), None))
            else:
                entries.extend(diff_shapes(old_keys[k], new_keys[k], child_path))
        return entries

    if isinstance(old, tuple) and isinstance(new, tuple) and old[0] == new[0] == "list":
        _, o_lo, o_hi, o_item = old
        _, n_lo, n_hi, n_item = new
        if (o_lo, o_hi) != (n_lo, n_hi):
            entries.append(
                DriftEntry("cardinality_changed", path, f"{o_lo}..{o_hi}", f"{n_lo}..{n_hi}")
            )
        if o_item is not None and n_item is not None:
            entries.extend(diff_shapes(o_item, n_item, f"{path}[]"))
        elif o_item != n_item:
            entries.append(
                DriftEntry(
                    "type_changed",
                    f"{path}[]",
                    _render_shape(o_item) if o_item is not None else "empty",
                    _render_shape(n_item) if n_item is not None else "empty",
                )
            )
        return entries

    if isinstance(old, tuple) and isinstance(new, tuple) and old[0] == new[0] == "union":
        if old[1] != new[1]:
            entries.append(
                DriftEntry("union_changed", path, _render_shape(old), _render_shape(new))
            )
        return entries

    if old != new:
        entries.append(
            DriftEntry("type_changed", path, _render_shape(old), _render_shape(new))
        )
    return entries
```

- [ ] **Step 4: Run the tests, confirm they pass**

Run: `uv run pytest tests/unit/test_cassette_drift.py::TestDiffShapes -v`
Expected: 11 passed.

- [ ] **Step 5: Lint and format**

Run: `uv run ruff check scripts/cassette_drift.py tests/unit/test_cassette_drift.py && uv run ruff format --check scripts/cassette_drift.py tests/unit/test_cassette_drift.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add scripts/cassette_drift.py tests/unit/test_cassette_drift.py
git commit -m "feat(scripts): cassette_drift diff_shapes + DriftEntry"
```

---

## Task 4 — TDD `render_report` (text + markdown formats)

**Files:**
- Modify: `tests/unit/test_cassette_drift.py` (append)
- Modify: `scripts/cassette_drift.py` (append)

Reports are produced per-cassette and concatenated. Test the per-cassette renderer.

- [ ] **Step 1: Append the failing tests**

Append to `tests/unit/test_cassette_drift.py`:

```python
from scripts.cassette_drift import render_report


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
```

- [ ] **Step 2: Run the tests, confirm they fail**

Run: `uv run pytest tests/unit/test_cassette_drift.py::TestRenderReport -v`
Expected: `ImportError: cannot import name 'render_report'`.

- [ ] **Step 3: Append the implementation**

Append to `scripts/cassette_drift.py`:

```python
_RENDERERS = {
    "added": lambda e: f"+ added {e.path} ({e.new})",
    "removed": lambda e: f"- removed {e.path} ({e.old})",
    "type_changed": lambda e: f"~ {e.path}: {e.old} → {e.new}",
    "cardinality_changed": lambda e: f"! list {e.path}: {e.old} → {e.new}",
    "union_changed": lambda e: f"~ union {e.path}: {e.old} → {e.new}",
}


def render_report(cassette_path: str, entries: list[DriftEntry], fmt: str = "text") -> str:
    """Render a per-cassette drift report. Empty entries → empty string."""
    if not entries:
        return ""
    sorted_entries = sorted(entries, key=lambda e: (e.path, e.kind))
    lines = [_RENDERERS[e.kind](e) for e in sorted_entries]
    if fmt == "md":
        return f"## {cassette_path}\n\n```\n" + "\n".join(lines) + "\n```\n"
    return f"{cassette_path}:\n" + "\n".join(f"  {line}" for line in lines) + "\n"
```

- [ ] **Step 4: Run the tests, confirm they pass**

Run: `uv run pytest tests/unit/test_cassette_drift.py::TestRenderReport -v`
Expected: 8 passed.

- [ ] **Step 5: Lint and format**

Run: `uv run ruff check scripts/cassette_drift.py tests/unit/test_cassette_drift.py && uv run ruff format --check scripts/cassette_drift.py tests/unit/test_cassette_drift.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add scripts/cassette_drift.py tests/unit/test_cassette_drift.py
git commit -m "feat(scripts): cassette_drift render_report (text + md)"
```

---

## Task 5 — TDD `load_cassette` (VCR YAML parsing)

**Files:**
- Modify: `tests/unit/test_cassette_drift.py` (append)
- Modify: `scripts/cassette_drift.py` (append)

`load_cassette` parses a VCR YAML file and returns a list of `(request, response_body_or_None, occurrence_index)` triples.

VCR cassette structure (relevant subset):

```yaml
interactions:
- request:
    method: GET
    uri: https://api.gandi.net/v5/organization/user-info
    body: null
  response:
    status:
      code: 200
    body:
      string: '{"username": "alice"}'
- request:
    method: POST
    uri: https://api.gandi.net/v5/...
    body: '{"key": "value"}'
  response:
    status:
      code: 204
    body:
      string: ''
```

Body is non-JSON / missing / non-2xx → `None`. Malformed YAML or missing top-level `interactions` → `CassetteParseError`.

- [ ] **Step 1: Append the failing tests**

Append to `tests/unit/test_cassette_drift.py`:

```python
import hashlib

from scripts.cassette_drift import CassetteParseError, load_cassette


def _write_cassette(tmp_path, name: str, interactions: list[dict]) -> str:
    import yaml

    path = tmp_path / name
    path.write_text(yaml.safe_dump({"interactions": interactions}))
    return str(path)


class TestLoadCassette:
    def test_well_formed_json_body(self, tmp_path) -> None:
        p = _write_cassette(
            tmp_path,
            "ok.yaml",
            [
                {
                    "request": {"method": "GET", "uri": "https://api.gandi.net/v5/x", "body": None},
                    "response": {"status": {"code": 200}, "body": {"string": '{"a": 1}'}},
                },
            ],
        )
        triples = load_cassette(p)
        assert len(triples) == 1
        req, body, occ = triples[0]
        assert req["method"] == "GET"
        assert body == {"a": 1}
        assert occ == 0

    def test_binary_body_returns_none(self, tmp_path) -> None:
        # Body that doesn't parse as JSON (e.g. HTML or binary).
        p = _write_cassette(
            tmp_path,
            "html.yaml",
            [
                {
                    "request": {"method": "GET", "uri": "https://x", "body": None},
                    "response": {"status": {"code": 200}, "body": {"string": "<html>not json</html>"}},
                },
            ],
        )
        assert load_cassette(p)[0][1] is None

    def test_missing_body_string_returns_none(self, tmp_path) -> None:
        p = _write_cassette(
            tmp_path,
            "nobody.yaml",
            [
                {
                    "request": {"method": "GET", "uri": "https://x", "body": None},
                    "response": {"status": {"code": 204}, "body": {}},
                },
            ],
        )
        assert load_cassette(p)[0][1] is None

    def test_non_2xx_response_returns_none(self, tmp_path) -> None:
        # Even if the body is valid JSON, a non-2xx response is excluded from drift.
        p = _write_cassette(
            tmp_path,
            "err.yaml",
            [
                {
                    "request": {"method": "GET", "uri": "https://x", "body": None},
                    "response": {"status": {"code": 404}, "body": {"string": '{"error": "x"}'}},
                },
            ],
        )
        assert load_cassette(p)[0][1] is None

    def test_malformed_yaml_raises(self, tmp_path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("this is: : not: valid: yaml: ::::: -")
        with pytest.raises(CassetteParseError):
            load_cassette(str(path))

    def test_missing_interactions_raises(self, tmp_path) -> None:
        path = tmp_path / "no-interactions.yaml"
        path.write_text("other_key: value\n")
        with pytest.raises(CassetteParseError):
            load_cassette(str(path))

    def test_occurrence_index_monotonic_per_identical_request(self, tmp_path) -> None:
        body = '{"k": 1}'
        same_req = {"method": "GET", "uri": "https://x/poll", "body": "ping"}
        p = _write_cassette(
            tmp_path,
            "poll.yaml",
            [
                {"request": same_req, "response": {"status": {"code": 200}, "body": {"string": body}}},
                {"request": same_req, "response": {"status": {"code": 200}, "body": {"string": body}}},
                {"request": same_req, "response": {"status": {"code": 200}, "body": {"string": body}}},
            ],
        )
        triples = load_cassette(p)
        assert [t[2] for t in triples] == [0, 1, 2]

    def test_occurrence_index_resets_per_distinct_request(self, tmp_path) -> None:
        a = {"method": "GET", "uri": "https://x/a", "body": None}
        b = {"method": "GET", "uri": "https://x/b", "body": None}
        body = '{"k": 1}'
        p = _write_cassette(
            tmp_path,
            "mixed.yaml",
            [
                {"request": a, "response": {"status": {"code": 200}, "body": {"string": body}}},
                {"request": b, "response": {"status": {"code": 200}, "body": {"string": body}}},
                {"request": a, "response": {"status": {"code": 200}, "body": {"string": body}}},
            ],
        )
        triples = load_cassette(p)
        # Order preserved; occurrence_index is 0,0,1 (a's second appearance is index 1; b's first is 0).
        assert [(t[0]["uri"], t[2]) for t in triples] == [
            ("https://x/a", 0),
            ("https://x/b", 0),
            ("https://x/a", 1),
        ]


def test_request_pairing_helper_exists() -> None:
    # Pairing logic is used by main() — sanity check it's importable.
    from scripts.cassette_drift import pair_interactions  # noqa: F401
```

- [ ] **Step 2: Run the tests, confirm they fail**

Run: `uv run pytest tests/unit/test_cassette_drift.py::TestLoadCassette -v`
Expected: `ImportError: cannot import name 'CassetteParseError'`.

- [ ] **Step 3: Append the implementation**

Append to `scripts/cassette_drift.py`:

```python
import hashlib
import json
import yaml


class CassetteParseError(Exception):
    """Raised when a cassette YAML is malformed or missing required structure."""


def _request_key(req: dict) -> tuple[str, str, str]:
    method = str(req.get("method", ""))
    uri = str(req.get("uri", ""))
    body = req.get("body")
    body_bytes = b"" if body is None else (body.encode("utf-8") if isinstance(body, str) else bytes(body))
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    return (method, uri, body_hash)


def load_cassette(path: str) -> list[tuple[dict, Any, int]]:
    """Parse a VCR cassette into ``(request, body_or_None, occurrence_index)`` triples."""
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise CassetteParseError(f"YAML parse error in {path}: {e}") from e
    if not isinstance(data, dict) or "interactions" not in data:
        raise CassetteParseError(f"missing top-level 'interactions' in {path}")
    interactions = data["interactions"]
    if not isinstance(interactions, list):
        raise CassetteParseError(f"'interactions' in {path} is not a list")

    triples: list[tuple[dict, Any, int]] = []
    counts: dict[tuple[str, str, str], int] = {}
    for interaction in interactions:
        if not isinstance(interaction, dict):
            continue
        request = interaction.get("request") or {}
        response = interaction.get("response") or {}
        status = (response.get("status") or {}).get("code", 0)
        body_field = response.get("body") or {}
        raw = body_field.get("string") if isinstance(body_field, dict) else None
        body: Any
        if not raw or not isinstance(status, int) or not (200 <= status < 300):
            body = None
        else:
            try:
                body = json.loads(raw)
            except (ValueError, TypeError):
                body = None
        key = _request_key(request)
        occ = counts.get(key, 0)
        counts[key] = occ + 1
        triples.append((request, body, occ))
    return triples


def pair_interactions(
    old: list[tuple[dict, Any, int]],
    new: list[tuple[dict, Any, int]],
) -> tuple[list[tuple[tuple[dict, Any, int], tuple[dict, Any, int]]], list, list]:
    """Pair old and new interactions by (method, uri, body-hash, occurrence_index).

    Returns ``(pairs, only_in_old, only_in_new)``.
    """
    old_by_key = {(*_request_key(r), occ): (r, b, occ) for (r, b, occ) in old}
    new_by_key = {(*_request_key(r), occ): (r, b, occ) for (r, b, occ) in new}
    keys_old = set(old_by_key)
    keys_new = set(new_by_key)
    common = keys_old & keys_new
    pairs = [(old_by_key[k], new_by_key[k]) for k in sorted(common)]
    only_in_old = [old_by_key[k] for k in sorted(keys_old - keys_new)]
    only_in_new = [new_by_key[k] for k in sorted(keys_new - keys_old)]
    return pairs, only_in_old, only_in_new
```

- [ ] **Step 4: Run the tests, confirm they pass**

Run: `uv run pytest tests/unit/test_cassette_drift.py::TestLoadCassette -v`
Expected: 8 passed.

Run: `uv run pytest tests/unit/test_cassette_drift.py -v`
Expected: 16 + 5 + 11 + 8 + 8 + 1 = **49 passed**.

- [ ] **Step 5: Lint and format**

Run: `uv run ruff check scripts/cassette_drift.py tests/unit/test_cassette_drift.py && uv run ruff format --check scripts/cassette_drift.py tests/unit/test_cassette_drift.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add scripts/cassette_drift.py tests/unit/test_cassette_drift.py
git commit -m "feat(scripts): cassette_drift load_cassette + pair_interactions"
```

---

## Task 6 — TDD `find_existing_drift_issue` (gh subprocess wrapper)

**Files:**
- Modify: `tests/unit/test_cassette_drift.py` (append)
- Modify: `scripts/cassette_drift.py` (append)

Shells out to `gh issue list --label drift --search "drift:" --state open --json number,title`. Parses the JSON, finds the first issue whose title starts with the prefix, returns its number. Tests use `monkeypatch` to stub `subprocess.run`.

- [ ] **Step 1: Append the failing tests**

Append to `tests/unit/test_cassette_drift.py`:

```python
import json as _json
import subprocess as _subprocess

from scripts.cassette_drift import find_existing_drift_issue


class TestFindExistingDriftIssue:
    def test_no_open_issues_returns_none(self, monkeypatch) -> None:
        def fake_run(*args, **kwargs):
            return _subprocess.CompletedProcess(args=args[0], returncode=0, stdout="[]", stderr="")

        monkeypatch.setattr("scripts.cassette_drift.subprocess.run", fake_run)
        assert find_existing_drift_issue("drift", "drift: ") is None

    def test_finds_matching_issue_by_title_prefix(self, monkeypatch) -> None:
        payload = _json.dumps([{"number": 42, "title": "drift: 3 cassette(s) drifted upstream"}])

        def fake_run(*args, **kwargs):
            return _subprocess.CompletedProcess(args=args[0], returncode=0, stdout=payload, stderr="")

        monkeypatch.setattr("scripts.cassette_drift.subprocess.run", fake_run)
        assert find_existing_drift_issue("drift", "drift: ") == 42

    def test_ignores_issues_with_drift_label_but_different_prefix(self, monkeypatch) -> None:
        payload = _json.dumps([{"number": 99, "title": "regression in drift checker"}])

        def fake_run(*args, **kwargs):
            return _subprocess.CompletedProcess(args=args[0], returncode=0, stdout=payload, stderr="")

        monkeypatch.setattr("scripts.cassette_drift.subprocess.run", fake_run)
        assert find_existing_drift_issue("drift", "drift: ") is None

    def test_gh_failure_returns_none_and_does_not_raise(self, monkeypatch) -> None:
        # If gh fails (auth issue, network, etc.), we surface no existing issue so
        # main() falls through to issue creation; the creation attempt will then
        # produce its own error path.
        def fake_run(*args, **kwargs):
            return _subprocess.CompletedProcess(
                args=args[0], returncode=1, stdout="", stderr="gh: not authenticated"
            )

        monkeypatch.setattr("scripts.cassette_drift.subprocess.run", fake_run)
        assert find_existing_drift_issue("drift", "drift: ") is None
```

- [ ] **Step 2: Run the tests, confirm they fail**

Run: `uv run pytest tests/unit/test_cassette_drift.py::TestFindExistingDriftIssue -v`
Expected: `ImportError: cannot import name 'find_existing_drift_issue'`.

- [ ] **Step 3: Append the implementation**

Append to `scripts/cassette_drift.py`:

```python
import subprocess


def find_existing_drift_issue(label: str, title_prefix: str) -> int | None:
    """Look up an open issue with the given label whose title starts with ``title_prefix``.

    Returns the issue number, or ``None`` on no match or on any ``gh`` failure
    (failure falls through to issue creation in main()).
    """
    result = subprocess.run(
        [
            "gh", "issue", "list",
            "--label", label,
            "--state", "open",
            "--json", "number,title",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        issues = json.loads(result.stdout)
    except (ValueError, TypeError):
        return None
    for issue in issues:
        title = issue.get("title", "")
        if isinstance(title, str) and title.startswith(title_prefix):
            number = issue.get("number")
            if isinstance(number, int):
                return number
    return None
```

- [ ] **Step 4: Run the tests, confirm they pass**

Run: `uv run pytest tests/unit/test_cassette_drift.py::TestFindExistingDriftIssue -v`
Expected: 4 passed.

- [ ] **Step 5: Lint and format**

Run: `uv run ruff check scripts/cassette_drift.py tests/unit/test_cassette_drift.py && uv run ruff format --check scripts/cassette_drift.py tests/unit/test_cassette_drift.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add scripts/cassette_drift.py tests/unit/test_cassette_drift.py
git commit -m "feat(scripts): cassette_drift find_existing_drift_issue"
```

---

## Task 7 — Wire `main()` + argparse + exit codes

**Files:**
- Modify: `scripts/cassette_drift.py` (append)

Glue:

1. argparse with `--cassette-dir-old`, `--cassette-dir-new`, `--report-format`, `--open-issue`.
2. Walk `cassette-dir-old/**/*.yaml`. For each found, locate `cassette-dir-new/<rel>.yaml`.
3. `load_cassette` both, pair, diff each paired (request, response) when both bodies are non-None.
4. Render full report, write to stdout.
5. If `--open-issue` and shape-drift exists: find existing → comment or create.
6. Exit 1 if any shape-drift entries OR every cassette failed to parse; exit 0 otherwise.

CLI test is in Task 8. This task focuses on the implementation; smoke-test by invoking the script as a subprocess.

- [ ] **Step 1: Append the implementation**

Append to `scripts/cassette_drift.py`:

```python
import argparse
import datetime as _dt
import sys
from pathlib import Path


def _walk_cassettes(root: Path) -> list[Path]:
    return sorted(root.glob("**/*.yaml"))


def _report_summary_line(n_cassettes: int) -> str:
    suffix = "s" if n_cassettes != 1 else ""
    return f"drift: {n_cassettes} cassette{suffix} drifted upstream"


def _post_or_append_issue(label: str, title_prefix: str, body: str) -> tuple[bool, str]:
    """Create a new drift issue or append a dated comment to an existing one.

    Returns ``(success, message)``. ``success=False`` indicates ``gh`` failed.
    """
    existing = find_existing_drift_issue(label, title_prefix)
    timestamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if existing is not None:
        commented_body = f"### Drift recurred at {timestamp}\n\n{body}"
        result = subprocess.run(
            ["gh", "issue", "comment", str(existing), "--body-file", "-"],
            input=commented_body,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False, f"append to issue #{existing} failed: {result.stderr.strip()}"
        return True, f"appended comment to issue #{existing}"

    n_cassettes = body.count("\n##") + (1 if body.startswith("##") else 0)
    if n_cassettes == 0:
        n_cassettes = 1  # text format — at least one cassette must have produced the body
    title = _report_summary_line(n_cassettes)
    result = subprocess.run(
        ["gh", "issue", "create", "--label", label, "--title", title, "--body-file", "-"],
        input=body,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False, f"create issue failed: {result.stderr.strip()}"
    return True, f"created issue: {result.stdout.strip()}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect structural drift between VCR cassette directories.")
    parser.add_argument("--cassette-dir-old", default="tests/contract/cassettes",
                        help="Directory of committed cassettes (default: %(default)s).")
    parser.add_argument("--cassette-dir-new", default="tests/contract/cassettes.new",
                        help="Directory of freshly-recorded cassettes (default: %(default)s).")
    parser.add_argument("--report-format", choices=("text", "md"), default="text")
    parser.add_argument("--open-issue", action="store_true",
                        help="On drift, create or append to a 'drift'-labeled GitHub issue via gh.")
    args = parser.parse_args(argv)

    old_root = Path(args.cassette_dir_old)
    new_root = Path(args.cassette_dir_new)
    if not old_root.is_dir():
        sys.stderr.write(f"ERROR: --cassette-dir-old not found: {old_root}\n")
        return 2
    if not new_root.is_dir():
        sys.stderr.write(f"ERROR: --cassette-dir-new not found: {new_root}\n")
        return 2

    old_cassettes = _walk_cassettes(old_root)
    if not old_cassettes:
        sys.stderr.write(f"WARN: no cassettes found under {old_root}\n")
        return 0

    parsed_total = 0
    parse_failures = 0
    drifted_cassettes: list[tuple[str, list[DriftEntry]]] = []
    warnings: list[str] = []

    for old_path in old_cassettes:
        rel = old_path.relative_to(old_root)
        new_path = new_root / rel
        if not new_path.is_file():
            warnings.append(f"WARN: missing-on-new: {rel}")
            continue
        try:
            old_triples = load_cassette(str(old_path))
            new_triples = load_cassette(str(new_path))
        except CassetteParseError as e:
            warnings.append(f"WARN: skipping {rel} (parse error: {e})")
            parse_failures += 1
            continue
        parsed_total += 1

        pairs, only_old, only_new = pair_interactions(old_triples, new_triples)
        for o in only_old:
            warnings.append(f"WARN: orchestration: removed {rel} {o[0].get('method')} {o[0].get('uri')}")
        for n in only_new:
            warnings.append(f"WARN: orchestration: added {rel} {n[0].get('method')} {n[0].get('uri')}")

        cassette_entries: list[DriftEntry] = []
        for i, (old_triple, new_triple) in enumerate(pairs):
            old_body = old_triple[1]
            new_body = new_triple[1]
            if old_body is None or new_body is None:
                warnings.append(
                    f"WARN: {rel} interaction {i}: body skipped (not a recordable JSON success)"
                )
                continue
            cassette_entries.extend(diff_shapes(extract_shape(old_body), extract_shape(new_body)))
        if cassette_entries:
            drifted_cassettes.append((str(rel), cassette_entries))

    report_parts = [render_report(name, entries, fmt=args.report_format) for name, entries in drifted_cassettes]
    full_report = "".join(p for p in report_parts if p)
    if full_report:
        sys.stdout.write(full_report)
    for w in warnings:
        sys.stderr.write(w + "\n")

    if args.open_issue and drifted_cassettes:
        success, message = _post_or_append_issue("drift", "drift: ", full_report)
        if success:
            sys.stderr.write(message + "\n")
        else:
            sys.stderr.write(f"ERROR: drift detected but issue creation failed: {message}\n")

    if parsed_total == 0 and parse_failures > 0:
        return 1
    if drifted_cassettes:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Smoke-test the script's argparse**

Run: `uv run python scripts/cassette_drift.py --help`
Expected: prints the argparse help block listing all four flags.

- [ ] **Step 3: Smoke-test the missing-dir error path**

Run: `uv run python scripts/cassette_drift.py --cassette-dir-old /nonexistent --cassette-dir-new /nonexistent; echo $?`
Expected: stderr starts with `ERROR: --cassette-dir-old not found:`. Exit code 2.

- [ ] **Step 4: Lint and format**

Run: `uv run ruff check scripts/cassette_drift.py && uv run ruff format --check scripts/cassette_drift.py`
Expected: clean.

- [ ] **Step 5: Type-check**

Run: `uv run ty check src/gandi_mcp/`
Expected: clean (script isn't under src/; this confirms we didn't break anything else).

- [ ] **Step 6: Commit**

```bash
git add scripts/cassette_drift.py
git commit -m "feat(scripts): cassette_drift main() + argparse + exit codes"
```

---

## Task 8 — Write CLI subprocess integration tests

**Files:**
- Create: `tests/unit/test_cassette_drift_cli.py`

End-to-end tests that spawn `scripts/cassette_drift.py` as a subprocess against `tmp_path` cassette dirs. The `gh` CLI is stubbed by writing a fake `gh` executable into a `tmp_path` bin directory and prepending it to `PATH`.

- [ ] **Step 1: Write the failing tests**

Write `tests/unit/test_cassette_drift_cli.py`:

```python
"""CLI subprocess tests for scripts/cassette_drift.py.

Offline-pure: no live network, no real gh API. The gh CLI is stubbed via
a PATH-shadowing fake executable written into tmp_path.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cassette_drift.py"


def _cassette(interactions: list[dict]) -> str:
    return yaml.safe_dump({"interactions": interactions})


def _interaction(uri: str, body_json: str | None, method: str = "GET", status: int = 200) -> dict:
    return {
        "request": {"method": method, "uri": uri, "body": None},
        "response": {"status": {"code": status}, "body": {"string": body_json if body_json is not None else ""}},
    }


def _run_cli(args: list[str], env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _write_gh_stub(bindir: Path, *, on_list: str = "[]", on_create_rc: int = 0,
                   on_comment_rc: int = 0, recorder: Path | None = None) -> None:
    """Write a fake gh that records argv into ``recorder`` and behaves per the kwargs."""
    bindir.mkdir(parents=True, exist_ok=True)
    rec = str(recorder) if recorder else "/dev/null"
    gh = bindir / "gh"
    gh.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        echo "$@" >> {rec}
        case "$1 $2" in
          "issue list")
            echo '{on_list}'
            exit 0
            ;;
          "issue create")
            cat >/dev/null
            echo "https://github.com/x/y/issues/123"
            exit {on_create_rc}
            ;;
          "issue comment")
            cat >/dev/null
            exit {on_comment_rc}
            ;;
        esac
        exit 0
    """))
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _path_with_stub(bindir: Path) -> dict[str, str]:
    return {"PATH": f"{bindir}:{os.environ['PATH']}"}


@pytest.fixture
def cassette_dirs(tmp_path: Path) -> tuple[Path, Path]:
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    return old, new


class TestExitCodes:
    def test_no_drift_exit_0(self, cassette_dirs: tuple[Path, Path]) -> None:
        old, new = cassette_dirs
        body = '{"username": "alice"}'
        (old / "x.yaml").write_text(_cassette([_interaction("https://x", body)]))
        (new / "x.yaml").write_text(_cassette([_interaction("https://x", body)]))
        result = _run_cli(["--cassette-dir-old", str(old), "--cassette-dir-new", str(new)])
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""

    def test_drift_exit_1_with_report(self, cassette_dirs: tuple[Path, Path]) -> None:
        old, new = cassette_dirs
        (old / "x.yaml").write_text(_cassette([_interaction("https://x", '{"a": "x"}')]))
        (new / "x.yaml").write_text(_cassette([_interaction("https://x", '{"a": "x", "b": 1}')]))
        result = _run_cli(["--cassette-dir-old", str(old), "--cassette-dir-new", str(new)])
        assert result.returncode == 1, result.stdout + result.stderr
        assert "+ added .b (int)" in result.stdout
        assert "x.yaml" in result.stdout

    def test_missing_dir_exit_2(self, cassette_dirs: tuple[Path, Path]) -> None:
        old, _new = cassette_dirs
        result = _run_cli(["--cassette-dir-old", str(old), "--cassette-dir-new", "/nonexistent"])
        assert result.returncode == 2
        assert "--cassette-dir-new not found" in result.stderr

    def test_empty_old_dir_exit_0_with_warning(self, cassette_dirs: tuple[Path, Path]) -> None:
        old, new = cassette_dirs
        result = _run_cli(["--cassette-dir-old", str(old), "--cassette-dir-new", str(new)])
        assert result.returncode == 0
        assert "no cassettes found" in result.stderr


class TestOpenIssueFlag:
    def test_open_issue_creates_when_no_existing(
        self, cassette_dirs: tuple[Path, Path], tmp_path: Path
    ) -> None:
        old, new = cassette_dirs
        (old / "x.yaml").write_text(_cassette([_interaction("https://x", '{"a": "x"}')]))
        (new / "x.yaml").write_text(_cassette([_interaction("https://x", '{"a": "x", "b": 1}')]))
        recorder = tmp_path / "gh-argv.txt"
        bindir = tmp_path / "bin"
        _write_gh_stub(bindir, on_list="[]", recorder=recorder)
        result = _run_cli(
            ["--cassette-dir-old", str(old), "--cassette-dir-new", str(new), "--open-issue"],
            env_extra=_path_with_stub(bindir),
        )
        assert result.returncode == 1
        argv_log = recorder.read_text()
        assert "issue list" in argv_log
        assert "issue create" in argv_log
        assert "--label drift" in argv_log

    def test_open_issue_appends_when_existing_open(
        self, cassette_dirs: tuple[Path, Path], tmp_path: Path
    ) -> None:
        old, new = cassette_dirs
        (old / "x.yaml").write_text(_cassette([_interaction("https://x", '{"a": "x"}')]))
        (new / "x.yaml").write_text(_cassette([_interaction("https://x", '{"a": "x", "b": 1}')]))
        recorder = tmp_path / "gh-argv.txt"
        bindir = tmp_path / "bin"
        existing = json.dumps([{"number": 42, "title": "drift: 1 cassette drifted upstream"}])
        _write_gh_stub(bindir, on_list=existing, recorder=recorder)
        result = _run_cli(
            ["--cassette-dir-old", str(old), "--cassette-dir-new", str(new), "--open-issue"],
            env_extra=_path_with_stub(bindir),
        )
        assert result.returncode == 1
        argv_log = recorder.read_text()
        assert "issue comment 42" in argv_log
        assert "issue create" not in argv_log

    def test_open_issue_failure_still_reports_drift(
        self, cassette_dirs: tuple[Path, Path], tmp_path: Path
    ) -> None:
        old, new = cassette_dirs
        (old / "x.yaml").write_text(_cassette([_interaction("https://x", '{"a": "x"}')]))
        (new / "x.yaml").write_text(_cassette([_interaction("https://x", '{"a": "x", "b": 1}')]))
        recorder = tmp_path / "gh-argv.txt"
        bindir = tmp_path / "bin"
        _write_gh_stub(bindir, on_list="[]", on_create_rc=1, recorder=recorder)
        result = _run_cli(
            ["--cassette-dir-old", str(old), "--cassette-dir-new", str(new), "--open-issue"],
            env_extra=_path_with_stub(bindir),
        )
        assert result.returncode == 1
        assert "+ added .b (int)" in result.stdout
        assert "issue creation failed" in result.stderr


class TestWarnings:
    def test_non_json_body_emits_warning_not_drift(
        self, cassette_dirs: tuple[Path, Path]
    ) -> None:
        old, new = cassette_dirs
        (old / "x.yaml").write_text(_cassette([_interaction("https://x", "<html>not json</html>")]))
        (new / "x.yaml").write_text(_cassette([_interaction("https://x", "<html>not json</html>")]))
        result = _run_cli(["--cassette-dir-old", str(old), "--cassette-dir-new", str(new)])
        assert result.returncode == 0
        assert "body skipped" in result.stderr
        assert "+ added" not in result.stdout

    def test_missing_on_new_emits_warning_not_drift(
        self, cassette_dirs: tuple[Path, Path]
    ) -> None:
        old, _new = cassette_dirs
        (old / "x.yaml").write_text(_cassette([_interaction("https://x", '{"a": 1}')]))
        result = _run_cli(["--cassette-dir-old", str(old), "--cassette-dir-new", str(_new)])
        assert result.returncode == 0
        assert "missing-on-new" in result.stderr

    def test_orchestration_drift_only_does_not_fail(
        self, cassette_dirs: tuple[Path, Path]
    ) -> None:
        old, new = cassette_dirs
        # New cassette adds an extra interaction that doesn't exist in old.
        body = '{"a": 1}'
        (old / "x.yaml").write_text(_cassette([_interaction("https://x/a", body)]))
        (new / "x.yaml").write_text(
            _cassette([_interaction("https://x/a", body), _interaction("https://x/b", body)])
        )
        result = _run_cli(["--cassette-dir-old", str(old), "--cassette-dir-new", str(new)])
        assert result.returncode == 0  # orchestration drift only — no shape drift
        assert "orchestration: added" in result.stderr
```

- [ ] **Step 2: Run the CLI tests**

Run: `uv run pytest tests/unit/test_cassette_drift_cli.py -v`
Expected: 10 passed (3 in TestExitCodes wait 4: no_drift, drift, missing_dir, empty_old = 4. TestOpenIssueFlag has 3. TestWarnings has 3. Total = 10.)

- [ ] **Step 3: Lint and format**

Run: `uv run ruff check tests/unit/test_cassette_drift_cli.py && uv run ruff format --check tests/unit/test_cassette_drift_cli.py`
Expected: clean.

- [ ] **Step 4: Run the full project test suite to confirm no regressions**

Run: `uv run pytest tests/unit/ tests/mocked/ tests/property/ -q -m "not live"`
Expected: existing test count + 49 (Task 5) + 10 (Task 8) new tests, all passing.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_cassette_drift_cli.py
git commit -m "test(scripts): subprocess integration tests for cassette_drift CLI"
```

---

## Task 9 — Wire `make check-drift` and the missing-token guard test

**Files:**
- Modify: `Makefile` (depends on PR #100 having created it)
- Modify: `tests/unit/test_cassette_drift_cli.py` (append one test)

The Makefile already has `refresh-cassettes` (from PR #100) which has the staging-dir + token-guard pattern. Re-use the pattern for `check-drift`. Difference: never swap, run the drift script after recording.

- [ ] **Step 1: Confirm PR #100's Makefile exists**

Run: `test -f Makefile && grep -n "refresh-cassettes" Makefile`
Expected: prints at least one line containing `refresh-cassettes`. If not, abort — PR #100 must merge first.

- [ ] **Step 2: Append the new target**

Add to the `.PHONY:` line: ` check-drift`. Then append at the bottom of the file:

```makefile

# Re-record cassettes to staging dir and structurally diff against the committed
# tree. NEVER swaps the staging dir into place — that's `make refresh-cassettes`.
# Pass CASSETTE_DRIFT_OPEN_ISSUE=1 to open/append a drift-labeled GitHub issue.
check-drift:
	@if [ -z "$$GANDI_TOKEN" ]; then \
		echo "GANDI_TOKEN not set. Drift check requires the same sandbox PAT as refresh-cassettes."; \
		echo "Example: GANDI_TOKEN=\$$(pass show gandi/pat-sandbox) make check-drift"; \
		exit 2; \
	fi
	rm -rf tests/contract/cassettes.new
	mkdir -p tests/contract/cassettes.new
	VCR_CASSETTE_DIR=tests/contract/cassettes.new \
		uv run pytest tests/contract/ --record-mode=once -p no:cacheprovider
	uv run python scripts/cassette_drift.py \
		--cassette-dir-old tests/contract/cassettes \
		--cassette-dir-new tests/contract/cassettes.new \
		$(if $(CASSETTE_DRIFT_OPEN_ISSUE),--open-issue,)
```

- [ ] **Step 3: Append the guard test**

Append to `tests/unit/test_cassette_drift_cli.py`:

```python
class TestMakefileGuards:
    def test_check_drift_guards_missing_token(self) -> None:
        # Spawn make in the repo root with GANDI_TOKEN explicitly unset.
        env = {k: v for k, v in os.environ.items() if k != "GANDI_TOKEN"}
        result = subprocess.run(
            ["make", "check-drift"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=env,
            check=False,
        )
        assert result.returncode == 2
        assert "GANDI_TOKEN not set" in (result.stdout + result.stderr)
```

- [ ] **Step 4: Run the guard test**

Run: `uv run pytest tests/unit/test_cassette_drift_cli.py::TestMakefileGuards -v`
Expected: 1 passed.

- [ ] **Step 5: Lint Makefile via shellcheck on the inlined script**

Skip — Makefiles don't have a standard linter. Visual check is sufficient.

- [ ] **Step 6: Commit**

```bash
git add Makefile tests/unit/test_cassette_drift_cli.py
git commit -m "build: add make check-drift target with GANDI_TOKEN guard"
```

---

## Task 10 — Create the dormant `drift-check` workflow

**Files:**
- Create: `.github/workflows/drift-check.yml`

`workflow_dispatch`-only. No cron. Required secret `GANDI_SANDBOX_PAT`. Required label `drift` (declared in the top-of-file comment block since GitHub Actions has no machine-readable hook for it). `permissions: { contents: read, issues: write }`. `concurrency: { group: drift-check, cancel-in-progress: false }`.

- [ ] **Step 1: Verify the SHA pins below still match `.github/workflows/ci.yml`**

Run: `grep -E "uses: actions/checkout|uses: astral-sh/setup-uv" .github/workflows/ci.yml | sort -u`
Expected: matches the two `uses:` lines in Step 2's workflow body. If the existing CI has bumped either action, copy its current pin in (the comment-tag `# vX.Y.Z` is the version label).

As of plan authorship (2026-05-15):
- `actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6.0.2`
- `astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b  # v8.1.0`

- [ ] **Step 2: Write the workflow**

Write `.github/workflows/drift-check.yml`:

```yaml
# Cassette drift check (manual dispatch only).
#
# Required repo secret:  GANDI_SANDBOX_PAT  (PAT scoped to teamrocket.network)
# Required repo label:    drift
#
# Runs `make check-drift CASSETTE_DRIFT_OPEN_ISSUE=1`. On detected shape drift,
# the script creates or appends to a `drift`-labeled issue. No cron — operator
# dispatches manually. The concurrency group serializes overlapping dispatches.

name: drift-check

on:
  workflow_dispatch:

permissions:
  contents: read
  issues: write

concurrency:
  group: drift-check
  cancel-in-progress: false

jobs:
  drift:
    runs-on: ubuntu-latest
    env:
      GANDI_TOKEN: ${{ secrets.GANDI_SANDBOX_PAT }}
      GH_TOKEN: ${{ github.token }}
    steps:
      - name: Checkout
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6.0.2
        with:
          persist-credentials: false

      - name: Set up uv
        uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b  # v8.1.0

      - name: Sync deps
        run: uv sync --extra dev

      - name: Run drift check
        run: make check-drift CASSETTE_DRIFT_OPEN_ISSUE=1
```

- [ ] **Step 3: Verify the workflow file is valid YAML**

Run: `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/drift-check.yml'))"`
Expected: silent (exit 0). No `yaml.YAMLError`.

- [ ] **Step 4: Lint the workflow with zizmor**

Run: `pipx run zizmor==1.24.1 .github/workflows/drift-check.yml`
Expected: no new findings (or only findings consistent with `.github/workflows/ci.yml`'s baseline — e.g. self-hosted-runner notes).

- [ ] **Step 5: Lint with actionlint**

Run: `actionlint .github/workflows/drift-check.yml 2>&1 || true`
Expected: no errors. (If `actionlint` is not installed, skip.)

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/drift-check.yml
git commit -m "ci: dormant drift-check workflow (workflow_dispatch only)"
```

---

## Task 11 — Document the workflow in CONTRIBUTING.md

**Files:**
- Modify: `CONTRIBUTING.md`

Append a section explaining when and how to run drift detection, what the failure modes look like, and what the operator should do on a positive result.

- [ ] **Step 1: Locate the insertion point**

Run: `grep -n "^### Recording contract cassettes" CONTRIBUTING.md`
Expected: prints the line number of the section added by PR #100. The new section goes immediately after.

- [ ] **Step 2: Insert the section**

Append after the "Recording contract cassettes" section:

```markdown
### Detecting cassette drift

Cassettes pin response shape (keys + types + cardinality bounds) but don't
detect when Gandi silently renames or restructures fields between refreshes.
`make check-drift` records new cassettes against `teamrocket.network`,
diffs them structurally against the committed tree, and reports any
additions / removals / type changes / cardinality shifts.

**To run locally:**

```bash
GANDI_TOKEN=$(pass show gandi/pat-sandbox) make check-drift
```

Exits 0 on no drift, 1 on drift detected (with a report on stdout), 2 on
invalid input or missing token. The freshly-recorded cassettes stay in
`tests/contract/cassettes.new/` — they are never automatically swapped
into place. If the drift is real and accepted, run `make refresh-cassettes`
to update the committed tree.

**To run in CI:**

The `drift-check` workflow under `.github/workflows/drift-check.yml` is
dispatch-only (no cron). Trigger it from the Actions tab. On detected
drift the workflow opens or appends to a `drift`-labeled issue via the
project's `GANDI_SANDBOX_PAT` secret. Required:

- Repo secret `GANDI_SANDBOX_PAT` set to a PAT scoped to `teamrocket.network`.
- Repo label `drift` exists.

**What counts as drift?**

| Symbol | Meaning |
|---|---|
| `+ added <path> (<type>)` | New key Gandi started returning. |
| `- removed <path> (<type>)` | Key Gandi stopped returning. |
| `~ <path>: <old> → <new>` | Value type changed (e.g. `str → int`). |
| `! list <path>: m..n → p..q` | List cardinality bounds shifted. |
| `~ union <path>: ...` | A heterogeneous list's member-type set changed. |

Warnings (stderr) cover non-comparable interactions (non-JSON bodies,
missing-on-new files, orchestration changes from the test suite itself);
these do not fail the gate.
```

- [ ] **Step 3: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "docs: how to run and interpret cassette drift detection"
```

---

## Task 12 — Create the `drift` GitHub label

**Files:** none (one-time operator action via `gh`)

The workflow uses `--label drift`; the label must exist before the first dispatch or `gh issue create` fails.

- [ ] **Step 1: Check whether the label exists**

Run: `gh label list --json name --jq '.[] | select(.name == "drift") | .name'`
Expected: either prints `drift` (already exists; skip step 2) or prints nothing.

- [ ] **Step 2: Create the label if missing**

Run: `gh label create drift --description "Structural drift detected between committed and live cassettes" --color "FBCA04"`
Expected: prints `✓ Label "drift" created in <repo>` on success.

- [ ] **Step 3: No commit needed** — this is a repo-level configuration action, not a code change.

---

## Task 13 — Full local verification + coverage snapshot

This is a verification gate, not a code task. Confirm the whole scaffolding works as a unit before opening the PR.

- [ ] **Step 1: Run lint + format across touched files**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: `All checks passed!` and a count of "already formatted".

- [ ] **Step 2: Run type check**

Run: `uv run ty check src/gandi_mcp/`
Expected: clean.

- [ ] **Step 3: Run the full unit + mocked + property suite**

Run: `uv run pytest tests/unit/ tests/mocked/ tests/property/ -q -m "not live"`
Expected: every existing test still passes plus the new drift tests:
- `tests/unit/test_cassette_drift.py` — 49 passed.
- `tests/unit/test_cassette_drift_cli.py` — 11 passed (10 from Task 8 + 1 Makefile guard from Task 9).

- [ ] **Step 4: Confirm coverage doesn't regress**

Run: `uv run pytest tests/unit/ tests/mocked/ tests/property/ -m "not live" --cov=gandi_mcp --cov-report=term -q && uv run python scripts/check_coverage_thresholds.py`
Expected: total coverage unchanged (drift script is not under `[tool.coverage.run] source = ["gandi_mcp"]`); per-file gate satisfied.

- [ ] **Step 5: Smoke-test the script against a real cassette pair**

Make a throwaway directory with two cassettes that differ in one field, run the script, confirm the report:

```bash
mkdir -p /tmp/drift-smoke/{old,new}
cat > /tmp/drift-smoke/old/x.yaml <<'EOF'
interactions:
- request: {method: GET, uri: https://x, body: null}
  response: {status: {code: 200}, body: {string: '{"a": 1}'}}
EOF
cat > /tmp/drift-smoke/new/x.yaml <<'EOF'
interactions:
- request: {method: GET, uri: https://x, body: null}
  response: {status: {code: 200}, body: {string: '{"a": 1, "b": "new"}'}}
EOF
uv run python scripts/cassette_drift.py \
    --cassette-dir-old /tmp/drift-smoke/old \
    --cassette-dir-new /tmp/drift-smoke/new
echo "exit: $?"
rm -rf /tmp/drift-smoke
```

Expected: stdout contains `+ added .b (str)`. Exit code 1.

- [ ] **Step 6: Clean coverage artifacts**

Run: `rm -f coverage.json coverage.xml`
Expected: silent.

---

## Task 14 — Push branch + open PR

**Files:** none (git operations)

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/cassette-drift-detection
```

(Substitute your actual branch name if you started work on a different one. The rest of this task is unchanged.)

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "feat: cassette drift detection (make check-drift + dormant CI)" \
    --body "$(cat <<'EOF'
## Summary

Adds `scripts/cassette_drift.py` + `make check-drift` + a `workflow_dispatch`-only
`drift-check` CI workflow. Detects structural drift (added/removed/type-changed
keys, cardinality shifts) between committed cassettes and freshly-recorded ones,
then prints a report and (in CI) opens/appends a `drift`-labeled issue.

Implements spec `docs/superpowers/specs/2026-05-15-cassette-drift-detection-design.md`.

What's in:

- `scripts/cassette_drift.py` — single-file CLI, 6 pure functions + `main()`.
- `tests/unit/test_cassette_drift.py` — 49 unit tests across 6 test classes.
- `tests/unit/test_cassette_drift_cli.py` — 11 subprocess integration tests
  using a PATH-shadowed `gh` stub.
- `Makefile` — new `check-drift` target with `GANDI_TOKEN` guard.
- `.github/workflows/drift-check.yml` — workflow_dispatch only, no cron.
- `CONTRIBUTING.md` — "Detecting cassette drift" section.
- `scripts/__init__.py` — package marker so the script is testable.

What's not in:

- A `cron:` schedule for the workflow. Deliberate non-decision deferred to a
  future PR after the secret-management + alert-routing story is settled.
- A drift-allowlist mechanism for fields that are expected to drift. Add only
  if false-positive churn becomes painful in practice.

## Test plan

- [x] `uv run pytest tests/unit/test_cassette_drift.py tests/unit/test_cassette_drift_cli.py -v` — 60 passed.
- [x] `uv run pytest tests/unit/ tests/mocked/ tests/property/ -q -m "not live"` — full suite green.
- [x] `uv run ruff check . && uv run ruff format --check .` — clean.
- [x] `uv run ty check src/gandi_mcp/` — clean.
- [x] Smoke-test the script against a synthetic cassette pair (Task 13 Step 5) — produces the expected `+ added` line and exit 1.
- [ ] Maintainer: dispatch the `drift-check` workflow once after merge to confirm the CI path works end-to-end against `teamrocket.network`. (Requires `GANDI_SANDBOX_PAT` secret to be set.)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

After completing every task, verify the following:

**Spec coverage:**

| Spec section | Task |
|---|---|
| Architecture (sibling-to-PR-A infra) | 1, 9, 10 |
| Components — `extract_shape` + `merge_list_shape` | 2 |
| Components — `diff_shapes` + `DriftEntry` | 3 |
| Components — `render_report` | 4 |
| Components — `load_cassette` + `pair_interactions` | 5 |
| Components — `find_existing_drift_issue` | 6 |
| Components — `main()` glue + exit codes | 7 |
| Data flow — Makefile target | 9 |
| Data flow — workflow_dispatch | 10 |
| Error handling — `GANDI_TOKEN` guard | 9 (impl) + 9 step 3 (test) |
| Error handling — cassette parse failures | 5 |
| Error handling — non-JSON / non-2xx bodies | 5 |
| Error handling — `gh` failures | 6 + 7 + 8 (TestOpenIssueFlag) |
| Testing — unit pure functions | 2, 3, 4, 5, 6 |
| Testing — CLI subprocess + `gh` stub | 8 |
| Migration — Makefile target | 9 |
| Migration — workflow file | 10 |
| Migration — CONTRIBUTING.md section | 11 |
| Migration — `drift` label | 12 |

**Placeholder scan:** no "TBD", "TODO", "implement later" in any step. Every code step has complete code. Every test step shows the assertion.

**Type consistency:** `DriftEntry` defined in Task 3, used in Tasks 4, 7, 8. `Shape` type alias defined in Task 2, used implicitly throughout. `CassetteParseError` defined in Task 5, used in Tasks 7, 8 (warnings). `load_cassette` signature is `path → list[tuple[dict, Any, int]]` consistent across Tasks 5, 7, 8. `pair_interactions` signature is consistent across Tasks 5, 7.
