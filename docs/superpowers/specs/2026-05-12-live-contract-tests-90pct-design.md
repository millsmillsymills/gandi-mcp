# Live Contract Tests + 90% Coverage Floor

## Status

Draft — 2026-05-12.

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

- **In scope:** All ~40 read endpoints + all ~25 non-purchasing write endpoints. Writes mutate teamrocket.network and are accepted churn (DNS records get created/updated/deleted within a single test class then restored in teardown).
- **Out of scope:** Purchase endpoints (`gandi_domain_register`, `gandi_email_create_mailbox_slot`, `gandi_cert_request`). These remain mocked-only with synthetic JSON; the existing per-file gate of 90% on `tools/*.py` is met via the error-path mocked tests (see below).

### Error-path coverage

The 25%-ish per-file gap in `tools/*.py` is dominated by `except Exception as e: handle_client_error(e)` lines. These are best driven by mocked tests, not cassettes — recording a real 429 is flaky, recording a 404 requires intentional bad input. Add parametrised mocked tests:

```python
# tests/mocked/test_<module>_error_paths.py
@pytest.mark.parametrize(
    "status,exc",
    [(400, GandiBadRequestError), (404, GandiNotFoundError),
     (409, GandiConflictError), (429, GandiRateLimitError),
     (500, GandiServerError)],
)
async def test_get_domain_translates_error(status, exc, mocked_client, respx_mock, ctx):
    respx_mock.get("/v5/domain/domains/example.com").mock(
        return_value=httpx.Response(status, json={"cause": "synthetic"}),
    )
    with pytest.raises(ToolError):
        await gandi_domain_get_domain(ctx, "example.com")
```

Two tests per status × ~70 tools ≈ 350 new mocked tests. Cheap (no I/O), deterministic, catches every error-handler line.

## Coverage gate change

`scripts/check_coverage_thresholds.py` and CI workflow:

- `--cov-fail-under` 85 → **90**.
- Per-file map collapses to a single rule: every `src/gandi_mcp/**/*.py` >=90%. `clients/gandi.py` added to the per-file list explicitly.
- `PER_DIR_THRESHOLDS` removed; the per-file rule covers `tools/`.

After both T3 cassettes and error-path mocked tests land, projected per-file coverage:

| File | Current | Projected | Driver |
|---|---:|---:|---|
| `clients/gandi.py` | 37% | 90%+ | T3 cassettes per endpoint |
| `tools/billing.py` | 77% | 95%+ | error-path mocked |
| `tools/certificate.py` | 79% | 95%+ | error-path mocked |
| `tools/domain.py` | 75% | 92%+ | error-path mocked |
| `tools/email.py` | 77% | 95%+ | error-path mocked |
| `tools/livedns.py` | 74% | 93%+ | error-path mocked |
| `tools/organization.py` | 74% | 95%+ | error-path mocked |
| Others | >=97% | unchanged | already over |

Total projected: ~93%.

## Cassette redaction + secrets

`tests/contract/conftest.py` configures VCR:

```python
def vcr_config():
    return {
        "cassette_library_dir": "tests/contract/cassettes",
        "filter_headers": ["authorization", "x-api-key", "cookie"],
        "filter_query_parameters": ["sharing_id"],
        "before_record_response": _redact_response,
        "record_mode": "none",  # CI default; --record-mode=once overrides
    }

def _redact_response(response):
    body = response["body"]["string"].decode("utf-8", errors="ignore")
    body = re.sub(r'"id"\s*:\s*"[0-9a-f-]{36}"',
                  '"id": "00000000-0000-0000-0000-000000000000"', body)
    body = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
                  'redacted@example.com', body)
    body = re.sub(r'(?<!\w)([A-Z]{2}\d{2}[A-Z0-9]{4,30})(?!\w)',
                  'REDACTED_IBAN', body)
    response["body"]["string"] = body.encode("utf-8")
    return response
```

`filter_headers` strips the Bearer PAT. `filter_query_parameters` strips the operator's `sharing_id`. Response redactor scrubs customer UUIDs, email addresses, IBANs from response bodies.

### Recording flow

```
make refresh-cassettes:
    rm -rf tests/contract/cassettes
    GANDI_TOKEN=$(pass show gandi/pat-sandbox) \
        GANDI_TEST_DOMAIN=teamrocket.network \
        uv run pytest tests/contract/ --record-mode=once -p no:cacheprovider
    @echo "Review the diff before committing."
```

Sandbox PAT is scoped to teamrocket.network at the Gandi console. Even if a cassette leaks an un-stripped token, blast radius is one test domain.

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

- **Cassette PII leak.** Mitigated by the response redactor + `filter_headers`. Each PR's cassette diff is reviewable in YAML.
- **Cassette drift from API changes.** Caught by the staleness check at 180 days + by any contract test failing on field removal during refresh. Operator workflow is: refresh, eyeball diff, commit.
- **teamrocket.network state churn.** Write tests register/update/delete DNS records on this domain. Acceptable trade-off — domain is explicitly a test domain. Each test class uses a unique prefix (`test-<uuid>.teamrocket.network`) so concurrent local refreshes don't collide.
- **Sandbox PAT scope.** Must be scoped to teamrocket.network only at the Gandi console, not full-account. Documented in `CONTRIBUTING.md`.

## Out of scope

- Mutation testing reaching purchase endpoints (no live recording).
- VCR record-mode `new_episodes` (allows additive append) — manual `make refresh-cassettes` is the only path that touches live API.
- Cassette compression / shared-fixture deduplication — yaml diff readability beats minor disk savings.
