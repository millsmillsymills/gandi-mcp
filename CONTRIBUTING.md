# Contributing

Thanks for contributing to gandi-mcp!

## Branch protection

The `main` branch requires:
- Pull request before merge
- Status checks: `static`, `test (3.13)`, `audit`
- Linear history (no merge commits)
- No force-push

Configure in GitHub Settings -> Branches -> "Add branch protection rule" for `main`.

## Local development

```bash
uv sync --extra dev
uv run pre-commit install
```

### Test tiers

| Tier | Command | Network | Notes |
|---|---|---|---|
| Unit + mocked + contract | `uv run pytest -m "not live"` | None | Default; runs in CI |
| Live (read + safe writes) | `GANDI_MCP_LIVE_TESTS=1 GANDI_TOKEN=$PAT uv run pytest -m live` | Real Gandi | See `tests/live/README.md` (Phase 3) |
| Smoke (release gate) | `GANDI_MCP_LIVE_TESTS=1 GANDI_TOKEN=$PAT uv run pytest -m smoke` | Real Gandi | See `RELEASE.md` (Phase 4) |

### Recording contract cassettes

Tier-3 contract tests under `tests/contract/` replay YAML cassettes recorded
against `api.gandi.net`. CI never hits the live API; replay-only.

**To re-record after a Gandi API change:**

1. Create a sandbox Personal Access Token at https://account.gandi.net/, scoped
   **only** to the `teamrocket.network` test domain. Do not use a full-account
   PAT — the cassettes will contain less-redacted data and a leak would be more
   damaging.
2. Store the PAT in your password manager (`pass insert gandi/pat-sandbox` or
   equivalent). Never commit it.
3. Run:
   ```bash
   GANDI_TOKEN=$(pass show gandi/pat-sandbox) make refresh-cassettes
   ```
   The target stages new cassettes under `tests/contract/cassettes.new/` and
   only swaps them in on full success.
4. Review the diff:
   ```bash
   git diff -- tests/contract/cassettes/
   ```
   Scan for any unredacted PII (real email addresses, IBANs, customer UUIDs
   outside the redacted JSON paths). If you spot any, extend
   `tests/contract/_redact.py`'s `PII_JSON_PATHS` rather than hand-editing the
   cassette.
5. Commit the cassette diff in its own commit so reviewers can focus on it.

**Stale cassettes.** `make check-cassettes-fresh` fails if any cassette is
older than 180 days. CI runs this as a non-blocking warning. Plan to refresh
quarterly, or whenever a contract test fails on a field shape change.

**What gets redacted.**
`filter_headers` strips the `Authorization` bearer token and any cookies.
`filter_query_parameters` strips the `sharing_id` URL parameter.
The JSON-path response redactor (`tests/contract/_redact.py`) scrubs the
following keys: `customer.id`, `owner.id`, `registrant.email`,
`registrant.phone`, `registrant.streetaddr`, `billing.iban`. Other UUIDs
(DNS record IDs, mailbox IDs, the resource's own `id`) survive — tests may
assert against them.

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

### Code style

- `ruff format` formats; `ruff check` lints
- `uv run ty check src/gandi_mcp/` for type checking
- Run `uv run pre-commit run --all-files` before committing

### Commits

- Imperative mood, <=72 char subject line
- One logical change per commit
- Co-author tag for AI-assisted contributions

## Mutation testing (local)

We use [mutmut](https://mutmut.readthedocs.io/) to verify the unit test suite catches semantic bugs, not just line execution. Mutation testing intentionally introduces small code changes ("mutants") — if the test suite still passes against the mutated code, that mutant **survived** and points to a test gap.

Mutation testing is **local only** — it's too slow for CI. The configuration in `pyproject.toml` (`[tool.mutmut]`) scopes mutation to the four highest-value modules:

- `src/gandi_mcp/clients/base.py` — request plumbing, retry policy, error mapping
- `src/gandi_mcp/errors.py` — exception hierarchy + `handle_client_error`
- `src/gandi_mcp/server.py` — lifespan, visibility gating, mode/purchase plumbing
- `src/gandi_mcp/tools/_common.py` — runtime safety-gate asserts

### Running

```bash
# Full baseline (~15-30 s on a developer laptop)
uv run mutmut run

# Inspect the per-mutant outcome list
uv run mutmut results

# Show the diff for a specific surviving mutant
uv run mutmut show gandi_mcp.clients.base.xǁBaseGandiClientǁ_parse_json__mutmut_5
```

`mutmut` mirrors the source tree to `mutants/` (gitignored), patches one mutant at a time, and reruns `pytest tests/unit/`. A surviving mutant is one where every unit test still passed despite the mutation.

### Interpreting results

| Outcome | Meaning |
|---|---|
| 🎉 killed | A test failed when the mutant was patched in — the test suite catches this class of bug. |
| 🙁 survived | All tests passed with the mutant — likely a test gap or an equivalent (no-op) mutant. |
| 🫥 no_tests | No test exercised this code path — either dead code or missing coverage. |
| ⏰ timeout | The mutant induced an infinite loop / hang; treat as a kill. |
| 🤔 suspicious | Test infrastructure failed for reasons unrelated to the mutation. Re-run before drawing a conclusion. |

### Killing surviving mutants

For each survivor, ask:

1. **Is the mutation behaviorally equivalent?** (e.g. `+= 0`, reordering independent statements, replacing `max(0, x)` with `max(x, 0)` when both branches are unreachable.) Document as equivalent and move on.
2. **Does it expose a real test gap?** Add a focused unit test that fails against the mutant. Prefer asserting the specific behavior — extending an existing test with another `assert` is often enough.
3. **Is the surviving code dead?** Delete it.

### Equivalent mutants

Survivors documented here are behaviourally equivalent to the original source — no test can kill them without inspecting the bytecode itself. Listed so reviewers don't waste a turn re-investigating each baseline.

`clients/base.py`:

- `__init____mutmut_1` (`timeout: int = 30` -> `timeout: int = 31`) and `__init____mutmut_2` (`max_retries: int = 3` -> `max_retries: int = 4`): mutmut's trampoline rewrites `__init__` to forward `kwargs={'timeout': timeout, 'max_retries': max_retries, ...}` from the *outer* `__init__` signature into the mutant function. The outer defaults (30 / 3) are baked into the wrapper, so the mutant function's own default value is never used. No call site that goes through `BaseGandiClient(...)` can observe the mutated default — architecturally equivalent under mutmut, not a real test gap.
- `_parse_json__mutmut_12` — drops `status_code=None` from the invalid-JSON `GandiError(...)` call. The default value of `status_code` on `GandiError.__init__` is already `None`, so passing it explicitly versus omitting it produces the same exception state.
- `get__mutmut_8` / `post__mutmut_8` / `put__mutmut_8` / `patch__mutmut_8` / `delete__mutmut_8` — change the literal method string from upper-case (`"GET"`) to lower-case (`"get"`). The string passes through three normalisers before it can be observed: `_request` does `method.upper() in ("GET", "HEAD")` for the retry-class decision, `httpx.Request` upper-cases `method` before sending, and `GandiTimeoutError.__init__` upper-cases the `method` it stores on the exception. Every observable surface (wire-method, retry policy, timeout-error string) is identical for `"GET"` and `"get"`.

### Current baseline (2026-05-12)

| Module | Mutants | Survived | No-tests | Notes |
|---|---:|---:|---:|---|
| `clients/base.py` | (large) | 59 | 0 | Most survivors are `__init__` defaults and `_request` retry-config branches; tests assert behavior, not constructor internals. |
| `errors.py` | 42 | 0 | 0 | 100 % kill rate. Every `handle_client_error` message substring + every typed-exception `__init__` is pinned. |
| `server.py` | 58 | 0 | 0 | 100 % kill rate. The three former `create_server` lifespan-wiring survivors (`lifespan=None`, `lifespan=_build_lifespan(None)`, kwarg removed) are now pinned via `TestCreateServerLifespanWiring` in `tests/unit/test_server_messages.py`. |
| `tools/_common.py` | 18 | 0 | 0 | 100 % kill rate. The two message-string survivors in `assert_readwrite` / `assert_purchases_allowed` are now pinned via `test_error_message_is_canonical` (exact-equality on the full f-string) in `tests/unit/test_tools_common.py`. |
| **Total** | **306** | **59** | **0** | **80.7 % kill rate overall.** |

Open follow-ups (kill remaining survivors on a per-module basis):

- #83 — `clients/base.py` survivors

CI integration of mutation testing is deferred — runs take long enough that gating on them would slow PRs significantly.
