# Live Contract Tests + 90% Coverage Floor

## Status

Draft — 2026-05-12 (revalidated against codebase same day).

## Goal

Lift per-file source coverage on every `src/gandi_mcp/**/*.py` to >=90% by introducing a contract-test tier (T3) that replays VCR cassettes recorded against the real Gandi v5 API. Replace the current split per-file gate (70% for `tools/*.py`, 90% for four core files) with a unified 90% floor.

## Non-goals

- Recording purchase endpoints (cost / approval scope).
- Automated cassette refresh in CI (drift risk + state churn on real domain).
- Replacing the mocked tier (T2) — cassettes complement, not replace, the synthetic mocked tests.
- Live tests in CI on every run (already covered by `tests/integration/test_live_smoke.py` for release gating).

## Background

Current state on `main` (`df1bcd3` + #98 + #99):

- Total: 88.20% (gate at 85%).
- Per-file gates: 70% for `src/gandi_mcp/tools/`, 90% for `clients/base.py`, `errors.py`, `server.py`, `config.py`.
- `clients/gandi.py`: **37%** — typed wrapper over v5 REST API, not exercised by any test.
- `tools/*.py`: 74-79% — uncovered lines are exclusively the `except Exception as e: handle_client_error(e)` paths in each tool handler.
- T3 marker `contract` declared in `pyproject.toml` but no tests use it. `pytest-recording-0.13.4` already in dev deps.
- A test domain `teamrocket.network` is referenced in `pyproject.toml` for live tests.

## Approach

VCR cassettes via `pytest-recording`. YAML files committed to git. `make refresh-cassettes` re-records against teamrocket.network. CI replays only (`--record-mode=none`). Secrets never touch CI.

Alternatives rejected:

- **respx replay with JSON fixtures.** Looser drift detection, more custom code; VCR's YAML diff is reviewer-friendly.
- **Pact consumer-driven contracts.** Overkill for a single-consumer MCP server; broker overhead unjustified.
- **Live API in CI.** Flaky on Gandi uptime, rate-limit budget exhaustion, write tests off-limits, possible ToS issue.

## Architecture

### Tier layout

```
tests/
├── unit/          T1 — pure unit
├── mocked/        T2 — respx + synthetic JSON, full tool-body coverage
├── contract/      T3 — NEW — VCR cassettes of real Gandi responses (replay-only in CI)
│   ├── conftest.py
│   ├── cassettes/
│   │   ├── domain/*.yaml
│   │   ├── livedns/*.yaml
│   │   ├── email/*.yaml
│   │   ├── billing/*.yaml
│   │   ├── organization/*.yaml
│   │   └── certificate/*.yaml
│   ├── test_domain.py
│   ├── test_livedns.py
│   ├── test_email.py
│   ├── test_billing.py
│   ├── test_organization.py
│   └── test_certificate.py
├── integration/   T4 — live smoke (already exists, 1 test)
└── property/      hypothesis
```

### Test pattern

Contract tests exercise `clients/gandi.py` methods directly with a real `GandiClient` against a real base URL. `pytest-recording` intercepts at the HTTP layer and either records (when `--record-mode=once` and cassette missing) or replays (when cassette present).

```python
# tests/contract/test_domain.py
import pytest
from gandi_mcp.clients.gandi import GandiClient

pytestmark = pytest.mark.contract

@pytest.mark.vcr
async def test_list_domains_returns_array_with_fqdn_field(client: GandiClient):
    result = await client.list_domains()
    assert isinstance(result, list)
    assert all("fqdn" in d for d in result)

@pytest.mark.vcr
async def test_get_domain_existing_returns_full_record(client: GandiClient):
    result = await client.get_domain("teamrocket.network")
    assert result["fqdn"] == "teamrocket.network"
    assert "nameservers" in result
```

### Scope

- **In scope:** All 34 read endpoints + all 29 non-purchasing write endpoints (per README and tag inventory: `gandi_*` 71 tools = 34 read / 29 write / 8 purchase; `GandiClient` exposes 70 corresponding methods). Writes mutate `teamrocket.network` and are accepted churn.
- **Out of scope:** The 8 purchase endpoints (`gandi_domain_register`, `gandi_email_create_mailbox_slot`, `gandi_cert_request`, etc.). These remain mocked-only with synthetic JSON; the per-file gate of >=90 % on `tools/*.py` is met for these via the error-path mocked tests (see below).

### Write-test cleanup matrix

Writes split into two categories by reversibility. Each contract write test must pick a strategy from this matrix:

| Category | Examples | Cleanup |
|---|---|---|
| **Self-inverse pairs** (preferred) | `create_record` + `delete_record`, `add_dnssec_key` + `delete_dnssec_key`, `create_mailbox` + `delete_mailbox`, `create_glue_record` + `delete_glue_record` | Test creates and deletes within the same function; cassette captures both calls. No conftest-level snapshot needed. |
| **Snapshot-and-restore** | `set_nameservers`, `update_autorenew`, `update_mailbox`, `set_contact` | Conftest-level fixture reads current state at session start, yields, restores at session end. Snapshot lives in `tests/contract/snapshots/` (gitignored) and only matters during `make refresh-cassettes`. CI replays don't touch live state, so no snapshot needed in CI. |
| **Effectively-irreversible** | `update_zone` (replaces all records), `update_contact` (registrant change with WHOIS implications) | Excluded from contract recording. Stay mocked-only. Document in this matrix so a future contributor doesn't try to add a cassette. |

### Error-path coverage

The 21-26 % per-file gap in `tools/*.py` is dominated by `except Exception as e: handle_client_error(e)` lines. These are best driven by mocked tests, not cassettes — recording a real 429 is flaky, recording a 404 requires intentional bad input.

The mapping logic itself is already tested exhaustively in `tests/unit/test_errors_mapping_properties.py` (hypothesis-driven over the status-code domain) and in `tests/unit/test_handle_client_error.py`. The remaining gap is *just executing the line in each tool body*. A single error-path test per tool suffices:

```python
# tests/mocked/test_<module>_error_paths.py
async def test_get_domain_handles_404(mocked_client, respx_mock, ctx):
    respx_mock.get("/v5/domain/domains/example.com").mock(
        return_value=httpx.Response(404, json={"cause": "domain not found"}),
    )
    with pytest.raises(ToolError):
        await gandi_domain_get_domain(ctx, "example.com")
```

Approximately one test per tool × 71 tools = **~71 new mocked tests**, not 350. Cheap (no I/O), deterministic, exercises the `except` branch in every handler. The exact status chosen per tool is whichever flows through naturally for that endpoint (404 for `get_*`, 409 for `create_*` collisions, 400 for `update_*` validation, etc.) — pick one that the real API would actually return.

## Coverage gate change

`scripts/check_coverage_thresholds.py` and CI workflow:

- `--cov-fail-under` 85 → **90**.
- Per-file map collapses to a single rule: every `src/gandi_mcp/**/*.py` >=90%. `clients/gandi.py` added to the per-file list explicitly.
- `PER_DIR_THRESHOLDS` removed; the per-file rule covers `tools/`.

After both T3 cassettes and error-path mocked tests land, projected per-file coverage:

| File | Current | Projected | Driver |
|---|---:|---:|---|
| `clients/gandi.py` | 37 % | 90 %+ | T3 cassettes per endpoint (63 of 70 methods recorded; 8 purchase methods excluded but covered via mocked tests already) |
| `tools/billing.py` | 77 % | 92 %+ | error-path mocked (one test per tool) |
| `tools/certificate.py` | 79 % | 92 %+ | error-path mocked |
| `tools/domain.py` | 75 % | 90 %+ | error-path mocked (largest file, smallest projected lift — 28 tools to cover) |
| `tools/email.py` | 77 % | 92 %+ | error-path mocked |
| `tools/livedns.py` | 74 % | 90 %+ | error-path mocked |
| `tools/organization.py` | 74 % | 92 %+ | error-path mocked |
| Others | >=97 % | unchanged | already over |

Total projected: ~92-93 %. If `clients/gandi.py` or `tools/domain.py` lands below 90 %, PR E does not merge; instead identify the specific uncovered lines (typically conditional branches like `if params: ...`) and either add targeted tests or document the line as unreachable.

## Library compatibility note

`vcrpy==8.1.1` (already a transitive dep via `pytest-recording==0.13.4`) does NOT ship a `vcr.stubs.httpx_stubs` module — `from vcr.stubs import httpx_stubs` raises `ImportError`. Despite this, VCR.py 8.x intercepts `httpx.AsyncClient` for both record and replay via its socket-level patcher; this is empirically verified on this codebase (`uv run python -c "import vcr, httpx, asyncio; ..."` records and replays cleanly). Future maintainers who see the missing `httpx_stubs` import should not assume VCR lacks httpx support — it has it, just without a dedicated stub module name. Pin `vcrpy>=8.1` to keep this behavior.

## Cassette redaction + secrets

`tests/contract/conftest.py` configures VCR via the `vcr_config` fixture (pytest-recording's hook):

```python
import json

@pytest.fixture(scope="session")
def vcr_config():
    return {
        "cassette_library_dir": "tests/contract/cassettes",
        "filter_headers": ["authorization", "x-api-key", "cookie", "set-cookie"],
        "filter_query_parameters": ["sharing_id"],
        "before_record_response": _redact_response,
        "record_mode": "none",  # CI default; CLI --record-mode=once overrides
        "match_on": ["method", "scheme", "host", "port", "path", "query"],
    }

# JSON-path redactor. Targeted by key, not by regex on the entire body, so DNS
# record IDs and other legitimate UUIDs survive intact for assertions.
_PII_JSON_PATHS = (
    ("customer", "id"),
    ("owner", "id"),
    ("registrant", "email"),
    ("registrant", "phone"),
    ("registrant", "streetaddr"),
    ("billing", "iban"),
)

def _redact_response(response):
    try:
        body = json.loads(response["body"]["string"])
    except (ValueError, KeyError):
        return response
    for path in _PII_JSON_PATHS:
        _redact_path(body, path)
    response["body"]["string"] = json.dumps(body).encode("utf-8")
    return response

def _redact_path(obj, path):
    cur = obj
    for key in path[:-1]:
        if not isinstance(cur, dict) or key not in cur:
            return
        cur = cur[key]
    if isinstance(cur, dict) and path[-1] in cur:
        cur[path[-1]] = "REDACTED"
```

`filter_headers` strips the Bearer PAT and any cookies. `filter_query_parameters` strips the operator's `sharing_id`. JSON-path redactor scrubs only known PII fields — leaves response IDs that tests may assert against.

### `sharing_id` matcher interaction

VCR's default `match_on` includes `query`. We strip `sharing_id` from the cassette URL via `filter_query_parameters`. For replay to match, the request issued by the test must also lack `sharing_id`. Enforce this by constructing the test `GandiClient` with `sharing_id=None` (see `_live_client` fixture below) regardless of any ambient `GANDI_SHARING_ID` env var. Document this invariant inline in `tests/contract/conftest.py`.

```python
@pytest.fixture
def client() -> GandiClient:
    # sharing_id intentionally None: contract cassettes elide it via filter_query_parameters,
    # so the replayed request must also lack it for the URL matcher to hit.
    return GandiClient(
        base_url="https://api.gandi.net",
        token=os.environ.get("GANDI_TOKEN", "REDACTED"),  # only used at record time
        sharing_id=None,
        timeout=10,
        max_retries=1,
    )
```

### Recording flow

```
make refresh-cassettes:
    @# Stage to a sibling dir so a mid-run failure doesn't leave the
    @# committed cassettes in a half-deleted state.
    rm -rf tests/contract/cassettes.new
    mkdir -p tests/contract/cassettes.new
    GANDI_TOKEN=$(pass show gandi/pat-sandbox) \
        GANDI_TEST_DOMAIN=teamrocket.network \
        VCR_CASSETTE_DIR=tests/contract/cassettes.new \
        uv run pytest tests/contract/ --record-mode=once -p no:cacheprovider
    @# Only swap on full success.
    rm -rf tests/contract/cassettes
    mv tests/contract/cassettes.new tests/contract/cassettes
    @echo "Review the diff before committing."
```

`VCR_CASSETTE_DIR` is read by `tests/contract/conftest.py` and overrides the default `cassette_library_dir`. If pytest exits non-zero, the old cassettes are still in place and the new ones are left under `.new` for inspection.

Sandbox PAT is scoped to `teamrocket.network` at the Gandi console (least-privilege; the PAT is created with only domain-level scope, no billing or account-wide scope). Even if a cassette leaks an un-stripped token, blast radius is one test domain.

### Staleness check

```
make check-cassettes-fresh:
    @find tests/contract/cassettes -name '*.yaml' -mtime +180 -print | \
        awk 'NR { print "STALE: " $$0 } END { if (NR) exit 1 }'
```

Non-blocking CI step posts a comment if cassettes are >180 days old.

## CI changes

`.github/workflows/ci.yml`:

- `test` job: same as today plus T3 directory included by default (`testpaths` already covers `tests/`).
- New step in `test` job after pytest: `make check-cassettes-fresh || echo "::warning::Some cassettes are >180 days old, run make refresh-cassettes locally"`.
- No new job. No secrets. Replay-only.

## Migration order

1. **PR A** — Scaffold T3 + redaction. `tests/contract/conftest.py`, `tests/contract/cassettes/.gitkeep`, `Makefile` with `refresh-cassettes` / `check-cassettes-fresh`. No test files yet. No coverage-gate change. CI green at current 88.20%.
2. **PR B** — Record cassettes + add T3 tests for `clients/gandi.py` reads. Cassettes committed. `clients/gandi.py` coverage jumps to ~70%.
3. **PR C** — Record cassettes for non-purchasing writes. `clients/gandi.py` coverage to ~90%+.
4. **PR D** — Add error-path mocked tests across all six tool modules. `tools/*.py` coverage to ~93%+.
5. **PR E** — Bump coverage gate: `--cov-fail-under=90`; collapse per-file rules to a unified 90% floor; add `clients/gandi.py` to the per-file list.

Each PR independent. PR E only merges when measured numbers support it.

## Testing the design itself

- After PR A: `make refresh-cassettes` records one cassette (e.g. `test_user_info_round_trip`), confirms redaction strips the PAT and operator UUIDs.
- After each subsequent PR: re-record cassettes touched by that PR, eyeball the YAML diff for any unexpected data.
- After PR E: temporarily delete a cassette file; CI should fail with "cassette missing" not silently pass.
- After PR E: temporarily drop `clients/gandi.py` coverage; CI should fail with the readable per-file message from `scripts/check_coverage_thresholds.py`.

## Risks

- **Cassette PII leak.** Mitigated by the JSON-path response redactor + `filter_headers` + `filter_query_parameters`. Each PR's cassette diff is reviewable in YAML. Reviewers must scan for non-redacted PII before approving the refresh PR; this is called out in the PR template.
- **Cassette drift from API changes.** Caught by the staleness check at 180 days + by any contract test failing on field removal during refresh. Operator workflow: refresh, eyeball diff, commit. A failing replay in CI means either (a) a real API change Gandi made — refresh and re-record, or (b) a test was updated without re-recording — re-record and commit.
- **`teamrocket.network` state churn.** Write tests create / update / delete DNS records (and similar) on this domain. Acceptable trade-off — the domain is explicitly a test domain. Test record names use the prefix `_contract-<uuid8>.` so a partial cleanup never collides with prod-style records on the same zone and is identifiable for manual sweeping.
- **Sandbox PAT scope.** Must be created with a per-domain scope at the Gandi console (`teamrocket.network` only), no billing scope. Documented in `CONTRIBUTING.md` under a new "Recording contract cassettes" section.
- **VCR.py upstream changes.** httpx interception in vcrpy 8.x relies on a socket-level patch rather than a documented `httpx_stubs` module. Future vcrpy versions could change this. Pin `vcrpy>=8.1,<9` and watch their changelog at refresh time; if 9.x ships a breaking change, the migration is contained to `tests/contract/conftest.py`.
- **Matcher mismatch from sharing_id.** `filter_query_parameters=["sharing_id"]` strips it from cassettes, so the test client must also be built with `sharing_id=None`. Enforced by the `client` fixture and called out inline; a developer who copies the fixture and adds `sharing_id` will get cassette-replay misses in CI rather than silent passes.

## Out of scope

- Mutation testing reaching purchase endpoints (no live recording).
- VCR record-mode `new_episodes` (allows additive append) — manual `make refresh-cassettes` is the only path that touches live API.
- Cassette compression / shared-fixture deduplication — yaml diff readability beats minor disk savings.
