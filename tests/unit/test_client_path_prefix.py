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


def _assignments_to(method: ast.AsyncFunctionDef, name: str) -> list[ast.expr]:
    found: list[ast.expr] = []
    for node in ast.walk(method):
        if isinstance(node, ast.Assign):
            found.extend(node.value for target in node.targets if isinstance(target, ast.Name) and target.id == name)
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            found.append(node.value)
    return found


def _local_resolves_to_v5_prefix(method: ast.AsyncFunctionDef, name: str) -> bool:
    """A local ``name`` resolves to a ``/v5/``-prefixed string.

    Requires at least one bootstrap assignment that begins with ``/v5/`` and
    every other assignment to be either another bootstrap or an extension of
    the same name (``f"{name}/..."``).
    """
    assignments = _assignments_to(method, name)
    if not assignments:
        return False
    has_bootstrap = any(_starts_with_prefix(v) for v in assignments)
    all_ok = all(_starts_with_prefix(v) or _is_self_extension(v, name) for v in assignments)
    return has_bootstrap and all_ok


def _path_arg_is_safe(method: ast.AsyncFunctionDef, call: ast.Call) -> bool:
    if not call.args:
        return False
    arg = call.args[0]
    if _starts_with_prefix(arg):
        return True
    if isinstance(arg, ast.Name):
        return _local_resolves_to_v5_prefix(method, arg.id)
    return False


def test_all_client_paths_start_with_v5() -> None:
    """Every ``self.<http>(path, ...)`` call uses a ``/v5/``-prefixed path."""
    tree = ast.parse(inspect.getsource(gandi))
    offenders: list[str] = []
    checked = 0
    for method in ast.walk(tree):
        if not isinstance(method, ast.AsyncFunctionDef):
            continue
        for node in ast.walk(method):
            if not _is_self_http_call(node):
                continue
            checked += 1
            if not _path_arg_is_safe(method, node):
                offenders.append(f"{method.name}: {ast.unparse(node)}")
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
