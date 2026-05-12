"""AST invariant: every write/purchase tool calls its runtime assert (closes #42).

The three-tier safety model (readonly → readwrite → readwrite+purchases) is
enforced by two independent layers:

1. Visibility — ``mcp.disable(tags={"write"})`` / ``mcp.disable(tags={"purchase"})``
   in ``server.py``.
2. Runtime — ``assert_readwrite(ctx, ...)`` / ``assert_purchases_allowed(ctx, ...)``
   inside each handler.

The runtime layer protects against the case where an operator runs in
``readwrite`` mode but the client reuses a tool list cached from a prior
``readonly`` startup. A new write-tagged tool that forgets the assert would
still pass lint, mypy, and unit tests — only a careful reviewer or this AST
test would catch it. We pin the property statically so a regression fails CI.

The walker resolves import aliases for the gate functions (closes #72): a
``from gandi_mcp.tools._common import assert_readwrite as assert_rw`` is
recognised, as is the attribute form ``from gandi_mcp.tools import _common as c;
c.assert_readwrite(...)``. Reassignment of either the canonical name or any
alias (module-level or function-local) shadows the binding — once shadowed,
calls to that name are no longer treated as gate calls, so a future tool that
tries to bypass the gate by reassigning it is still flagged.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

TOOLS_DIR = pathlib.Path(__file__).resolve().parents[2] / "src" / "gandi_mcp" / "tools"
SKIP_FILES = frozenset({"__init__.py", "_common.py"})

WRITE_TAG = "write"
PURCHASE_TAG = "purchase"

WRITE_ASSERT = "assert_readwrite"
PURCHASE_ASSERT = "assert_purchases_allowed"

GATE_MODULE = "gandi_mcp.tools._common"
GATE_MODULE_LEAF = "_common"
CANONICAL_GATES = frozenset({WRITE_ASSERT, PURCHASE_ASSERT})


def _decorator_tags(decorator: ast.expr) -> set[str]:
    """Return the string tag set from ``@mcp.tool(tags={...})``, or empty.

    Only matches a ``Call`` whose ``tags`` keyword is a ``Set`` of string
    ``Constant``\\s. Anything dynamic (variable, comprehension) returns the
    empty set — we want a regression there to be caught explicitly via a
    visible test failure, not silently pass by the type erasing it.
    """
    if not isinstance(decorator, ast.Call):
        return set()
    for kw in decorator.keywords:
        if kw.arg == "tags" and isinstance(kw.value, ast.Set):
            return {e.value for e in kw.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return set()


def _function_tags(node: ast.AsyncFunctionDef | ast.FunctionDef) -> set[str]:
    tags: set[str] = set()
    for dec in node.decorator_list:
        tags |= _decorator_tags(dec)
    return tags


def _calls_named(node: ast.AST, name: str) -> bool:
    """True if ``node`` contains a direct call to ``name(...)``."""
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == name:
            return True
    return False


def _module_aliases(tree: ast.Module) -> tuple[dict[str, str], set[str]]:
    """Resolve gate-related imports in a module.

    Returns ``(name_aliases, module_aliases)``:

    - ``name_aliases`` maps each local name bound to a gate function to its
      canonical name. ``from gandi_mcp.tools._common import assert_readwrite``
      yields ``{"assert_readwrite": "assert_readwrite"}``; the same with
      ``as assert_rw`` yields ``{"assert_rw": "assert_readwrite"}``.
    - ``module_aliases`` is the set of local names bound to the
      ``gandi_mcp.tools._common`` module (so attribute-form calls like
      ``c.assert_readwrite(...)`` can be recognised). Covers
      ``from gandi_mcp.tools import _common [as c]`` and
      ``import gandi_mcp.tools._common as c``.

    Only imports that actually reach ``gandi_mcp.tools._common`` are tracked;
    a same-named import from a different module is ignored.
    """
    name_aliases: dict[str, str] = {}
    module_aliases: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.module == GATE_MODULE:
                for alias in node.names:
                    if alias.name in CANONICAL_GATES:
                        name_aliases[alias.asname or alias.name] = alias.name
            elif node.module == "gandi_mcp.tools":
                for alias in node.names:
                    if alias.name == GATE_MODULE_LEAF:
                        module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == GATE_MODULE and alias.asname is not None:
                    module_aliases.add(alias.asname)
    return name_aliases, module_aliases


def _stored_names(node: ast.AST) -> set[str]:
    """Names locally rebound inside ``node``.

    Used to invalidate any gate-name binding the user shadowed — either by an
    assignment, an augmented assignment, a walrus, a function/class def with
    the same name, or a ``global``/``nonlocal`` declaration. A shadowed name
    is no longer trusted to refer to the canonical gate function.
    """
    stored: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            stored.add(child.id)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            stored.add(child.name)
        elif isinstance(child, (ast.Global, ast.Nonlocal)):
            stored.update(child.names)
    return stored


def _function_calls_gate(
    tree: ast.Module,
    func: ast.AsyncFunctionDef | ast.FunctionDef,
    canonical: str,
) -> bool:
    """True if ``func`` calls the gate ``canonical`` via any allowed binding.

    Resolves bindings via :func:`_module_aliases` for the module, then unions
    in module-level shadowing (any reassignment at the top level of ``tree``
    invalidates the alias). Within ``func``, any locally-stored name is
    treated as shadowed for the whole function — Python lifts all assignments
    in a function to the function's local scope, so a later reassignment
    invalidates the earlier alias even before the assignment runs (matching
    the "static name resolution can't be trusted" intuition we want this
    walker to encode).
    """
    if canonical not in CANONICAL_GATES:
        raise ValueError(f"Unknown canonical gate name: {canonical!r}")
    name_aliases, module_aliases = _module_aliases(tree)
    # ``ast.alias`` (the import-statement binding) does not produce an
    # ``ast.Name`` with Store context, so an unaltered import is absent from
    # ``_stored_names``. Any name found there is a real reassignment.
    shadowed = _stored_names(tree) | _stored_names(func)
    live_names = {local: cname for local, cname in name_aliases.items() if local not in shadowed}
    live_modules = {m for m in module_aliases if m not in shadowed}
    for child in ast.walk(func):
        if not isinstance(child, ast.Call):
            continue
        called = child.func
        if isinstance(called, ast.Name) and called.id in live_names and live_names[called.id] == canonical:
            return True
        if (
            isinstance(called, ast.Attribute)
            and isinstance(called.value, ast.Name)
            and called.value.id in live_modules
            and called.attr == canonical
        ):
            return True
    return False


def _is_gate_call(node: ast.AST, tree: ast.Module, canonical: str) -> bool:
    """True if ``node`` is a ``Call`` resolving to the canonical gate ``canonical``.

    Matches a bare-``Name`` call where the name resolves via :func:`_module_aliases`,
    or a module-attribute call (``c.assert_readwrite(...)`` where ``c`` aliases
    ``gandi_mcp.tools._common``). Shadowing is **not** applied here because the
    caller has already pinned this specific call site — the question is "is this
    exact node a gate call?" not "could some bound name reach the gate?".
    """
    if canonical not in CANONICAL_GATES:
        raise ValueError(f"Unknown canonical gate name: {canonical!r}")
    if not isinstance(node, ast.Call):
        return False
    name_aliases, module_aliases = _module_aliases(tree)
    called = node.func
    if isinstance(called, ast.Name) and called.id in name_aliases and name_aliases[called.id] == canonical:
        return True
    return (
        isinstance(called, ast.Attribute)
        and isinstance(called.value, ast.Name)
        and called.value.id in module_aliases
        and called.attr == canonical
    )


def _first_try(func: ast.AsyncFunctionDef | ast.FunctionDef) -> ast.Try | None:
    """Return the first ``ast.Try`` statement in ``func.body``, or ``None``.

    The documented convention is that a tool handler's body is a single ``try`` /
    ``except``. A tool with no ``try`` block at all fails the first-stmt
    invariant because the gate has no defined position relative to the wrapped
    API call.
    """
    for stmt in func.body:
        if isinstance(stmt, ast.Try):
            return stmt
    return None


def _expected_gates_for_tags(tags: set[str]) -> list[str]:
    """The required gate-call sequence at the head of a tool's first ``try`` block.

    - Write-only tool: ``[assert_readwrite]``.
    - Purchase tool: ``[assert_readwrite, assert_purchases_allowed]`` — the
      readwrite check must come first so an operator hitting a purchase tool
      in readonly mode sees the narrower "read-only" error, not "purchases
      disabled" (per ``CLAUDE.md``'s "narrower error first" contract).
    - Read tool: ``[]`` (no gate expected).
    """
    if PURCHASE_TAG in tags:
        return [WRITE_ASSERT, PURCHASE_ASSERT]
    if WRITE_TAG in tags:
        return [WRITE_ASSERT]
    return []


def _gate_sequence_starting_try(try_node: ast.Try, tree: ast.Module, expected: list[str]) -> tuple[bool, str]:
    """Verify ``try_node.body[0:N]`` is the expected gate-call sequence.

    Returns ``(ok, reason)``. On mismatch, ``reason`` names the offending
    statement so the test failure points the contributor at the right line.
    """
    body = try_node.body
    if len(body) < len(expected):
        return False, f"try body has only {len(body)} statements; need at least {len(expected)}"
    for i, canonical in enumerate(expected):
        stmt = body[i]
        if not isinstance(stmt, ast.Expr):
            return False, f"try body[{i}] is {type(stmt).__name__}, expected a bare call to {canonical}"
        if not _is_gate_call(stmt.value, tree, canonical):
            return False, f"try body[{i}] is not a call to {canonical}; got {ast.unparse(stmt)}"
    return True, ""


def _iter_tool_functions() -> list[tuple[pathlib.Path, ast.Module, ast.AsyncFunctionDef]]:
    """Every ``async def`` decorated with ``@mcp.tool(...)`` under ``tools/``.

    Yields ``(path, module_tree, func)`` so callers can resolve module-level
    imports (used by :func:`_function_calls_gate`) without re-parsing.
    """
    found: list[tuple[pathlib.Path, ast.Module, ast.AsyncFunctionDef]] = []
    for path in sorted(TOOLS_DIR.glob("*.py")):
        if path.name in SKIP_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found.extend(
            (path, tree, node)
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and _function_tags(node)
        )
    return found


def test_every_write_tool_calls_assert_readwrite() -> None:
    """A tool tagged ``"write"`` must call ``assert_readwrite`` in its body."""
    offenders: list[str] = []
    write_count = 0
    for path, tree, node in _iter_tool_functions():
        tags = _function_tags(node)
        if WRITE_TAG not in tags:
            continue
        write_count += 1
        if not _function_calls_gate(tree, node, WRITE_ASSERT):
            offenders.append(f"{path.name}::{node.name}")
    assert not offenders, f"write-tagged tools missing {WRITE_ASSERT}(): {offenders}"
    assert write_count > 0, "AST walker found no write-tagged tools — test is a no-op"


def test_every_purchase_tool_calls_assert_purchases_allowed() -> None:
    """A tool tagged ``"purchase"`` must call ``assert_purchases_allowed`` in its body."""
    offenders: list[str] = []
    purchase_count = 0
    for path, tree, node in _iter_tool_functions():
        tags = _function_tags(node)
        if PURCHASE_TAG not in tags:
            continue
        purchase_count += 1
        if not _function_calls_gate(tree, node, PURCHASE_ASSERT):
            offenders.append(f"{path.name}::{node.name}")
    assert not offenders, f"purchase-tagged tools missing {PURCHASE_ASSERT}(): {offenders}"
    assert purchase_count > 0, "AST walker found no purchase-tagged tools — test is a no-op"


def test_gate_is_first_statement_of_try_block() -> None:
    """The runtime gate must be the first statement of the tool's first ``try`` block.

    Pins the convention documented in ``CLAUDE.md`` ("Adding a write tool" /
    "Adding a purchase tool"). A future contributor placing the gate after the
    API call, or inside an ``if`` branch, would still pass the
    :func:`_function_calls_gate` invariant — and still ship a tool that hits
    Gandi before the runtime safety check runs. This test closes that gap.

    For purchase tools, ``assert_readwrite`` must precede ``assert_purchases_allowed``
    so the narrower error surfaces first.
    """
    offenders: list[str] = []
    write_count = 0
    purchase_count = 0
    for path, tree, node in _iter_tool_functions():
        tags = _function_tags(node)
        expected = _expected_gates_for_tags(tags)
        if not expected:
            continue
        if PURCHASE_TAG in tags:
            purchase_count += 1
        elif WRITE_TAG in tags:
            write_count += 1
        try_node = _first_try(node)
        if try_node is None:
            offenders.append(f"{path.name}::{node.name}: no try block at function top level")
            continue
        ok, reason = _gate_sequence_starting_try(try_node, tree, expected)
        if not ok:
            offenders.append(f"{path.name}::{node.name}: {reason}")
    assert not offenders, "tools with mis-placed runtime gates:\n  " + "\n  ".join(offenders)
    assert write_count > 0, "AST walker found no write-tagged tools — test is a no-op"
    assert purchase_count > 0, "AST walker found no purchase-tagged tools — test is a no-op"


def test_every_purchase_tool_is_also_a_write_tool() -> None:
    """``"purchase"`` implies ``"write"`` — keeps the two-layer disable working.

    ``server.py`` disables both tags independently in readonly mode. If a
    purchase tool ever loses its ``"write"`` tag, ``mcp.disable(tags={"write"})``
    would still leave it visible in readonly mode — relying entirely on the
    runtime assert. The convention in ``CLAUDE.md`` is that purchase tools
    carry both tags; this pins it.
    """
    offenders: list[str] = []
    for path, _tree, node in _iter_tool_functions():
        tags = _function_tags(node)
        if PURCHASE_TAG in tags and WRITE_TAG not in tags:
            offenders.append(f"{path.name}::{node.name}")
    assert not offenders, f"purchase-tagged tools missing 'write' tag: {offenders}"


# ── Helper fixtures ────────────────────────────────────────────────────────


def _parse_tool(src: str) -> ast.AsyncFunctionDef:
    """Parse one module containing a single ``async def`` and return it."""
    module = ast.parse(src)
    [func] = [n for n in module.body if isinstance(n, ast.AsyncFunctionDef)]
    return func


def _parse_module_and_tool(src: str) -> tuple[ast.Module, ast.AsyncFunctionDef]:
    """Parse a module containing a single ``async def`` and return ``(module, func)``."""
    module = ast.parse(src)
    [func] = [n for n in module.body if isinstance(n, ast.AsyncFunctionDef)]
    return module, func


def test_decorator_tags_extracts_string_set() -> None:
    src = '@mcp.tool(tags={"gandi", "domain", "write"})\nasync def t(ctx):\n    pass\n'
    assert _function_tags(_parse_tool(src)) == {"gandi", "domain", "write"}


def test_decorator_tags_ignores_undecorated() -> None:
    src = "async def t(ctx):\n    pass\n"
    assert _function_tags(_parse_tool(src)) == set()


def test_decorator_tags_ignores_non_set_tags() -> None:
    """A list literal would be a regression (looser tag literal); we treat it as untagged.

    The handler for that hypothetical regression is "fail the count assertion" —
    the no-op guard at the end of each test catches a tooling change that
    silently empties the tagged-tool set.
    """
    src = '@mcp.tool(tags=["gandi", "write"])\nasync def t(ctx):\n    pass\n'
    assert _function_tags(_parse_tool(src)) == set()


def test_calls_named_finds_nested_call() -> None:
    src = (
        "async def t(ctx):\n"
        "    try:\n"
        '        assert_readwrite(ctx, "x")\n'
        "        return None\n"
        "    except Exception:\n"
        "        raise\n"
    )
    assert _calls_named(_parse_tool(src), "assert_readwrite")


def test_calls_named_rejects_attribute_call() -> None:
    """``self.assert_readwrite(...)`` is not the same function — must be a bare ``Name``.

    The legitimate attribute form (``c.assert_readwrite(...)`` where ``c`` is a
    module alias) is recognised by :func:`_function_calls_gate`, not the bare
    :func:`_calls_named` helper.
    """
    src = 'async def t(ctx):\n    self.assert_readwrite(ctx, "x")\n'
    assert not _calls_named(_parse_tool(src), "assert_readwrite")


def test_calls_named_returns_false_when_absent() -> None:
    src = "async def t(ctx):\n    return await client.write(ctx)\n"
    assert not _calls_named(_parse_tool(src), "assert_readwrite")


# ── Alias-resolving walker (#72) ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("src", "canonical", "expected"),
    [
        # Canonical bare import + call.
        (
            'from gandi_mcp.tools._common import assert_readwrite\nasync def t(ctx):\n    assert_readwrite(ctx, "x")\n',
            WRITE_ASSERT,
            True,
        ),
        # Aliased import: `from ... import X as Y` then call Y.
        (
            "from gandi_mcp.tools._common import assert_readwrite as assert_rw\n"
            "async def t(ctx):\n"
            '    assert_rw(ctx, "x")\n',
            WRITE_ASSERT,
            True,
        ),
        # Attribute form via `from gandi_mcp.tools import _common`.
        (
            'from gandi_mcp.tools import _common\nasync def t(ctx):\n    _common.assert_readwrite(ctx, "x")\n',
            WRITE_ASSERT,
            True,
        ),
        # Attribute form via `from gandi_mcp.tools import _common as c`.
        (
            'from gandi_mcp.tools import _common as c\nasync def t(ctx):\n    c.assert_readwrite(ctx, "x")\n',
            WRITE_ASSERT,
            True,
        ),
        # Attribute form via `import gandi_mcp.tools._common as c`.
        (
            'import gandi_mcp.tools._common as c\nasync def t(ctx):\n    c.assert_readwrite(ctx, "x")\n',
            WRITE_ASSERT,
            True,
        ),
        # Same coverage on the purchase gate (alias form).
        (
            "from gandi_mcp.tools._common import assert_purchases_allowed as assert_pa\n"
            "async def t(ctx):\n"
            '    assert_pa(ctx, "x")\n',
            PURCHASE_ASSERT,
            True,
        ),
        # Same coverage on the purchase gate (module-attr form).
        (
            'from gandi_mcp.tools import _common as c\nasync def t(ctx):\n    c.assert_purchases_allowed(ctx, "x")\n',
            PURCHASE_ASSERT,
            True,
        ),
        # No call at all — must be False.
        (
            "from gandi_mcp.tools._common import assert_readwrite\n"
            "async def t(ctx):\n"
            "    return await client.write(ctx)\n",
            WRITE_ASSERT,
            False,
        ),
        # Attribute call with the wrong attr name.
        (
            'from gandi_mcp.tools import _common as c\nasync def t(ctx):\n    c.something_else(ctx, "x")\n',
            WRITE_ASSERT,
            False,
        ),
        # Attribute call on an unrelated name (``self``) — not a module alias.
        (
            "from gandi_mcp.tools._common import assert_readwrite\n"
            "async def t(ctx):\n"
            '    self.assert_readwrite(ctx, "x")\n',
            WRITE_ASSERT,
            False,
        ),
        # Imported under an alias but the bare canonical name is called — the
        # canonical name isn't bound, so this must be False.
        (
            "from gandi_mcp.tools._common import assert_readwrite as assert_rw\n"
            "async def t(ctx):\n"
            '    assert_readwrite(ctx, "x")\n',
            WRITE_ASSERT,
            False,
        ),
    ],
)
def test_function_calls_gate_resolves_aliases(src: str, canonical: str, expected: bool) -> None:
    """The walker recognises aliased imports and attribute-form calls."""
    tree, func = _parse_module_and_tool(src)
    assert _function_calls_gate(tree, func, canonical) is expected


@pytest.mark.parametrize(
    "src",
    [
        # Module-level reassignment of the canonical name.
        (
            "from gandi_mcp.tools._common import assert_readwrite\n"
            "assert_readwrite = lambda *a, **kw: None\n"
            "async def t(ctx):\n"
            '    assert_readwrite(ctx, "x")\n'
        ),
        # Function-local reassignment of the canonical name.
        (
            "from gandi_mcp.tools._common import assert_readwrite\n"
            "async def t(ctx):\n"
            "    assert_readwrite = lambda *a, **kw: None\n"
            '    assert_readwrite(ctx, "x")\n'
        ),
        # Module-level reassignment of an ``as alias``.
        (
            "from gandi_mcp.tools._common import assert_readwrite as assert_rw\n"
            "assert_rw = lambda *a, **kw: None\n"
            "async def t(ctx):\n"
            '    assert_rw(ctx, "x")\n'
        ),
        # Function-local reassignment of a module alias.
        (
            "from gandi_mcp.tools import _common as c\n"
            "async def t(ctx):\n"
            "    c = object()\n"
            '    c.assert_readwrite(ctx, "x")\n'
        ),
        # Function-local reassignment of a purchase-gate alias.
        (
            "from gandi_mcp.tools._common import assert_purchases_allowed as assert_pa\n"
            "async def t(ctx):\n"
            "    assert_pa = lambda *a, **kw: None\n"
            '    assert_pa(ctx, "x")\n'
        ),
    ],
)
def test_function_calls_gate_rejects_reassigned_names(src: str) -> None:
    """A reassigned gate name shadows the alias — must not be treated as a gate call."""
    tree, func = _parse_module_and_tool(src)
    canonical = PURCHASE_ASSERT if "purchase" in src else WRITE_ASSERT
    assert _function_calls_gate(tree, func, canonical) is False


def test_function_calls_gate_rejects_unknown_canonical() -> None:
    """The walker refuses to look up an unknown gate name — typos must fail loudly."""
    src = "from gandi_mcp.tools._common import assert_readwrite\nasync def t(ctx):\n    pass\n"
    tree, func = _parse_module_and_tool(src)
    with pytest.raises(ValueError, match="Unknown canonical gate name"):
        _function_calls_gate(tree, func, "assert_something_else")


# ── First-statement gate-placement walker (#73) ────────────────────────────


_FIRST_STMT_OK_WRITE = (
    "from gandi_mcp.tools._common import assert_readwrite\n"
    "async def t(ctx):\n"
    "    try:\n"
    '        assert_readwrite(ctx, "x")\n'
    "        return None\n"
    "    except Exception:\n"
    "        raise\n"
)

_FIRST_STMT_OK_PURCHASE = (
    "from gandi_mcp.tools._common import assert_readwrite, assert_purchases_allowed\n"
    "async def t(ctx):\n"
    "    try:\n"
    '        assert_readwrite(ctx, "x")\n'
    '        assert_purchases_allowed(ctx, "x")\n'
    "        return None\n"
    "    except Exception:\n"
    "        raise\n"
)


def test_first_stmt_walker_accepts_canonical_write_shape() -> None:
    tree, func = _parse_module_and_tool(_FIRST_STMT_OK_WRITE)
    try_node = _first_try(func)
    assert try_node is not None
    ok, _ = _gate_sequence_starting_try(try_node, tree, [WRITE_ASSERT])
    assert ok


def test_first_stmt_walker_accepts_canonical_purchase_shape() -> None:
    tree, func = _parse_module_and_tool(_FIRST_STMT_OK_PURCHASE)
    try_node = _first_try(func)
    assert try_node is not None
    ok, _ = _gate_sequence_starting_try(try_node, tree, [WRITE_ASSERT, PURCHASE_ASSERT])
    assert ok


@pytest.mark.parametrize(
    "src",
    [
        # Gate after the API call — must be flagged.
        (
            "from gandi_mcp.tools._common import assert_readwrite\n"
            "async def t(ctx):\n"
            "    try:\n"
            "        await client.register(ctx)\n"
            '        assert_readwrite(ctx, "register")\n'
            "    except Exception:\n"
            "        raise\n"
        ),
        # Gate inside an `if False:` branch — never executed.
        (
            "from gandi_mcp.tools._common import assert_readwrite\n"
            "async def t(ctx):\n"
            "    try:\n"
            "        if False:\n"
            '            assert_readwrite(ctx, "x")\n'
            "        await client.register(ctx)\n"
            "    except Exception:\n"
            "        raise\n"
        ),
        # Gate inside an `else` branch — same problem.
        (
            "from gandi_mcp.tools._common import assert_readwrite\n"
            "async def t(ctx):\n"
            "    try:\n"
            "        if cond:\n"
            "            return None\n"
            "        else:\n"
            '            assert_readwrite(ctx, "x")\n'
            "    except Exception:\n"
            "        raise\n"
        ),
        # No try block at all.
        (
            "from gandi_mcp.tools._common import assert_readwrite\n"
            "async def t(ctx):\n"
            '    assert_readwrite(ctx, "x")\n'
            "    return None\n"
        ),
    ],
)
def test_first_stmt_walker_rejects_mis_placed_write_gate(src: str) -> None:
    """A write tool with the gate buried anywhere except `try.body[0]` must be flagged."""
    tree, func = _parse_module_and_tool(src)
    try_node = _first_try(func)
    if try_node is None:
        # No-try case — the wrapper would record this as an offender too.
        return
    ok, _ = _gate_sequence_starting_try(try_node, tree, [WRITE_ASSERT])
    assert ok is False


def test_first_stmt_walker_rejects_reversed_purchase_order() -> None:
    """``assert_purchases_allowed`` before ``assert_readwrite`` violates the narrower-error contract."""
    src = (
        "from gandi_mcp.tools._common import assert_readwrite, assert_purchases_allowed\n"
        "async def t(ctx):\n"
        "    try:\n"
        '        assert_purchases_allowed(ctx, "x")\n'
        '        assert_readwrite(ctx, "x")\n'
        "        return None\n"
        "    except Exception:\n"
        "        raise\n"
    )
    tree, func = _parse_module_and_tool(src)
    try_node = _first_try(func)
    assert try_node is not None
    ok, _ = _gate_sequence_starting_try(try_node, tree, [WRITE_ASSERT, PURCHASE_ASSERT])
    assert ok is False


def test_first_stmt_walker_rejects_purchase_tool_missing_purchase_gate() -> None:
    """A purchase tool with only the write gate must fail the sequence check."""
    src = (
        "from gandi_mcp.tools._common import assert_readwrite\n"
        "async def t(ctx):\n"
        "    try:\n"
        '        assert_readwrite(ctx, "x")\n'
        "        return None\n"
        "    except Exception:\n"
        "        raise\n"
    )
    tree, func = _parse_module_and_tool(src)
    try_node = _first_try(func)
    assert try_node is not None
    ok, reason = _gate_sequence_starting_try(try_node, tree, [WRITE_ASSERT, PURCHASE_ASSERT])
    assert ok is False
    assert "at least 2" in reason or "assert_purchases_allowed" in reason


def test_first_stmt_walker_accepts_aliased_gate_in_first_position() -> None:
    """The first-stmt check composes with #72: an aliased name in `try.body[0]` is OK."""
    src = (
        "from gandi_mcp.tools._common import assert_readwrite as assert_rw\n"
        "async def t(ctx):\n"
        "    try:\n"
        '        assert_rw(ctx, "x")\n'
        "        return None\n"
        "    except Exception:\n"
        "        raise\n"
    )
    tree, func = _parse_module_and_tool(src)
    try_node = _first_try(func)
    assert try_node is not None
    ok, _ = _gate_sequence_starting_try(try_node, tree, [WRITE_ASSERT])
    assert ok


def test_first_stmt_walker_rejects_unknown_canonical() -> None:
    """``_is_gate_call`` rejects a typoed canonical to mirror ``_function_calls_gate``."""
    tree = ast.parse("from gandi_mcp.tools._common import assert_readwrite\n")
    fake_call = ast.parse('assert_readwrite(ctx, "x")', mode="eval").body
    with pytest.raises(ValueError, match="Unknown canonical gate name"):
        _is_gate_call(fake_call, tree, "assert_something_else")
