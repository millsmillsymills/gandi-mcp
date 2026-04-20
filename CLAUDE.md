# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Production-grade Python MCP server for the Gandi v5 API (domains, LiveDNS, email, billing, organizations, certificates). Uses FastMCP with a three-tier safety model: readonly (default) → readwrite → readwrite+purchases. Follows the same architectural conventions as sister projects `unifi-mcp` and `unraid-mcp`.

## Commands

```bash
# Install (development)
uv sync --extra dev

# Lint
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Type check
uv run mypy src/gandi_mcp/

# Test (unit only)
uv run pytest tests/unit/ -v

# Run a single test file / class / test
uv run pytest tests/unit/test_server_lifespan.py -v
uv run pytest tests/unit/test_server.py::TestReadOnlyGate -v
uv run pytest tests/unit/test_config.py::TestPurchaseGate::test_purchases_enabled_when_both_set -v

# Test with coverage
uv run pytest tests/unit/ --cov=gandi_mcp --cov-report=term-missing -m "not integration"

# Security scan
uv run bandit -r src/gandi_mcp/ -c pyproject.toml

# Pre-commit hooks
uv run pre-commit run --all-files

# Build package
uv build
```

## Architecture

```
src/gandi_mcp/
├── __init__.py          # Package root, exports __version__
├── __main__.py          # Entry point: creates and runs server
├── server.py            # FastMCP server creation + lifespan + mode/purchase gating
├── config.py            # Pydantic settings (env vars + safety-gate properties)
├── errors.py            # Exception hierarchy + error mapping (incl. ReadOnly/PurchaseBlocked)
├── clients/
│   ├── base.py          # BaseGandiClient with retry/auth/error mapping, sharing_id passthrough
│   └── gandi.py         # Typed method-per-endpoint wrapper over the v5 REST API
└── tools/
    ├── _common.py       # get_server_context, get_client, assert_readwrite, assert_purchases_allowed
    ├── organization.py  # organization tools (read)
    ├── billing.py       # billing tools (read)
    ├── domain.py        # domain tools (read + write + purchase)
    ├── livedns.py       # LiveDNS tools (read + write)
    ├── email.py         # email tools (read + write + purchase)
    └── certificate.py   # certificate tools (read + write + purchase)
```

## Conventions

- **Python >=3.11**, strict mypy, ruff for lint+format
- **Line length**: 120 characters
- **Tool naming**: `{area}_{verb}_{entity}` (e.g. `domain_list_domains`, `livedns_create_record`, `cert_revoke`). Exception: `org_*` for organization tools.
- **Tags**: every tool carries `{"gandi", "<area>"}`. Write tools add `"write"`. Purchase tools add both `"write"` AND `"purchase"`.
- **Annotations**: write tools set `readOnlyHint=False`; destructive writes set `destructiveHint=True`; purchase tools additionally set `openWorldHint=True` (they affect external state beyond the Gandi account).
- **Defense-in-depth**: visibility gating in `server.py` (`mcp.disable(tags={"write"})`, `mcp.disable(tags={"purchase"})`) PLUS runtime `assert_readwrite` / `assert_purchases_allowed` calls inside each handler.
- **Clients**: `httpx.AsyncClient` with `tenacity` retry (3 attempts, exponential backoff). Timeouts are **not** retried for non-idempotent methods to avoid double-spending on purchase endpoints. Responses pass through as `dict[str, Any]` / `list[dict[str, Any]]` — no Pydantic validation layer between clients and tools.
- **Error mapping**: API errors → typed exceptions → `ToolError` with agent-readable messages.
- **Tests**: `respx` for HTTP mocking, `pytest-asyncio` for async tests.
- **No print statements**: Use `logging` module (enforced by ruff T20 rule).

## Safety gates

Two orthogonal env flags produce three tiers of exposure:

| `GANDI_MODE` | `GANDI_ALLOW_PURCHASES` | Visible tools |
|---|---|---|
| `readonly` (default) | any | Read only |
| `readwrite` | `false` (default) | Read + non-purchasing writes |
| `readwrite` | `true` | Read + writes + purchases |

Purchase tools are tagged `{"write", "purchase"}` — both `mcp.disable(tags={"write"})` in readonly mode AND `mcp.disable(tags={"purchase"})` when purchases are off will hide them. A purchase tool handler runs `assert_readwrite` *before* `assert_purchases_allowed`, so the operator always sees the narrower error first.

## Key patterns

### Adding a read tool
```python
@mcp.tool(tags={"gandi", "domain"})
async def domain_get_domain(ctx: Context, fqdn: str) -> dict[str, Any]:
    """One-line summary.

    Args:
        fqdn: Fully-qualified domain name.
    """
    try:
        return await get_client(ctx).get_domain(fqdn)
    except Exception as e:
        handle_client_error(e)
```

### Adding a write (non-purchasing) tool
```python
@mcp.tool(
    tags={"gandi", "domain", "write"},
    annotations={"readOnlyHint": False, "destructiveHint": False},
)
async def domain_set_nameservers(ctx: Context, fqdn: str, nameservers: list[str]) -> dict[str, Any]:
    """..."""
    try:
        assert_readwrite(ctx, "update nameservers")
        return await get_client(ctx).set_nameservers(fqdn, nameservers)
    except Exception as e:
        handle_client_error(e)
```

### Adding a purchase tool
```python
@mcp.tool(
    tags={"gandi", "domain", "write", "purchase"},
    annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
)
async def domain_register(ctx: Context, data: dict[str, Any]) -> dict[str, Any]:
    """SPENDS MONEY. Requires GANDI_MODE=readwrite AND GANDI_ALLOW_PURCHASES=true."""
    try:
        assert_readwrite(ctx, "register domain")
        assert_purchases_allowed(ctx, "register domain")
        return await get_client(ctx).register_domain(data)
    except Exception as e:
        handle_client_error(e)
```

## Gandi API notes

- **Auth**: `Authorization: Bearer <PAT>`. The legacy `Apikey <key>` scheme is deprecated; use Bearer PATs.
- **Base URL**: `https://api.gandi.net`
- **Sharing ID**: passed as `?sharing_id=<uuid>` query parameter; applied to every request by `BaseGandiClient._merge_sharing_id` when `GANDI_SHARING_ID` is set.
- **Rate limits**: 429 maps to `GandiRateLimitError`; the `Retry-After` header (seconds form only) is parsed onto `retry_after` and echoed in the surfaced `ToolError`.

## Non-obvious invariants

Properties enforced across files. A regression that quietly breaks any of these will pass local CI only if its test is also removed — each has a dedicated test pinning it.

- **`sharing_id` is operator-owned.** `BaseGandiClient._merge_sharing_id` unconditionally overrides any caller-supplied `sharing_id` in params; a caller passing a *different* value raises `ValueError`. A future tool that forwards `**kwargs` cannot silently bypass operator scoping.
- **`GandiConfig` is frozen.** Safety flags (`gandi_mode`, `gandi_allow_purchases`) cannot be reassigned after construction.
- **`create_server(config)` threads config into the lifespan via a closure.** `_build_lifespan(config)` is called from `create_server` so visibility-gating and runtime-asserts see the same config. The lifespan does **not** re-read env vars.
- **`validate_connection` raises** the underlying typed exception on failure (returns `None` on success). The lifespan classifies the exception into an actionable operator message — do not collapse it back to `bool`.
- **POST / PATCH timeouts are never retried.** `BaseGandiClient._request` narrows `retry_on` to `ConnectError` only for non-GET/HEAD methods, preventing double-spend on purchase endpoints. `GandiTimeoutError.method` carries the HTTP method; `handle_client_error` uses it to warn the agent to check state before retrying a non-idempotent call.
- **`GandiError.details`** holds the parsed JSON error body when Gandi returned one (Content-Type `application/json`); `cause` and `message` fields are surfaced in the exception message.
- **Path segments are percent-encoded** via `_seg()` in `clients/gandi.py`. Raw `{fqdn}` / `{name}` / `{mailbox_id}` interpolation into URL paths is a regression — the helper is there to prevent `/` or `?` in a DNS record name from shifting into a different API path.
- **Empty response body is an error unless 204.** `BaseGandiClient._parse_json` only returns `{}` for 204; any other status with no content raises `GandiError` rather than silently pretending the API returned an empty object.
- **`authenticated` checks non-empty token.** `GandiConfig.authenticated` requires both `gandi_token is not None` AND a non-empty secret value; an empty-string `GANDI_TOKEN=` fails closed with the clean "not configured" branch, not a 401 from the API.
- **`GANDI_MAX_RETRIES >= 1`** — the field is "total attempts including the first" (1 = no retry). `0` would make `tenacity.stop_after_attempt(0)` stop before the first attempt, breaking every request.
