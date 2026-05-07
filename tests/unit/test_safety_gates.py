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
"""

from __future__ import annotations

import ast
import pathlib

TOOLS_DIR = pathlib.Path(__file__).resolve().parents[2] / "src" / "gandi_mcp" / "tools"
SKIP_FILES = frozenset({"__init__.py", "_common.py"})

WRITE_TAG = "write"
PURCHASE_TAG = "purchase"

WRITE_ASSERT = "assert_readwrite"
PURCHASE_ASSERT = "assert_purchases_allowed"


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


def _iter_tool_functions() -> list[tuple[pathlib.Path, ast.AsyncFunctionDef]]:
    """Every ``async def`` decorated with ``@mcp.tool(...)`` under ``tools/``."""
    found: list[tuple[pathlib.Path, ast.AsyncFunctionDef]] = []
    for path in sorted(TOOLS_DIR.glob("*.py")):
        if path.name in SKIP_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found.extend(
            (path, node) for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and _function_tags(node)
        )
    return found


def test_every_write_tool_calls_assert_readwrite() -> None:
    """A tool tagged ``"write"`` must call ``assert_readwrite`` in its body."""
    offenders: list[str] = []
    write_count = 0
    for path, node in _iter_tool_functions():
        tags = _function_tags(node)
        if WRITE_TAG not in tags:
            continue
        write_count += 1
        if not _calls_named(node, WRITE_ASSERT):
            offenders.append(f"{path.name}::{node.name}")
    assert not offenders, f"write-tagged tools missing {WRITE_ASSERT}(): {offenders}"
    assert write_count > 0, "AST walker found no write-tagged tools — test is a no-op"


def test_every_purchase_tool_calls_assert_purchases_allowed() -> None:
    """A tool tagged ``"purchase"`` must call ``assert_purchases_allowed`` in its body."""
    offenders: list[str] = []
    purchase_count = 0
    for path, node in _iter_tool_functions():
        tags = _function_tags(node)
        if PURCHASE_TAG not in tags:
            continue
        purchase_count += 1
        if not _calls_named(node, PURCHASE_ASSERT):
            offenders.append(f"{path.name}::{node.name}")
    assert not offenders, f"purchase-tagged tools missing {PURCHASE_ASSERT}(): {offenders}"
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
    for path, node in _iter_tool_functions():
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
    """``self.assert_readwrite(...)`` is not the same function — must be a bare ``Name``."""
    src = 'async def t(ctx):\n    self.assert_readwrite(ctx, "x")\n'
    assert not _calls_named(_parse_tool(src), "assert_readwrite")


def test_calls_named_returns_false_when_absent() -> None:
    src = "async def t(ctx):\n    return await client.write(ctx)\n"
    assert not _calls_named(_parse_tool(src), "assert_readwrite")
