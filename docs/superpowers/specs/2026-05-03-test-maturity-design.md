# Gandi-MCP Test Maturity Plan

**Status:** Design — approved 2026-05-03
**Author:** Brainstorming session (mills)
**Scope:** Raise test maturity from 52% coverage / 1 tool tested behaviorally to a layered suite covering 100% of tools at the mocked tier, 100% of read tools at the contract tier, and 76% of all tools at the live tier.

## Goals

1. Every tool body has at least mocked-integration coverage asserting arg marshalling, client call, and response shape.
2. Every read tool replays a recorded real Gandi response (contract tier) so API drift fails CI.
3. Every safe tool runs against the real Gandi API and `teamrocket.network` via local opt-in (`pytest -m live`).
4. Add GitHub Actions CI for static checks + non-live tests on every PR/push.
5. Add a smoke release gate (`pytest -m smoke`) — minimal live read, run before each version tag.

## Non-goals

- Live testing of money-spending tools (purchases). Mock-only forever in this scope.
- Live testing of dangerous-but-free tools (`domain_delete`, `domain_set_nameservers`, `domain_update_contacts`, `domain_initiate_ownership_change`, `cert_revoke`). Mock-only.
- Mutation testing (filed as #33).
- Property-based testing (filed as #34).
- Coverage thresholds in CI (filed as #35).

## Test tiers

Five layered tiers. Each catches what others miss.

| Tier | Marker | When | Scope | Network |
|---|---|---|---|---|
| T0 static | n/a | pre-commit + CI | ruff, ruff-format, mypy, bandit, prek hooks, pip-audit, zizmor | none |
| T1 unit | (default) | CI on PR/push | logic in isolation: `_seg`, `_status_view`, retry policy, error mapping, config validation, lifespan branches (existing 108 tests) | none |
| T2 mocked-integration | `mocked` | CI on PR/push | every tool body via `respx` HTTP intercepts. **All 71 tools.** | mocked |
| T3 contract-fixture | `contract` | CI on PR/push | replay recorded real Gandi responses via `pytest-recording` (VCR for httpx). Re-record quarterly. | mocked replay |
| T4 live | `live` | local-only | hits real Gandi API + `teamrocket.network`. 34 read tools + 20 safe writes. | real |
| T4 smoke | `smoke` + `live` | local pre-release | minimal live read suite, ~10 calls, <30s | real |

Default `pytest` runs T0+T1+T2+T3. `pytest -m live` opt-in. CI runs `pytest -m "not live"`.

## Test directory layout

```
tests/
├── conftest.py              # shared fixtures
├── unit/                    # T1 (existing 108 tests, no change)
├── mocked/                  # T2 NEW — one file per tool module
│   ├── test_billing_tools.py
│   ├── test_cert_tools.py
│   ├── test_domain_tools.py
│   ├── test_email_tools.py
│   ├── test_livedns_tools.py
│   └── test_org_tools.py
├── contract/                # T3 NEW — VCR cassettes + replay tests
│   ├── README.md            # re-record procedure
│   ├── cassettes/           # recorded YAML responses, scrubbed
│   └── test_contract_*.py
└── live/                    # T4 NEW — real API tests
    ├── README.md            # env vars + manual prereqs
    ├── conftest.py          # ephemeral fixtures + sweeper + safety guards
    ├── test_live_read.py
    ├── test_live_livedns.py
    ├── test_live_email.py
    ├── test_live_domain_safe.py
    └── test_live_smoke.py
```

## Per-tool coverage matrix

71 tools total = 34 read + 29 non-purchase write + 8 purchase.

### Read tools (34) — 100% live

| Module | Tools |
|---|---|
| organization (5) | `org_get_user_info`, `org_list_organizations`, `org_get_organization`, `org_list_customers`, `org_get_customer` |
| billing (3) | `billing_get_info`, `billing_get_info_for_org`, `billing_get_price_catalog` |
| domain (13) | `domain_list_domains`, `domain_get_domain`, `domain_get_status`, `domain_get_nameservers`, `domain_get_contacts`, `domain_get_renew_info`, `domain_list_dnssec_keys`, `domain_list_glue_records`, `domain_get_glue_record`, `domain_get_claims`, `domain_get_transferin_info`, `domain_get_ownership_change_status`, `domain_check_availability` |
| livedns (6) | `livedns_list_domains`, `livedns_get_domain`, `livedns_list_records`, `livedns_list_nameservers`, `livedns_list_dnssec_keys`, `livedns_list_rrtypes` |
| email (5) | `email_list_mailboxes`, `email_get_mailbox`, `email_list_slots`, `email_get_slot`, `email_list_forwards` |
| cert (2) | `cert_list`, `cert_get` (only if cert exists) |

All 34 covered at T2 + T3 + T4.

### Safe writes (20) — live-tested on `teamrocket.network`

| Tool | Strategy |
|---|---|
| `domain_set_autorenew` | toggle off→on, restore initial |
| `domain_reset_authinfo` | call, assert response shape (rotates code, safe) |
| `domain_create_dnssec_key` / `_delete_dnssec_key` | create+delete cycle, ephemeral |
| `domain_create_glue_record` / `_update_glue_record` / `_delete_glue_record` | full CRUD on `ns-test-{uuid}.teamrocket.network` (read covered above) |
| `livedns_update_domain` | toggle `automatic_snapshots`, restore |
| `livedns_create_record` / `_delete_record` / `_replace_record` | full CRUD with `mcp-test-{uuid}` name |
| `livedns_create_dnssec_key` / `_delete_dnssec_key` | create+delete on test subdomain |
| `email_create_forward` / `_update_forward` / `_delete_forward` | full CRUD: `forward-{uuid}@teamrocket.network` |
| `email_create_mailbox` / `_update_mailbox` / `_delete_mailbox` | uses pre-paid slot; create/delete cycle (read covered above) |
| `email_purge_mailbox` | called on test mailbox after content tests |

Counted: 2 domain toggles + 2 domain dnssec + 3 domain glue + 1 livedns update + 3 livedns record + 2 livedns dnssec + 3 email forward + 3 email mailbox + 1 email purge = **20 writes**. All 20 covered at T2 + T4. Glue/DNSSEC/forward CRUD also at T3 (read parts).

### Mock-only (5 + 4 + 8 = 17)

Never run live. T2 + T3 (read paths where applicable) only.

**Dangerous-even-when-free (5):** `domain_delete`, `domain_set_nameservers`, `domain_update_contacts`, `domain_initiate_ownership_change`, `cert_revoke`.

**Risky bulk (4):** `livedns_add_domain` (one-shot per zone), `livedns_replace_zone` (replaces ALL records), `livedns_delete_all_records` (same), `domain_resend_foa` (sends real email — defer until needed).

**Purchases (8):** `domain_register`, `domain_renew`, `domain_transfer_in`, `cert_issue`, `cert_renew`, `email_create_slot`, `email_renew_mailbox`, `email_refund_slot`. (Note: `email_refund_slot` is non-spending but only meaningful in purchase context.)

### Net coverage

- Read: 34/34 = 100% live
- Non-purchase writes: 20/29 = 69% live
- **Total live: 54/71 = 76%**
- Mocked + contract (read): 34/34 = 100%
- Mocked (all): 71/71 = 100%

## Live test fixture model

Hybrid approach: long-lived manually-provisioned resources + ephemeral per-test resources.

### Long-lived (manual, documented in `tests/live/README.md`)

| Resource | Why long-lived | Provisioning |
|---|---|---|
| `teamrocket.network` registration | live testing requires owned domain | one-time, manual |
| 1 paid mailbox slot | recreating costs $3/mo each run | one-time `email_create_slot`, manual |
| 1 forward target email | needs real working inbox | none (use dev's main address) |

### Ephemeral (per-test, UUID-prefixed)

- DNS records: `mcp-test-{uuid8}` (TXT/A/CNAME/MX as test demands)
- Glue records: `ns-test-{uuid8}.teamrocket.network`
- Forwards: `forward-{uuid8}@teamrocket.network`
- DNSSEC keys: created on test subdomain, deleted in same test

```python
@pytest.fixture
async def ephemeral_record(live_client, test_domain):
    name = f"mcp-test-{uuid4().hex[:8]}"
    yield name
    with contextlib.suppress(GandiNotFoundError):
        await live_client.livedns_delete_record(test_domain, name, "TXT")
```

Best-effort teardown — wrap in `suppress(GandiNotFoundError)`. Sweeper catches anything missed. Teardown failure must not mask test failure.

### Pre-flight (session start, autouse)

```python
@pytest.fixture(scope="session", autouse=True)
async def live_safety_check(request):
    if "live" not in request.config.getoption("-m", default=""):
        return

    # Guard 1: explicit env opt-in
    if os.environ.get("GANDI_MCP_LIVE_TESTS") != "1":
        pytest.exit("Live tests require GANDI_MCP_LIVE_TESTS=1", 2)

    # Guard 2: test domain owned by account
    domain = os.environ.get("GANDI_MCP_TEST_DOMAIN", "teamrocket.network")
    client = build_client_from_env()
    try:
        await client.get_domain(domain)
    except GandiNotFoundError:
        pytest.exit(f"Test domain {domain} not in account; refusing to run", 2)

    # Guard 3: domain in whitelist (defense in depth)
    if domain not in {"teamrocket.network"}:
        pytest.exit(f"{domain} not in allowed test-domain whitelist", 2)

    # Sweep orphans from prior crashed runs
    await sweep_test_records(client, domain, prefix="mcp-test-", older_than=timedelta(hours=1))
    await sweep_test_glue(client, domain, prefix="ns-test-", older_than=timedelta(hours=1))
    await sweep_test_forwards(client, domain, prefix="forward-", older_than=timedelta(hours=1))
```

Three independent guards. Any one failing aborts the suite before any mutation.

### Env vars

```bash
GANDI_MCP_LIVE_TESTS=1                              # opt-in
GANDI_TOKEN=<PAT>                                   # auth
GANDI_MCP_TEST_DOMAIN=teamrocket.network            # target
GANDI_MCP_TEST_FORWARD_TARGET=<dev-email>           # forward dest
GANDI_MCP_TEST_MAILBOX_SLOT=<slot-uuid>             # pre-paid slot
```

Missing any → tests skip with clear message (not error).

### Rate-limit handling

Add `pytest-rerunfailures`. Live tests retry only on `GandiRateLimitError`: `--reruns=2 --reruns-delay=10`. Hard fail otherwise.

### Cost ceiling guard

`tests/live/conftest.py` includes a custom check that refuses to import any tool tagged `purchase`. Defense in depth on top of mock-only policy.

## Contract fixtures (T3)

Tool: `pytest-recording` (VCR for httpx).

```python
@pytest.mark.contract
@pytest.mark.vcr
async def test_domain_get_returns_expected_shape(client):
    domain = await client.get_domain("teamrocket.network")
    assert {"fqdn", "status", "tld", "dates", "nameservers"} <= domain.keys()
    assert isinstance(domain["status"], list)
```

First run with `--record-mode=once`: hits real API, writes `tests/contract/cassettes/test_domain_get_returns_expected_shape.yaml`. Subsequent runs replay without network. Test fails if response shape no longer matches.

### Secret scrubbing

```python
@pytest.fixture(scope="module")
def vcr_config():
    return {
        "filter_headers": ["authorization", "x-api-key"],
        "filter_query_parameters": ["sharing_id"],
        "before_record_response": redact_pii_from_body,
    }
```

`redact_pii_from_body` strips: customer name, email, phone, address, billing balance values. Replaces with `<REDACTED>`. Cassettes commit to git safely.

### Re-record cadence

Quarterly + on Gandi changelog mention. Procedure in `tests/contract/README.md`:

```bash
GANDI_MCP_LIVE_TESTS=1 GANDI_TOKEN=... \
  uv run pytest tests/contract/ --record-mode=rewrite
git diff tests/contract/cassettes/
```

### Scope limits

- Read-only. Write contract tests would require dummy resources + complicate re-recording.
- One cassette per read tool. 34 cassettes total.

## CI workflow

Single workflow, three jobs, runs on PR + push to `main`.

```yaml
# .github/workflows/ci.yml
name: ci
on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  static:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>  # vX.Y.Z
        with: { persist-credentials: false }
      - uses: astral-sh/setup-uv@<sha>
      - run: uv sync --extra dev
      - run: uv run ruff check src/ tests/
      - run: uv run ruff format --check src/ tests/
      - run: uv run mypy src/gandi_mcp/
      - run: uv run bandit -r src/gandi_mcp/ -c pyproject.toml

  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@<sha>
        with: { persist-credentials: false }
      - uses: astral-sh/setup-uv@<sha>
      - run: uv sync --extra dev --python ${{ matrix.python }}
      - run: uv run pytest -m "not live" --cov=gandi_mcp --cov-report=xml
      - uses: codecov/codecov-action@<sha>
        if: matrix.python == '3.13'

  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<sha>
        with: { persist-credentials: false }
      - uses: astral-sh/setup-uv@<sha>
      - run: uv sync --extra dev
      - run: uv run pip-audit
      - run: pipx run zizmor .github/workflows/
```

All actions pinned to commit SHA with version comment (per CLAUDE.md). Dependabot configured with 7-day cooldown:

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule: { interval: "weekly" }
    cooldown: { default-days: 7 }
  - package-ecosystem: "uv"
    directory: "/"
    schedule: { interval: "weekly" }
    cooldown: { default-days: 7 }
    groups:
      dev-deps:
        dependency-type: "development"
```

### Branch protection (manual setup, document in CONTRIBUTING.md)

- `main` requires PR
- PR requires `static` + `test` (matrix 3.11/3.12/3.13) green
- No force-push to `main`
- Linear history

### Coverage tracking

Codecov reports % per PR comment. **No fail threshold yet** — issue #35 codifies threshold once tool-body mocked tests land.

## Smoke release gate

`pytest -m smoke` — ~10 live read calls, <30s, run before every release tag.

Tools covered: `org_get_user_info`, `domain_list_domains`, `livedns_list_records`, `billing_get_info`, `email_list_mailboxes`, `cert_list`, `domain_get_status`, `livedns_list_nameservers`, `org_list_organizations`, `email_list_slots`.

Documented in `RELEASE.md`:

```bash
GANDI_MCP_LIVE_TESTS=1 GANDI_TOKEN=$PAT \
  uv run pytest -m smoke -v
# All green → tag + publish
```

## Rollout phases

Each phase ships independently and provides standalone value.

### Phase 1 — CI foundation + mocked-integration tests

- Add `.github/workflows/ci.yml` with static + test (matrix) + audit jobs
- Add `.github/dependabot.yml`
- Add `tests/mocked/` with one test file per tool module covering all 71 tools at T2
- Add `bandit` to pre-commit
- Document branch-protection setup in CONTRIBUTING.md
- **Outcome:** every tool has behavior coverage; PRs gated; supply chain audited

### Phase 2 — Contract fixtures

- Add `pytest-recording` dev dep
- Add `tests/contract/` with 34 read-tool replay tests
- Record initial cassettes (one-time live run)
- Add VCR config with PII scrubber
- Document re-record procedure
- **Outcome:** API drift caught in CI; quarterly re-record cadence established

### Phase 3 — Live tier

- Add `pytest-rerunfailures` dev dep
- Add `tests/live/conftest.py` with safety guards + sweeper + ephemeral fixtures
- Add `tests/live/test_live_*.py` covering 34 reads + 20 safe writes
- Add `tests/live/README.md` documenting prereqs (env vars + manual provisioning)
- Manual prereq: provision `teamrocket.network` mailbox slot one-time
- **Outcome:** 76% of tools verified against real Gandi; local opt-in only

### Phase 4 — Smoke gate + release docs

- Add `tests/live/test_live_smoke.py` (~10 tests, `smoke` + `live` markers)
- Add `RELEASE.md` with smoke-run procedure
- **Outcome:** pre-release confidence in <30s

### Future (filed as issues)

- #33 mutation testing (mutmut)
- #34 property-based testing (hypothesis)
- #35 coverage gate (>=85% total, >=70% per tool module)

## Success metrics

- 71/71 tools have at least T2 coverage (currently 1/71 has behavior test)
- 34/34 read tools have T3 cassette + assert shape
- 54/71 tools verified live (currently 0/71)
- CI runs on every PR, blocks merge on failure (currently no CI)
- Smoke gate <30s, all green before each release tag
- Coverage moves from 52% → 85%+ across the suite (gate enforced via #35 once stable)
