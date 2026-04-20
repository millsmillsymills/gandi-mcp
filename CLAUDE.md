# CLAUDE.md — Project Intelligence for gandi-mcp

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
    ├── organization.py  # 5 read tools
    ├── billing.py       # 3 read tools
    ├── domain.py        # 12 read + 11 write (+ 3 purchase) tools
    ├── livedns.py       # 6 read + 10 write tools
    ├── email.py         # 5 read + 7 write + 3 purchase tools
    └── certificate.py   # 2 read + 1 write + 2 purchase tools
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
- **Tests**: `respx` for HTTP mocking, `pytest-asyncio` for async tests. Live read-only smoke tests run against api.gandi.net.
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

- **Auth**: `Authorization: Bearer <PAT>`. The legacy `Apikey <key>` scheme returns 403 on the v5 API as of 2025.
- **Base URL**: `https://api.gandi.net`
- **Sharing ID**: passed as `?sharing_id=<uuid>` query parameter; applied to every request by `BaseGandiClient._merge_sharing_id` when `GANDI_SHARING_ID` is set.
- **Rate limits**: Gandi returns 429 with a `Retry-After` header — the client currently maps 429 to `GandiRateLimitError` but does not auto-sleep; agents should back off on the surfaced error.
