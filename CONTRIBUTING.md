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
