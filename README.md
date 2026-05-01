# gandi-mcp

Production-grade Python MCP server for the [Gandi v5 API](https://api.gandi.net/docs/reference/).

## Status

**Under active development** — see [CLAUDE.md](CLAUDE.md) for the architectural overview.

## Features

- **71 MCP tools** covering Gandi Domains, LiveDNS, Email, Billing, Organization, and Certificates (34 read / 29 write / 8 purchase)
- **Three-tier safety model** — readonly (default) → readwrite → readwrite + purchases, gated at both tool-visibility and handler-runtime layers
- **No-purchasing mode** — tools that spend money (domain registration, renewal, transfer-in, cert issuance, mailbox slots) are hidden by default even in readwrite mode
- **Bearer auth** with optional `sharing_id` scoping for reseller / multi-org accounts
- **Typed, linted, tested** — strict mypy, ruff, pytest, bandit

## Quick Start

```bash
# Install from source
git clone https://github.com/millsmillsymills/gandi-mcp.git
cd gandi-mcp
uv sync --extra dev

# Configure
cp .env.example .env
# Edit .env — at minimum set GANDI_TOKEN

# Run
uv run gandi-mcp
```

### Global install (system-wide CLI)

To install `gandi-mcp` as a global binary on `PATH` (useful when wiring it into Claude Code without a per-project checkout):

```bash
# From the cloned repo
uv tool install /absolute/path/to/gandi-mcp

# Refresh after pulling new commits
uv tool upgrade --reinstall gandi-mcp

# Verify
gandi-mcp --help
```

## Configuration

See [.env.example](.env.example) for every option.

| Variable | Default | Description |
|---|---|---|
| `GANDI_TOKEN` | — | **Required.** Personal Access Token from https://admin.gandi.net/ |
| `GANDI_SHARING_ID` | — | Optional organization UUID to scope all requests to |
| `GANDI_MODE` | `readonly` | `readonly` hides all write tools; `readwrite` exposes them |
| `GANDI_ALLOW_PURCHASES` | `false` | When `true` AND `GANDI_MODE=readwrite`, exposes tools that spend money |
| `GANDI_API_BASE_URL` | `https://api.gandi.net` | Override only for testing |
| `GANDI_REQUEST_TIMEOUT` | `30` | Request timeout in seconds |
| `GANDI_MAX_RETRIES` | `3` | Retry attempts on connection errors |

## Safety model

Three tiers, two orthogonal gates:

| Mode | Purchases | Tools visible |
|---|---|---|
| `readonly` (default) | n/a | Read tools only |
| `readwrite` | `false` (default) | Read + non-purchasing writes (DNS records, contacts, mailbox edits, cert revoke, …) |
| `readwrite` | `true` | Everything including `domain_register`, `domain_renew`, `domain_transfer_in`, `email_create_mailbox`, `email_create_slot`, `email_renew_mailbox`, `cert_issue`, `cert_renew` |

Defense-in-depth: every write tool *also* checks the mode at handler time, and every purchase tool *also* checks the purchase flag, so a stale tool list cached by an MCP client can't slip a write through.

## Claude Code integration

Register the server in `~/.claude.json` (global) or `.claude/settings.json` (project).

**With a global install** (`uv tool install`, recommended for global config — no project directory required):

```json
{
  "mcpServers": {
    "gandi": {
      "command": "gandi-mcp",
      "env": {
        "GANDI_TOKEN": "your-bearer-pat-here",
        "GANDI_MODE": "readonly",
        "GANDI_ALLOW_PURCHASES": "false"
      }
    }
  }
}
```

**From a working copy** (picks up local edits live):

```json
{
  "mcpServers": {
    "gandi": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/gandi-mcp", "run", "gandi-mcp"]
    }
  }
}
```

In the working-copy form, environment variables are read from `.env` in the project directory. In the global-install form, set them under `env` in the JSON or via your shell environment.

Default the global config to `GANDI_MODE=readonly` until you actively need writes — every session inherits the mode you set here.

## Limitations

Gaps in Gandi's v5 REST API that this server cannot work around. Each requires manual action in the Gandi web UI:

- **Registrar transfer-lock toggle.** v5 reports `clientTransferProhibited` in `domain_get_domain` / `domain_get_status` responses but exposes no PATCH/PUT endpoint to set it. Unlock from `Domains → <domain> → Transfer lock` before initiating a registrar transfer-out.
- **Email subscription cancellation.** `email_refund_slot` only refunds an unused slot within the refund window — there is no v5 endpoint to stop a recurring email subscription. Cancel from `Billing → Subscriptions`.
- **Outbound transfer status / approval.** v5 does not surface outbound-transfer state. Gandi sends an FOA email; approve there.

## Development

```bash
# Lint and format
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Type check
uv run mypy src/gandi_mcp/

# Unit tests
uv run pytest tests/unit/ -v

# Pre-commit hooks
uv run pre-commit install
```

## License

Apache-2.0 — see [LICENSE](LICENSE).
