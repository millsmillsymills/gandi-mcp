# Contributing

Thanks for contributing to gandi-mcp!

## Branch protection

The `main` branch requires:
- Pull request before merge
- Status checks: `static`, `test (3.11)`, `test (3.12)`, `test (3.13)`, `audit`
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

### Re-recording contract cassettes (Phase 2)

See `tests/contract/README.md` once Phase 2 lands.

### Code style

- `ruff format` formats; `ruff check` lints
- `mypy --strict` for type checking
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

### Current baseline (2026-05-12, branch `chore/mutmut-baseline`)

| Module | Mutants | Killed | Survived | No-tests | Notes |
|---|---:|---:|---:|---:|---|
| `clients/base.py` | (large) | — | 66 | 0 | Most survivors are `__init__` defaults and `_request` retry-config branches; tests assert behavior, not constructor internals. |
| `errors.py` | 42 | — | 11 | 0 | `handle_client_error` survivors are mostly the message-string mutants (the typed exception is asserted, the user-facing string isn't). |
| `server.py` | 58 | — | 35 | 0 | Many survivors live in `_classify_startup_error` and `create_server`; the lifespan tests assert the surfaced exception type, not the intermediate string-building. |
| `tools/_common.py` | 18 | 0 | 0 | 7 | The 7 no-test mutants belong to helpers exercised only via tool-integration tests, which are excluded from the unit suite. |
| **Total** | **301** | **182** | **112** | **7** | **60.5 % kill rate overall.** |

Per-module kill rates are below the 80 % goal. The four follow-up issues track the work:

- #83 — `clients/base.py` survivors
- #84 — `errors.py` survivors
- #85 — `server.py` survivors
- #86 — `tools/_common.py` no-test mutants (lift indirect coverage into unit tests)

This PR establishes the baseline so future contributors have a measurable starting point. CI integration is deferred — runs take long enough that gating on them would slow PRs significantly.
