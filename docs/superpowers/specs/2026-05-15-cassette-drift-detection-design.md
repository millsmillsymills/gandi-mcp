# Cassette Drift Detection

## Status

Draft — 2026-05-15.

## Goal

Catch structural drift between the cassettes committed under `tests/contract/cassettes/` and the responses Gandi v5 returns today, before the drift silently invalidates contract-test assertions.

## Non-goals

- Replacing or modifying the existing 180-day `make check-cassettes-fresh` staleness gate. Drift detection is a sharper, semantic check; the time-based gate is its complement.
- Value-level diffing (timestamps, IDs, counts churn on every refresh and would drown signal).
- Schema generation against a third-party schema registry.
- Auto-refreshing cassettes when drift is found. Drift detection is observe-only; accepting drift is always a separate, explicit operator action (`make refresh-cassettes`).
- Real-money or purchase-endpoint coverage (spec [`2026-05-12-live-contract-tests-90pct-design.md`](2026-05-12-live-contract-tests-90pct-design.md) excludes those by design).

## Background

After the live-contract-tests spec lands (PRs #100–#104), `tests/contract/cassettes/` will hold YAML cassettes recorded against `teamrocket.network` covering ~63 of the ~70 `GandiClient` methods. CI replays them with `record_mode='none'`. The committed cassette is the de-facto contract: the test asserts shape, the cassette pins the shape.

The existing freshness gate fails the build only when a cassette file's mtime is >180 days old. It cannot detect that:

- Gandi added a new top-level field to `GET /v5/domain/domains/{fqdn}` last week. The committed cassette still parses, the test still passes, but downstream code that reads the new field via the dict-pass-through pattern would silently see `KeyError`.
- A field that used to be a `string` is now an `object`. Replay still works; production fails.
- A list endpoint's response cardinality shifted from "always 1+" to "sometimes empty". Replay-only tests don't see it.

Drift detection bridges the gap: re-record cassettes on demand against live Gandi, structurally diff old vs. new, surface differences without overwriting.

## Decisions made during brainstorming

1. **Scope** — complement the existing 5-PR spec, not replace any part of it.
2. **Trigger** — `make check-drift` is the primary entry point. A scaffolded GitHub Actions workflow exists but is `workflow_dispatch`-only; no cron line ships in this design.
3. **Diff semantics** — structural only: keys present/absent, value types, list cardinality bounds. Values are discarded after type extraction.
4. **Action on drift** — print a human-readable report and (with `--open-issue`) create a `drift`-labeled GitHub issue, or append a dated comment to an existing open one.

## Architecture

```
EXISTING (after PR A merges)
─────────────────────────────────
tests/contract/cassettes/          committed YAML cassettes
tests/contract/cassettes.new/      refresh staging (gitignored)
Makefile: refresh-cassettes        records → atomic-swaps into cassettes/
Makefile: check-cassettes-fresh    180-day mtime gate

NEW (this spec)
─────────────────────────────────
scripts/cassette_drift.py          CLI: extract shape + diff + report +
                                   optional gh-issue notify
Makefile: check-drift              records to cassettes.new, runs the CLI,
                                   NEVER swaps. exit 1 on drift.
.github/workflows/drift-check.yml  workflow_dispatch only. No cron.
                                   Reads GANDI_SANDBOX_PAT from secrets,
                                   invokes the makefile target with
                                   CASSETTE_DRIFT_OPEN_ISSUE=1.
tests/unit/test_cassette_drift.py  shape extractor + diff logic
tests/unit/test_cassette_drift_cli.py
                                   CLI exit codes + gh stub interaction
```

Drift is **observe-only**. The staging dir is shared with `refresh-cassettes` because re-recording is the same expensive operation; the swap step is the only difference between the two flows.

## Components

`scripts/cassette_drift.py` is a single argparse CLI.

```
usage: cassette_drift.py [-h]
                         [--cassette-dir-old DIR]
                         [--cassette-dir-new DIR]
                         [--report-format {text,md}]
                         [--open-issue]

Exit codes:
  0  no drift
  1  drift detected (or every cassette failed to parse)
  2  invalid input
```

Six pure functions plus a thin `main()`.

| Function | Input → Output | Purpose |
|---|---|---|
| `load_cassette(path)` | YAML path → list of `(request, response_body_json_or_None)` | Parses VCR YAML. Returns `None` for the body when it is not valid JSON. Raises `CassetteParseError` only on malformed YAML or missing `interactions` list. |
| `extract_shape(body)` | parsed JSON → frozen shape | Recursive walk. `dict` → frozenset of `(key, child_shape)`. `list` → `("list", min_len, max_len, item_shape)`. Scalar → `"str"`/`"int"`/`"float"`/`"bool"`/`"null"`. Values discarded. |
| `merge_list_shape(items)` | list of item shapes → unified shape | Folds heterogeneous list items into one shape with cardinality bounds. Mixed types collapse into `("union", frozenset_of_member_shapes)`. |
| `diff_shapes(old, new, path)` | two shapes + jq-path → list of `DriftEntry` | Walks recursively, emitting `Added`/`Removed`/`TypeChanged`/`CardinalityChanged`/`UnionChanged`. |
| `render_report(entries, fmt)` | entries + format → string | `text`: `+ added foo.bar (str)` / `- removed baz` / `~ qux: int → str` / `! list users: 0..3 → 0..50`. `md`: same lines in a fenced code block under a per-cassette `## ` heading. Sorted by jq-path for determinism. |
| `find_existing_drift_issue(label, title_prefix)` | `gh issue list` JSON → issue number or `None` | Idempotency hook for `--open-issue`. |

Glue (`main()`):

1. Walk `cassette-dir-old/**/*.yaml`. For each path, locate the sibling under `cassette-dir-new/` at the same relative path.
2. Missing-on-new → warning, not drift (refresh was partial; that's a `refresh-cassettes` failure, not a drift signal).
3. For each pair: `load_cassette(old)` + `load_cassette(new)`. Pair interactions by `(method, full_url_after_filtering, sha256(request_body_bytes))`. Unpaired interactions surface as orchestration-drift entries (separate channel from response-shape drift).
4. For each paired response: `extract_shape(old)` + `extract_shape(new)` + `diff_shapes(...)`. Collect.
5. `render_report(all_entries)` to stdout.
6. If `--open-issue` AND total drift entries > 0: `find_existing_drift_issue("drift", "drift: ")`. Append a dated comment if found, else create with title `drift: N cassette(s) drifted upstream`, label `drift`, body containing the report.
7. Exit 1 if drift, 0 otherwise.

The `gh` notifier shells out via `subprocess.run` — no new Python HTTP dep; `gh` is already required by `gh issue create` elsewhere in the project's workflows.

## Data flow

```
operator: `make check-drift`         ┌──────────────────────────────────────────────────┐
   │                                 │  Makefile target check-drift                     │
   │  GANDI_TOKEN in env             │                                                  │
   ├────────────────────────────────▶│  1. guard: GANDI_TOKEN set → else exit 2         │
   │                                 │  2. rm -rf tests/contract/cassettes.new          │
   │                                 │  3. mkdir tests/contract/cassettes.new           │
   │                                 │  4. VCR_CASSETTE_DIR=…cassettes.new              │
   │                                 │     uv run pytest tests/contract/                │
   │                                 │     --record-mode=once -p no:cacheprovider       │
   │                                 │                          │ writes fresh YAMLs    │
   │                                 │                          ▼                       │
   │                                 │  5. uv run python scripts/cassette_drift.py \    │
   │                                 │       --cassette-dir-old tests/contract/         │
   │                                 │                          cassettes               │
   │                                 │       --cassette-dir-new tests/contract/         │
   │                                 │                          cassettes.new           │
   │                                 │       $(if $(CASSETTE_DRIFT_OPEN_ISSUE),         │
   │                                 │            --open-issue,)                        │
   │                                 │  6. NEVER `mv cassettes.new cassettes`           │
   │                                 │  7. propagate the script's exit code             │
   │                                 └──────────────────────────────────────────────────┘
   │
   ▼
operator reads report on stdout, decides:
  - drift expected (Gandi shipped a new field) → run `make refresh-cassettes`, commit
  - drift surprising → investigate before refreshing
```

**Pairing detail.** Cassettes are list-of-interactions; the same endpoint can appear N times in one cassette with different request bodies. Pairing key = `(method, full_url_after_filtering, sha256(request_body_bytes))`. Unpaired-on-new = "request gone" entry; unpaired-on-old = "new request" entry (test added a new call). Both report as orchestration drift, distinct from response-shape drift.

**Workflow path** (`.github/workflows/drift-check.yml`, dormant):

- `on: workflow_dispatch` only. No `schedule:` line.
- One job: checkout, `uv sync`, exports `GANDI_TOKEN` from `${{ secrets.GANDI_SANDBOX_PAT }}`, runs `make check-drift CASSETTE_DRIFT_OPEN_ISSUE=1`.
- `permissions: { issues: write }` so the script can create or comment on the drift issue.
- Workflow YAML lists `secrets.GANDI_SANDBOX_PAT` as a required secret in `inputs:` documentation for discoverability.

The Makefile reads `$(CASSETTE_DRIFT_OPEN_ISSUE)` and conditionally adds `--open-issue`. Local default is no auto-issue.

## Error handling

| Failure | Detection | Behavior |
|---|---|---|
| `GANDI_TOKEN` unset (manual run) | Makefile guard pre-record | Print `GANDI_TOKEN not set. Drift check requires the same sandbox PAT as refresh-cassettes.` Exit 2. No filesystem changes. (Mirrors `refresh-cassettes`.) |
| `GANDI_TOKEN` unset (workflow_dispatch) | Same guard | Workflow step fails immediately with the same message. The workflow lists `secrets.GANDI_SANDBOX_PAT` in dispatch-inputs docs for discoverability. |
| Pytest record fails partway | Non-zero pytest exit | Makefile target propagates the exit code. `cassettes.new/` is left in place for inspection. `cassette_drift.py` does NOT run. Operator triages the contract-test failure first. |
| Cassette parse error (malformed YAML or missing `interactions`) | `load_cassette` raises `CassetteParseError` | Print `WARN: skipping <path> (parse error: <msg>)`, continue with remaining pairs. Not counted as drift. Returns exit 1 only if every cassette failed to parse. |
| Non-JSON response body | `load_cassette` returns body=None | Pair logged but excluded from shape diff. `WARN: <path> request <N>: body is not JSON, skipping shape diff`. |
| `gh` not on PATH or non-zero on create/comment (only with `--open-issue`) | `subprocess.run` non-zero | Print `ERROR: drift detected but issue creation failed: <stderr>`. Still print the full drift report. Exit 1 (drift was real). CI surfaces both signals in one log. |

**Two invariants that prevent silent failure:**

1. **Pairing miss is not silently "no drift".** A cassette that loaded zero `(request, response)` pairs (e.g. every body was non-JSON, or YAML was unexpectedly empty) prints `WARN: <path> has no comparable pairs` and is excluded from the 0/1 exit logic. Without this, an all-binary cassette plus a network glitch on re-record could yield a clean "no drift" exit.
2. **Issue de-dup is strict.** `find_existing_drift_issue` searches by exact label (`drift`) AND title prefix (`drift: `). Match → append a dated comment with the new report. No match → create. Never silently swallow issue creation when an open one exists — appending a comment is the visible signal that drift recurred.

**Non-goals for error handling:** retrying failed `gh` calls (operator can re-run), retrying failed records (the contract suite owns its own retry policy), validating that `cassettes.new/` schema matches `cassettes/` structurally (the YAML structure is VCR's; we trust the recorder).

## Testing

The drift checker is itself code that must be tested.

**Unit (`tests/unit/test_cassette_drift.py`):**

Pure functions exercised with synthetic inputs — no YAML files, no `gh`, no network.

| Test class | Cases |
|---|---|
| `TestExtractShape` | scalar types (str/int/float/bool/null); nested dict; flat list of homogeneous scalars; list of dicts; empty list; deeply nested mixed; assertion that no actual value survives extraction |
| `TestMergeListShape` | empty input; single-type list; mixed-scalar list → union; mixed-dict list → key-union with optional flags; cardinality bounds are (min, max) over input list |
| `TestDiffShapes` | identical → empty diff; added field; removed field; type-changed field; cardinality bound widened; cardinality bound narrowed; nested-dict added; nested type change; union member added; union member removed; jq-path is correct for nested cases |
| `TestRenderReport` | empty entries → empty string; one of each entry type → expected `+/-/~/!` line; markdown format has fenced block under a `## ` per-cassette heading; report is deterministic (sorted by jq-path) |
| `TestLoadCassette` | well-formed YAML with JSON body → list of pairs; binary body → pair has body=None; missing `body.string` → pair has body=None; malformed YAML → raises `CassetteParseError`; multi-interaction cassette → all interactions returned |
| `TestPairing` | identical request lists pair 1:1; same URL different body → distinct pairs; request gone in new → "orchestration: removed"; new request added → "orchestration: added" |

**CLI (`tests/unit/test_cassette_drift_cli.py`):**

Driven via `subprocess.run` against `scripts/cassette_drift.py`. Uses two `tmp_path` cassette dirs. Lives under `tests/unit/` because it is offline-pure — no network, no real `gh` call, no live cassettes.

| Test | Setup | Assertion |
|---|---|---|
| `test_no_drift_exit_0` | Identical YAML in old + new | exit 0, stdout empty |
| `test_drift_exit_1_with_report` | New cassette adds a field | exit 1, stdout contains `+ added` and the field's jq-path |
| `test_open_issue_flag_invokes_gh` | PATH-shadowed `gh` stub records its argv | exit 1, stub recorded `issue create --label drift` |
| `test_open_issue_appends_when_existing_open` | Stub `gh issue list` returns one open drift issue | stub recorded `issue comment <N>`, not `issue create` |
| `test_open_issue_failure_still_reports_drift` | Stub exits non-zero on create | exit 1, stdout contains both the drift report AND the `ERROR: ... issue creation failed` line |
| `test_missing_pair_emits_warning_not_drift` | Empty cassette + populated cassette | exit 1, stdout contains `WARN: ... no comparable pairs`, no `+/-/~` entries |
| `test_makefile_check_drift_guards_missing_token` | Spawn `make check-drift` with `GANDI_TOKEN` unset | exit 2, stderr contains `GANDI_TOKEN not set` |

**Out of scope for testing:**

- The actual record-mode pytest run inside `make check-drift` (already exercised by `make refresh-cassettes`, whose contract suite is the recorded surface). Drift CLI tests use canned `*.yaml` fixtures.
- Real `gh issue create` calls (stubbed via PATH shadowing — safer than hitting a live test repo).
- Network behavior — drift logic is offline-pure given two cassette dirs.

**Coverage scope.** `scripts/` is not under `[tool.coverage.run] source = ["gandi_mcp"]`, so the drift script does not contribute to project coverage and the coverage gate does not apply to it. Its correctness is enforced exclusively by the unit + CLI tests above. If a future change adds `scripts/` to the coverage source, the script should hold ~100% line coverage given its size (~80 LoC of pure logic).

## Dependencies

- **Blocked by #100** (PR A) — needs `tests/contract/`, `Makefile`, `cassettes.new/` staging dir to exist.
- **Recommended after #101 + #102** (PR B + PR C) — drift detection is most valuable once there are real cassettes to drift against. Shipping before B/C means the only cassette in scope is the smoke cassette from PR A, which limits useful signal.
- **Independent of #103, #104** (PR D + PR E). Drift CLI lands in its own PR.

## Risks

- **False-positive churn on Gandi releases.** Gandi may ship harmless field additions (new optional `extra_metadata` keys, etc.) frequently. Each one trips drift, opens an issue, demands triage. Mitigation: the issue body shows exactly what changed (one line per added field); the maintainer can refresh + commit in one cycle. If churn becomes painful, a future PR can add a `cassettes/.drift-allowlist.yaml` declaring fields where additions are expected (deletions still trip).
- **Cassette refresh during drift-check leaks unredacted PII.** The pytest run inside `check-drift` writes new cassettes to `cassettes.new/`, which is gitignored but lives on the operator's disk. The redactor (`tests/contract/_redact.py`) runs before disk write, so the staging cassettes are already redacted. Risk reduces to "an operator's local cassettes.new/ directory contains redacted-but-fresh response data" — same posture as `make refresh-cassettes` today.
- **`gh` subprocess injection.** The drift report goes into `gh issue create --body-file -` via stdin, not as a shell argument. No string interpolation into the command line. The script never accepts user input — its only inputs are file paths and committed YAML.
- **Sandbox PAT exposure via workflow_dispatch.** The workflow accepts no inputs, runs only on operator dispatch, and reads the PAT from `secrets.GANDI_SANDBOX_PAT`. Standard GitHub-managed secret hygiene applies. The PAT is sandbox-scoped to `teamrocket.network` per the live-contract-tests spec; blast radius on leak is bounded.
- **Drift checker drift.** The diff logic itself can have bugs that hide drift. Mitigation: unit tests cover the four drift categories explicitly with both directions (added/removed, widened/narrowed, etc.). Mutation testing can be added in a follow-up if the script becomes complex enough.

## Out of scope

- Cron-scheduled drift detection. Workflow file scaffolds the entry point; cron line is a deliberate non-decision deferred to a future PR after the secret-management and alert-routing story is settled.
- Value pinning. If a future test wants to assert that `response["status"] == "active"` rather than just `isinstance(response["status"], str)`, that's a test-side decision, not a drift-detector decision.
- Drift detection for the 8 purchase endpoints. They have no committed cassettes (excluded by the live-contract-tests spec), so there is nothing to drift against.
- Multi-PAT support (e.g. recording with one PAT, comparing against another's cassettes). Drift always uses the same sandbox PAT as refresh.
- Webhook / Slack / email notifications. The `drift` GitHub issue is the canonical alert surface; GitHub's issue-subscription mechanism handles fan-out.

## Migration

One PR introduces:

- `scripts/cassette_drift.py`
- `tests/unit/test_cassette_drift.py`
- `tests/unit/test_cassette_drift_cli.py`
- New `Makefile` target `check-drift` (and a `CASSETTE_DRIFT_OPEN_ISSUE` conditional)
- `.github/workflows/drift-check.yml` (workflow_dispatch only)
- `CONTRIBUTING.md` section: "Detecting cassette drift"
- A new GitHub label: `drift` (declared in the issue template or set up manually)

No changes to `src/gandi_mcp/`, `tests/contract/`, or any production code path.
