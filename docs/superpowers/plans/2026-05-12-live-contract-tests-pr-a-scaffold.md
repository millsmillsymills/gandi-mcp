# PR A — Contract Test Scaffolding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Tier 3 ("contract") testing infrastructure — VCR config, redaction, cassette directory, Makefile targets, CONTRIBUTING docs, and one smoke contract test that exercises the recording + replay pipeline end-to-end — without yet recording any production cassettes.

**Architecture:** New `tests/contract/` directory with a `conftest.py` that wires `pytest-recording` to the project's `GandiClient`. JSON-path PII redaction in a small pure-Python helper that is itself unit-tested. A Makefile gives a one-command refresh + staleness gate. One smoke test (`test_user_info_smoke`) lets us prove the pipeline records and replays cleanly before PR B starts recording the whole API surface.

**Tech Stack:** Python 3.13, pytest, pytest-recording 0.13.4, vcrpy 8.1.1, respx (existing), httpx, uv, ruff, ty.

**Source spec:** `docs/superpowers/specs/2026-05-12-live-contract-tests-90pct-design.md` (revalidated commit `f8c6193`).

**Out of scope for this plan:** PR B (read-endpoint cassettes), PR C (write-endpoint cassettes), PR D (error-path mocked tests), PR E (coverage-gate bump 85→90 + unified per-file rule). Those each get their own plan after this PR merges and the cassette pipeline is proven on real Gandi traffic.

---

## File Structure

| Path | Status | Responsibility |
|---|---|---|
| `pyproject.toml` | Modify | Pin `vcrpy>=8.1,<9` (the httpx interception is from this version range). |
| `Makefile` | Create | `refresh-cassettes` (atomic-swap recording), `check-cassettes-fresh` (180-day staleness gate). |
| `tests/contract/__init__.py` | Create | Empty package marker (mirrors `tests/integration/` and `tests/property/`). |
| `tests/contract/cassettes/.gitkeep` | Create | Empty file so the empty dir survives in git. |
| `tests/contract/_redact.py` | Create | Pure-Python JSON-path redactor + the canonical PII path list. Unit-tested. |
| `tests/contract/conftest.py` | Create | `vcr_config` session fixture, `client` fixture (sharing_id=None, real base URL), env-var validation when recording. |
| `tests/contract/test_smoke.py` | Create | One contract test: `test_user_info_smoke` exercising `GandiClient.get_user_info` end-to-end. Drives the pipeline. |
| `tests/unit/test_contract_redact.py` | Create | Unit tests for `tests/contract/_redact.py`. |
| `CONTRIBUTING.md` | Modify | Append a "Recording contract cassettes" section. |
| `.github/workflows/ci.yml` | Modify | Add a non-blocking step that runs `make check-cassettes-fresh` and prints a warning if anything is stale. |
| `.gitignore` | Modify | Ignore `tests/contract/cassettes.new/` (the refresh staging dir). |

The redactor lives in its own module under `tests/contract/` (not in `conftest.py`) because (a) it's pure logic worth unit-testing in isolation, and (b) conftest files cannot be imported by other tests cleanly.

---

## Task 1 — Pin `vcrpy` version range

**Files:**
- Modify: `pyproject.toml`

The spec calls out that vcrpy 8.x intercepts httpx via socket-level patching, with no dedicated `vcr.stubs.httpx_stubs` module. A future vcrpy 9.x could change this. Lock the working range now.

- [ ] **Step 1: Inspect current pin**

Run: `grep -n "vcrpy\|pytest-recording" pyproject.toml uv.lock | head -10`
Expected: `pytest-recording>=0.13.2` is declared as a dev dep. `vcrpy` only appears in `uv.lock` as a transitive dep (version `8.1.1`).

- [ ] **Step 2: Add a direct constraint on `vcrpy` in `[tool.uv]`**

The spec already constrains `python-multipart>=0.0.27` in `[tool.uv].constraint-dependencies`. Add `vcrpy` to that same list:

```toml
[tool.uv]
constraint-dependencies = [
    "python-multipart>=0.0.27",
    "vcrpy>=8.1,<9",
]
```

- [ ] **Step 3: Re-resolve the lockfile**

Run: `uv lock`
Expected: exit code 0, no diff to the resolved `vcrpy` version line (already at 8.1.1).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(deps): pin vcrpy to >=8.1,<9 for httpx interception stability"
```

---

## Task 2 — Scaffold the `tests/contract/` package

**Files:**
- Create: `tests/contract/__init__.py`
- Create: `tests/contract/cassettes/.gitkeep`
- Modify: `.gitignore`

- [ ] **Step 1: Create the package marker**

Write `tests/contract/__init__.py` with empty content:

```python
```

(Yes, zero bytes — matches `tests/integration/__init__.py` and `tests/property/__init__.py`.)

- [ ] **Step 2: Create the cassette directory placeholder**

Write `tests/contract/cassettes/.gitkeep` with empty content.

- [ ] **Step 3: Ignore the refresh staging dir**

Edit `.gitignore`. Find the "Testing / coverage" block (after line 29 in the current file). Add `tests/contract/cassettes.new/` under it:

```
# Testing / coverage
.pytest_cache/
.coverage
.coverage.*
htmlcov/
coverage.xml
coverage.json
tests/contract/cassettes.new/
tests/integration/artifacts/
.tox/
.nox/
```

- [ ] **Step 4: Verify pytest discovers the new package**

Run: `uv run pytest tests/contract/ --collect-only -q`
Expected: `0 tests collected` (no tests yet), exit code 5 (no tests is technically a "failure"). That's fine — Task 5 adds the first test.

- [ ] **Step 5: Commit**

```bash
git add tests/contract/__init__.py tests/contract/cassettes/.gitkeep .gitignore
git commit -m "test: scaffold tests/contract/ package (T3 contract tier)"
```

---

## Task 3 — Implement and unit-test the JSON-path PII redactor

**Files:**
- Create: `tests/contract/_redact.py`
- Test: `tests/unit/test_contract_redact.py`

The redactor walks JSON response bodies and replaces values at known PII paths with the literal string `"REDACTED"`. It must:
- Leave non-PII keys (including arbitrary UUIDs at `*.id`) intact.
- Return the response unchanged if the body isn't JSON.
- Survive missing intermediate keys without raising.

- [ ] **Step 1: Write the failing tests**

Write `tests/unit/test_contract_redact.py`:

```python
"""Unit tests for the contract-cassette PII redactor."""

from __future__ import annotations

import json

import pytest

from tests.contract._redact import PII_JSON_PATHS, redact_response


def _resp(body: dict) -> dict:
    return {"body": {"string": json.dumps(body).encode("utf-8")}}


class TestRedactResponse:
    def test_customer_id_redacted(self) -> None:
        resp = _resp({"customer": {"id": "f8a3c9d0-1111-2222-3333-444455556666"}})
        out = redact_response(resp)
        assert json.loads(out["body"]["string"])["customer"]["id"] == "REDACTED"

    def test_owner_id_redacted(self) -> None:
        resp = _resp({"owner": {"id": "f8a3c9d0-1111-2222-3333-444455556666"}})
        out = redact_response(resp)
        assert json.loads(out["body"]["string"])["owner"]["id"] == "REDACTED"

    def test_registrant_email_redacted(self) -> None:
        resp = _resp({"registrant": {"email": "real-customer@example.com"}})
        out = redact_response(resp)
        assert json.loads(out["body"]["string"])["registrant"]["email"] == "REDACTED"

    def test_non_pii_id_left_alone(self) -> None:
        # DNS record IDs, mailbox IDs, anything else with an `id` key not under a PII path.
        resp = _resp({"records": [{"id": "dns-record-uuid", "name": "@", "type": "A"}]})
        out = redact_response(resp)
        body = json.loads(out["body"]["string"])
        assert body["records"][0]["id"] == "dns-record-uuid"

    def test_top_level_id_left_alone(self) -> None:
        # Some Gandi endpoints return a bare `{"id": "..."}` — that's the resource's own ID,
        # not a customer ID. Don't blanket-scrub.
        resp = _resp({"id": "domain-record-uuid", "fqdn": "example.com"})
        out = redact_response(resp)
        assert json.loads(out["body"]["string"])["id"] == "domain-record-uuid"

    def test_missing_intermediate_key_is_noop(self) -> None:
        resp = _resp({"foo": "bar"})  # no customer/owner/registrant/billing keys
        out = redact_response(resp)
        assert json.loads(out["body"]["string"]) == {"foo": "bar"}

    def test_non_dict_at_pii_path_is_noop(self) -> None:
        # If the response sets customer=null, don't crash.
        resp = _resp({"customer": None})
        out = redact_response(resp)
        assert json.loads(out["body"]["string"])["customer"] is None

    def test_non_json_body_returned_unchanged(self) -> None:
        resp = {"body": {"string": b"<html>not json</html>"}}
        out = redact_response(resp)
        assert out["body"]["string"] == b"<html>not json</html>"

    def test_empty_body_returned_unchanged(self) -> None:
        resp = {"body": {"string": b""}}
        out = redact_response(resp)
        assert out["body"]["string"] == b""

    def test_missing_body_key_returned_unchanged(self) -> None:
        resp = {"headers": {}}  # body absent
        out = redact_response(resp)
        assert "body" not in out

    def test_pii_paths_constant_is_a_tuple_of_path_tuples(self) -> None:
        # Locks the shape so a future contributor can't accidentally reintroduce a string regex.
        assert isinstance(PII_JSON_PATHS, tuple)
        assert all(isinstance(p, tuple) and all(isinstance(k, str) for k in p) for p in PII_JSON_PATHS)
```

- [ ] **Step 2: Run the tests, confirm they fail**

Run: `uv run pytest tests/unit/test_contract_redact.py -v`
Expected: `ModuleNotFoundError: No module named 'tests.contract._redact'` (or equivalent).

- [ ] **Step 3: Write the minimal implementation**

Write `tests/contract/_redact.py`:

```python
"""JSON-path PII redactor for contract-test cassettes.

VCR.py's ``before_record_response`` hook receives a response dict and returns the
(possibly modified) response. This module exposes ``redact_response`` for that
hook. Redaction is path-based, not regex-based: only values at the exact JSON
paths in ``PII_JSON_PATHS`` are replaced. Other ``id`` keys (DNS record IDs,
mailbox IDs, the resource's own ID) survive intact so contract tests can assert
against them.
"""

from __future__ import annotations

import json
from typing import Any

PII_JSON_PATHS: tuple[tuple[str, ...], ...] = (
    ("customer", "id"),
    ("owner", "id"),
    ("registrant", "email"),
    ("registrant", "phone"),
    ("registrant", "streetaddr"),
    ("billing", "iban"),
)

_REDACTED = "REDACTED"


def redact_response(response: dict[str, Any]) -> dict[str, Any]:
    """Replace values at known PII JSON paths with the literal string "REDACTED".

    Returns the response unchanged if the body is missing, empty, or not valid
    JSON. Missing intermediate keys are tolerated.
    """
    body_container = response.get("body")
    if not isinstance(body_container, dict) or "string" not in body_container:
        return response
    raw: bytes = body_container["string"]
    if not raw:
        return response
    try:
        parsed = json.loads(raw)
    except ValueError:
        return response
    if not isinstance(parsed, dict):
        return response
    for path in PII_JSON_PATHS:
        _redact_path(parsed, path)
    body_container["string"] = json.dumps(parsed).encode("utf-8")
    return response


def _redact_path(obj: dict[str, Any], path: tuple[str, ...]) -> None:
    cur: Any = obj
    for key in path[:-1]:
        if not isinstance(cur, dict) or key not in cur:
            return
        cur = cur[key]
    if isinstance(cur, dict) and path[-1] in cur:
        cur[path[-1]] = _REDACTED
```

- [ ] **Step 4: Run the tests, confirm they pass**

Run: `uv run pytest tests/unit/test_contract_redact.py -v`
Expected: 11 passed.

- [ ] **Step 5: Lint and format**

Run: `uv run ruff check tests/contract/_redact.py tests/unit/test_contract_redact.py && uv run ruff format --check tests/contract/_redact.py tests/unit/test_contract_redact.py`
Expected: `All checks passed!` and `2 files already formatted` (or run `uv run ruff format` to fix).

- [ ] **Step 6: Type-check**

Run: `uv run ty check src/gandi_mcp/`
Expected: clean (no new errors — the redactor isn't under `src/`, but the type check ensures we didn't break anything else by editing the lockfile).

- [ ] **Step 7: Commit**

```bash
git add tests/contract/_redact.py tests/unit/test_contract_redact.py
git commit -m "test(contract): JSON-path PII redactor with unit tests"
```

---

## Task 4 — Write `tests/contract/conftest.py` (vcr_config + client fixture)

**Files:**
- Create: `tests/contract/conftest.py`

Wires `pytest-recording` to use the redactor, the cassette directory, and a `GandiClient` configured to match the cassette shape (no `sharing_id` in the URL).

- [ ] **Step 1: Write the conftest**

Write `tests/contract/conftest.py`:

```python
"""Tier-3 contract-test fixtures.

These tests replay cassettes recorded against the live Gandi v5 API. In CI,
``record_mode='none'`` means a missing cassette is a hard failure (not a record
attempt). To re-record locally, run ``make refresh-cassettes`` — see
CONTRIBUTING.md "Recording contract cassettes".

Invariants enforced here:
- The test ``GandiClient`` is built with ``sharing_id=None`` because the
  cassette URLs have ``sharing_id`` stripped by ``filter_query_parameters``.
  Building the client with any other value would cause cassette-replay misses
  on the URL matcher.
- ``GANDI_TOKEN`` is only read at *record* time. At replay time the token can
  be any non-empty string; we hardcode ``"REDACTED"``.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from gandi_mcp.clients.gandi import GandiClient
from tests.contract._redact import redact_response

_DEFAULT_CASSETTE_DIR = "tests/contract/cassettes"


@pytest.fixture(scope="session")
def vcr_config() -> dict[str, object]:
    """pytest-recording session config — applies to every ``@pytest.mark.vcr`` test."""
    cassette_dir = os.environ.get("VCR_CASSETTE_DIR", _DEFAULT_CASSETTE_DIR)
    return {
        "cassette_library_dir": cassette_dir,
        "filter_headers": ["authorization", "x-api-key", "cookie", "set-cookie"],
        "filter_query_parameters": ["sharing_id"],
        "before_record_response": redact_response,
        "record_mode": "none",
        "match_on": ["method", "scheme", "host", "port", "path", "query"],
    }


@pytest.fixture
async def client() -> AsyncIterator[GandiClient]:
    """A GandiClient that matches the shape recorded in cassettes.

    sharing_id is None on purpose — see module docstring.
    """
    token = os.environ.get("GANDI_TOKEN", "REDACTED")
    c = GandiClient(
        base_url="https://api.gandi.net",
        token=token,
        sharing_id=None,
        timeout=10,
        max_retries=1,
    )
    try:
        yield c
    finally:
        await c.close()


@pytest.fixture(autouse=True)
def _ensure_cassette_dir_exists() -> None:
    """Make the cassette dir exist so a clean checkout doesn't error on first replay."""
    Path(_DEFAULT_CASSETTE_DIR).mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 2: Lint and format**

Run: `uv run ruff check tests/contract/conftest.py && uv run ruff format --check tests/contract/conftest.py`
Expected: `All checks passed!` and `1 file already formatted`.

- [ ] **Step 3: Commit**

```bash
git add tests/contract/conftest.py
git commit -m "test(contract): VCR config fixture + GandiClient fixture with sharing_id=None"
```

---

## Task 5 — Add one smoke contract test (`test_user_info_smoke`)

**Files:**
- Create: `tests/contract/test_smoke.py`

One test that exercises the whole pipeline (real httpx call → VCR record → cassette on disk → next run replays from cassette). Uses `get_user_info`, the same endpoint as the existing live smoke in `tests/integration/test_live_smoke.py`, so we can compare behavior.

- [ ] **Step 1: Write the test**

Write `tests/contract/test_smoke.py`:

```python
"""Pipeline smoke test for the contract tier.

This is the only test in PR A. Its job is to prove the record + replay pipeline
works end-to-end before PR B starts recording the full API surface. Once that
work lands, this file may go away — it's a temporary checkpoint.

The cassette ``tests/contract/cassettes/test_user_info_smoke.yaml`` must be
recorded locally before merge via ``make refresh-cassettes``. Until it exists,
CI fails with ``CannotOverwriteExistingCassetteException`` — which is
intentional: it forces the maintainer to record once and review the diff.
"""

from __future__ import annotations

import pytest

from gandi_mcp.clients.gandi import GandiClient

pytestmark = pytest.mark.contract


@pytest.mark.vcr
async def test_user_info_smoke(client: GandiClient) -> None:
    """A bare round-trip against /v5/organization/user-info.

    Asserts only the *shape* of the response, not specific identifiers:
    Gandi may rotate UUIDs, change customer-id formatting, etc., and the
    redactor scrubs ``customer.id``/``owner.id`` anyway. Shape-level
    assertions are the contract.
    """
    info = await client.get_user_info()
    assert isinstance(info, dict)
    assert "username" in info
    assert isinstance(info["username"], str) and info["username"]
```

- [ ] **Step 2: Add the `contract` marker to `pyproject.toml` if not already strict**

The marker is already declared in `pyproject.toml` (`"contract: VCR-replayed real Gandi responses (T3, intended for CI)"`). No change needed — just confirm:

Run: `grep -n 'contract:' pyproject.toml`
Expected: one match on the line in `markers = [...]`.

- [ ] **Step 3: Run the test in replay-only mode — expect a clean cassette-missing failure**

Run: `uv run pytest tests/contract/test_smoke.py -v`
Expected: 1 failed, with the failure message containing `CannotOverwriteExistingCassetteException` or `Can't overwrite existing cassette` (vcrpy's exact wording varies by version). This is the success case for this step — it proves the wiring rejects a missing cassette rather than silently making a real API call.

- [ ] **Step 4: Lint and format**

Run: `uv run ruff check tests/contract/test_smoke.py && uv run ruff format --check tests/contract/test_smoke.py`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add tests/contract/test_smoke.py
git commit -m "test(contract): smoke test for record+replay pipeline (cassette pending)"
```

---

## Task 6 — Write the `Makefile`

**Files:**
- Create: `Makefile`

Two targets: `refresh-cassettes` (atomic-swap recording) and `check-cassettes-fresh` (180-day staleness gate).

- [ ] **Step 1: Write the Makefile**

Write `Makefile`:

```makefile
# Developer-facing make targets. CI doesn't use these — CI uses `uv run pytest`
# and `uv run python scripts/check_coverage_thresholds.py` directly.

.PHONY: help refresh-cassettes check-cassettes-fresh

help:
	@echo "Targets:"
	@echo "  refresh-cassettes      Re-record every contract cassette against api.gandi.net."
	@echo "                         Requires GANDI_TOKEN in env (use `pass show gandi/pat-sandbox`)."
	@echo "  check-cassettes-fresh  Fail if any cassette is older than 180 days."

# Re-record every cassette. Stages to cassettes.new so a mid-run failure
# never leaves the committed tree in a half-deleted state.
refresh-cassettes:
	@if [ -z "$$GANDI_TOKEN" ]; then \
		echo "GANDI_TOKEN not set. Recording requires a sandbox PAT scoped to teamrocket.network."; \
		echo "Example: GANDI_TOKEN=\$$(pass show gandi/pat-sandbox) make refresh-cassettes"; \
		exit 2; \
	fi
	rm -rf tests/contract/cassettes.new
	mkdir -p tests/contract/cassettes.new
	VCR_CASSETTE_DIR=tests/contract/cassettes.new \
		uv run pytest tests/contract/ --record-mode=once -p no:cacheprovider
	rm -rf tests/contract/cassettes
	mv tests/contract/cassettes.new tests/contract/cassettes
	@echo
	@echo "Cassettes recorded. Review the diff (git diff -- tests/contract/cassettes/)"
	@echo "for unredacted PII before committing."

# Warn (don't fail the build) when any cassette is >180 days old.
check-cassettes-fresh:
	@find tests/contract/cassettes -name '*.yaml' -mtime +180 -print 2>/dev/null | \
		awk 'NR { print "STALE: " $$0 } END { \
			if (NR) { print "\nRun: make refresh-cassettes"; exit 1 } \
			else { print "All cassettes fresh (<=180 days)." } }'
```

- [ ] **Step 2: Verify the staleness target runs cleanly when no cassettes exist yet**

Run: `make check-cassettes-fresh`
Expected: `All cassettes fresh (<=180 days).` exit code 0. (No `.yaml` files yet → `find` returns nothing → NR is 0 → success branch.)

- [ ] **Step 3: Verify `make refresh-cassettes` aborts cleanly when GANDI_TOKEN is unset**

Run: `make refresh-cassettes`
Expected: prints the "GANDI_TOKEN not set..." message and exits with code 2. No filesystem changes.

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "build: Makefile with refresh-cassettes + check-cassettes-fresh targets"
```

---

## Task 7 — Document the recording workflow in `CONTRIBUTING.md`

**Files:**
- Modify: `CONTRIBUTING.md`

- [ ] **Step 1: Find the right insertion point**

Run: `grep -n '^## \|^### ' CONTRIBUTING.md | head -20`
Expected: a list of headings. Find the heading that introduces the testing/maturity discussion — the spec context suggests there's a section about test tiers near the top of the file.

- [ ] **Step 2: Append a new section before "Open follow-ups" (or before the bottom of the file if no such section)**

Add this section. Place it after the existing "Test tiers" section (or, if that section doesn't exist, place it as a top-level subsection just before the mutmut docs):

```markdown
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
```

- [ ] **Step 3: Lint nothing — this is markdown**

Skip. (The repo has no markdown linter.)

- [ ] **Step 4: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "docs: how to record + review contract cassettes"
```

---

## Task 8 — Wire the staleness check into CI as a non-blocking warning

**Files:**
- Modify: `.github/workflows/ci.yml`

Add a step to the `test` job that runs `make check-cassettes-fresh` but doesn't fail the build on stale cassettes — just emits a GitHub Actions warning annotation.

- [ ] **Step 1: Inspect the current `test` job**

Run: `grep -n -A 20 "test:" .github/workflows/ci.yml | head -40`
Expected: see the job's `steps:` list. Find the last step (the codecov upload).

- [ ] **Step 2: Add a new step after the threshold check**

Edit `.github/workflows/ci.yml`. Locate this block (currently after PR #98 merged):

```yaml
      - run: uv run pytest -m "not live" --cov=gandi_mcp --cov-report=xml --cov-report=json --cov-report=term --cov-fail-under=85
      - run: uv run python scripts/check_coverage_thresholds.py
      - if: matrix.python == '3.13'
        uses: codecov/codecov-action@57e3a136b779b570ffcdbf80b3bdc90e7fab3de2  # v6.0.0
```

Add a `make check-cassettes-fresh` step between the threshold check and the codecov upload:

```yaml
      - run: uv run pytest -m "not live" --cov=gandi_mcp --cov-report=xml --cov-report=json --cov-report=term --cov-fail-under=85
      - run: uv run python scripts/check_coverage_thresholds.py
      - name: Cassette staleness warning (non-blocking)
        if: always()
        run: |
          if ! make check-cassettes-fresh; then
            echo "::warning::Some cassettes are >180 days old. Run 'make refresh-cassettes' locally."
          fi
      - if: matrix.python == '3.13'
        uses: codecov/codecov-action@57e3a136b779b570ffcdbf80b3bdc90e7fab3de2  # v6.0.0
```

The `if: always()` keeps it running even if a prior step failed (the staleness check is independent). The `if ! make check-cassettes-fresh` form swallows the non-zero exit and turns it into a warning annotation instead of a job failure.

- [ ] **Step 3: Lint the workflow**

Run: `pipx run zizmor==1.24.1 .github/workflows/ci.yml`
Expected: no new findings beyond whatever zizmor already reports on this file.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: non-blocking cassette staleness warning"
```

---

## Task 9 — Full local verification

This is a verification gate, not a code task. Confirm the whole scaffolding works as a unit before pushing.

- [ ] **Step 1: Run lint + format across the touched files**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: `All checks passed!` and a count of "already formatted".

- [ ] **Step 2: Run type check**

Run: `uv run ty check src/gandi_mcp/`
Expected: clean.

- [ ] **Step 3: Run the full unit + mocked suite (replay-only)**

Run: `uv run pytest tests/unit/ tests/mocked/ tests/property/ -q -m "not live"`
Expected: 438+11 = 449 passed, 0 failed. (11 redactor tests added in Task 3.)

- [ ] **Step 4: Confirm the contract smoke test fails-loud on missing cassette**

Run: `uv run pytest tests/contract/ -v`
Expected: exactly 1 failure (`test_user_info_smoke`) with `CannotOverwriteExistingCassetteException`. This proves replay-only is the default and that the smoke test is wired correctly.

- [ ] **Step 5: Run the coverage gate (existing, unchanged)**

Run: `uv run pytest tests/unit/ tests/mocked/ tests/property/ -m "not live" --cov=gandi_mcp --cov-report=json -q && uv run python scripts/check_coverage_thresholds.py`
Expected: `Coverage thresholds satisfied (total 88.XX%).` Coverage might tick up a hair from the redactor tests; we're well above 85 %.

- [ ] **Step 6: Run `make check-cassettes-fresh`**

Run: `make check-cassettes-fresh`
Expected: `All cassettes fresh (<=180 days).` exit 0.

- [ ] **Step 7: Clean coverage artifacts**

Run: `rm -f coverage.json coverage.xml`
Expected: silent.

---

## Task 10 — Maintainer-only: record the smoke cassette

This task **cannot be done by an agent** — it requires a real `GANDI_TOKEN`. The agent must stop here and surface a clear hand-off message to the maintainer.

- [ ] **Step 1 (maintainer): record the smoke cassette**

Run, from the project root, with a sandbox PAT in env:

```bash
GANDI_TOKEN=$(pass show gandi/pat-sandbox) make refresh-cassettes
```

Expected: pytest runs `test_user_info_smoke` against the real API, records the response to `tests/contract/cassettes.new/test_user_info_smoke.yaml`, then atomically renames the directory to `tests/contract/cassettes/`.

- [ ] **Step 2 (maintainer): review the cassette diff**

Run: `git diff --stat -- tests/contract/cassettes/ && less tests/contract/cassettes/test_user_info_smoke.yaml`

Scan for:
- `authorization:` header — should be `[]` (filtered).
- `sharing_id=` in any URL — should be absent.
- `customer.id` / `owner.id` in the response body — should be `"REDACTED"`.
- The PAT owner's `username` is visible (that's the test target — fine).
- Any unexpected PII (real billing addresses, IBANs, etc.) — extend `PII_JSON_PATHS` and re-record before committing.

- [ ] **Step 3 (maintainer): verify replay works**

Run: `uv run pytest tests/contract/ -v`
Expected: `1 passed`. Same input, no live API call. This proves the cassette replays.

- [ ] **Step 4 (maintainer): commit the cassette**

```bash
git add tests/contract/cassettes/
git commit -m "test(contract): record smoke cassette for user-info round-trip"
```

- [ ] **Step 5: Push branch + open PR**

The branch name for this work is `test/contract-scaffold`. (If you started work on a different branch, substitute that name in the `git push` line — the rest of the command is unchanged.)

```bash
git push -u origin test/contract-scaffold
gh pr create --title "test(contract): scaffold Tier-3 contract tests with VCR cassettes" \
    --body "$(cat <<'EOF'
## Summary

Stands up the Tier-3 contract test scaffolding per spec
\`docs/superpowers/specs/2026-05-12-live-contract-tests-90pct-design.md\`.
This PR is foundation only — no cassettes for the full API surface yet (that's
PR B).

What's in:

- \`tests/contract/_redact.py\` — JSON-path PII redactor with 11 unit tests.
- \`tests/contract/conftest.py\` — VCR config + GandiClient fixture
  (sharing_id=None invariant).
- \`tests/contract/test_smoke.py\` — one smoke test exercising the
  record + replay pipeline against \`/v5/organization/user-info\`.
- \`tests/contract/cassettes/test_user_info_smoke.yaml\` — recorded against
  \`teamrocket.network\` sandbox PAT.
- \`Makefile\` — \`refresh-cassettes\` (atomic-swap recording) and
  \`check-cassettes-fresh\` (180-day staleness gate).
- \`CONTRIBUTING.md\` — "Recording contract cassettes" section.
- \`.github/workflows/ci.yml\` — non-blocking staleness warning step.
- \`pyproject.toml\` — pin \`vcrpy>=8.1,<9\` (httpx interception range).

What's not in (later PRs):
- PR B — read-endpoint cassettes (34 endpoints).
- PR C — non-purchasing-write cassettes (29 endpoints).
- PR D — error-path mocked tests (~71 tests).
- PR E — bump coverage gate 85 -> 90 with unified per-file rule.

## Test plan

- [x] \`uv run pytest tests/unit/ tests/mocked/ tests/property/ -q\` — 449 passed.
- [x] \`uv run pytest tests/contract/ -v\` — 1 passed (replays the smoke cassette).
- [x] \`make check-cassettes-fresh\` — passes (cassette is fresh).
- [x] Cassette diff reviewed for PII.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review checklist (run after completing every task)

- [ ] Every step has either a code block or an exact command — no "implement appropriately".
- [ ] Every test step shows the exact pytest invocation and the expected pass/fail.
- [ ] `tests.contract._redact.redact_response` and `tests.contract._redact.PII_JSON_PATHS` are the only names that cross task boundaries; both are defined in Task 3 and re-used in Task 4. No other type names cross boundaries.
- [ ] The cassette directory is referenced consistently as `tests/contract/cassettes/` (no trailing-slash drift).
- [ ] `sharing_id=None` invariant is enforced in three places (spec, conftest fixture docstring, code), per spec's "Matcher mismatch from sharing_id" risk.
- [ ] Task 10 explicitly marks itself as maintainer-only and explains why an agent cannot complete it.

## Spec coverage check

Maps each spec section to a task:

| Spec section | Task(s) |
|---|---|
| Tier layout (`tests/contract/...`) | 2 |
| Test pattern (`@pytest.mark.contract` + `@pytest.mark.vcr`) | 5 |
| Scope (in/out) | (deferred — PR B/C plans) |
| Write-test cleanup matrix | (deferred — PR C plan) |
| Error-path coverage | (deferred — PR D plan) |
| Coverage gate change | (deferred — PR E plan) |
| Library compatibility note | 1 (pin), 4 (conftest comment) |
| Cassette redaction + secrets | 3 (redactor), 4 (conftest), 7 (docs) |
| `sharing_id` matcher interaction | 4 (fixture), 7 (docs reference) |
| Recording flow (Makefile) | 6 |
| Staleness check | 6, 8 |
| CI changes (non-blocking warning) | 8 |
| Migration order | (this plan covers PR A only) |
| Risks (PAT scope, VCR upstream, matcher) | 1, 4, 7 |
