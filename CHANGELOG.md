# Changelog

All notable changes to this project are documented in this file. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- 8-bit Gandi favicon and logo asset.
- `SECURITY.md` with PAT-rotation procedure.
- `tests/property/` and `tests/integration/` skeleton (PY-013, PY-014, MCP-012, MCP-013).
- `.github/workflows/codeql.yml` for static security analysis on push/PR + weekly schedule (MCP-015).
- Stderr-bound JSON logging via `gandi_mcp._logging.configure_logging`, invoked from `__main__.main()` (MCP-021, MCP-022).
- `GandiConfig.writes_enabled` property — alias of `is_readwrite` using the canonical PROTO-006 vocabulary.
- Granular `register_<area>_<tier>_tools` helpers for every tool module plus top-level `register_read_tools` / `register_write_tools` in `gandi_mcp.tools` (PROTO-005).

### Changed
- **BREAKING.** Every public MCP tool name now carries the `gandi_` namespace prefix (PROTO-002). Examples:
  - `domain_register` → `gandi_domain_register`
  - `livedns_create_record` → `gandi_livedns_create_record`
  - `cert_revoke` → `gandi_cert_revoke`

  Operators with the old names wired into Claude Desktop / Cursor / Continue.dev configs must update them.
- Every tool docstring now includes both `Args:` and `Returns:` sections (PROTO-004).
- `requires-python` bumped from `>=3.11` to `>=3.13`. CI matrix narrowed to 3.13 only (PY-002).
- Type-checker swapped from `mypy` to `ty` in dev deps, CI, pre-commit, README, and CLAUDE.md (PY-008).
- Lifespan log line that fires when no Gandi credential is configured no longer contains the literal env-var name; the README/CONFIGURATION docs are now the single source of truth for the variable's exact spelling (PROTO-012).

### Removed
- `mypy` and the `[tool.mypy]` configuration block.
- Python 3.11 / 3.12 from the supported runtime classifiers and CI matrix.

[Unreleased]: https://github.com/millsmillsymills/gandi-mcp/compare/HEAD...HEAD
