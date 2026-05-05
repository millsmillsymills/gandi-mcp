# Security Policy

## Reporting a vulnerability

Email the maintainer or open a private security advisory on GitHub. Please do
not file public issues for unpatched vulnerabilities.

## Operator responsibilities

This server is configured locally via `.env` (see `.env.example`). Two things
are entirely the operator's responsibility:

### Personal Access Token hygiene

`GANDI_TOKEN` is a Bearer credential with full scope on the owning account —
including read access to account PII (name, address, phone). Treat it like any
other production secret:

- Never commit `.env`. The file is gitignored; verify before pushing.
- Rotate the token in `admin.gandi.net` → Security → Personal Access Tokens
  whenever it may have been exposed (shell history, terminal scrollback,
  shared screenshots, transcripts, leaked logs).
- Gandi's v5 REST API does **not** expose a PAT-revoke endpoint. Revocation
  is UI-only. There is no programmatic way for this server (or any tool) to
  invalidate a leaked PAT — only the operator can.
- Prefer scoped PATs over full-access ones when Gandi's UI permits it.

### Scope gating

The three-tier safety model (`GANDI_MODE`, `GANDI_ALLOW_PURCHASES`) is
defense-in-depth, not a substitute for hygiene. A `readwrite` PAT in the wrong
hands is fully exploitable regardless of how this server is configured —
because the attacker can simply use the raw API.

## What the repo guarantees

- No PAT, password, or account PII is committed in any tracked file or in any
  commit in `git log --all`.
- `.env` and `.env.example` schemas are kept in sync; the example always ships
  with empty secrets.
- CI workflows pin every action to a SHA, run with `persist-credentials: false`
  and the minimum `permissions:` block, and audit dependencies on every push.
