# github-mcp — Setup Guide

Two paths: **remote** (recommended — OAuth, no PAT in config) or **local** (Go binary + PAT).

> Source: <https://github.com/github/github-mcp-server>. Defer to upstream if instructions diverge.

---

## Path A: Remote (OAuth, recommended)

GitHub hosts a managed MCP endpoint at `https://mcp.github.com`. The agent authenticates via OAuth on first use — no token lives in your config.

### 1. Append to project `.mcp.json`

```json
{
  "github": {
    "type": "http",
    "url": "https://mcp.github.com/mcp"
  }
}
```

### 2. Restart Claude Code

`/mcp` → on first call, Claude Code will open a browser for OAuth authorization. Accept the scope.

### 3. Adjust scope

After the first authorization, manage scopes at <https://github.com/settings/connections/applications> — find "Claude" / "MCP" and trim permissions to the minimum needed.

---

## Path B: Local binary (PAT-based)

Use this if you need self-hosted control, on-prem GitHub Enterprise, or fine-grained PAT scoping.

### 1. Install the Go binary

```bash
# macOS / Linux
go install github.com/github/github-mcp-server@latest

# Or download a release:
# https://github.com/github/github-mcp-server/releases
```

### 2. Create a Personal Access Token

<https://github.com/settings/tokens?type=beta> — fine-grained PAT. Scope to:

- Specific repositories (not "all repositories")
- Permissions: `Contents: Read`, `Issues: Read/Write`, `Pull requests: Read/Write`, `Actions: Read` (adjust per need)
- Expiration: 30–90 days

### 3. Append to project `.mcp.json` (or `.env`-driven config)

```json
{
  "github": {
    "command": "github-mcp-server",
    "args": ["stdio"],
    "env": {
      "GITHUB_PERSONAL_ACCESS_TOKEN": "${GH_MCP_TOKEN}"
    }
  }
}
```

Put `GH_MCP_TOKEN` in your shell env or `.env` — **never commit the token**.

### 4. Smoke test

```bash
github-mcp-server --version
```

Restart Claude Code, then `/mcp` should show `github` connected.

---

## GitHub Enterprise

Both paths support GHE. For remote: replace `https://mcp.github.com/mcp` with your GHE-hosted endpoint (check upstream README for the path). For local: set `GITHUB_HOST=https://github.your-company.com/api/v3` in env.

---

## Verifying it works

Ask the agent:

```
Use the github MCP to list open issues with label "bug" in this repo.
```

If you see structured JSON with issue numbers / titles — wired up. If you see a Grep / shell `gh` fallback — re-check `/mcp`.

---

## Troubleshooting

### OAuth flow doesn't open browser (remote)

Some terminal-launch contexts can't open browsers. Use Path B (local PAT) instead.

### "401 Unauthorized" with local PAT

- PAT expired or revoked
- PAT doesn't include the target repo (fine-grained PATs are per-repo)
- Token not actually loaded into env (try `echo $GH_MCP_TOKEN` in CC's terminal)

### Tool calls feel slow

Remote path = HTTP roundtrips to GitHub API. For high-volume operations (e.g. listing 1000+ issues), the local binary with PAT is faster (caches metadata locally).

### Agent ignores github-mcp and uses shell `gh`

Tool routing isn't pinned. Add the routing snippet from [README.md § Tool routing](README.md) to your project root `CLAUDE.md`.

---

## Uninstall

- Remote: remove the `github` block from `.mcp.json`. Revoke the OAuth app at <https://github.com/settings/connections/applications>.
- Local: `rm $(which github-mcp-server)` + remove `.mcp.json` block + revoke PAT.

---

## Security notes

- **Never commit PATs.** Use env vars or your OS keychain (`security`, `secret-tool`, Windows Credential Manager).
- **Audit OAuth grants quarterly** at <https://github.com/settings/connections/applications>.
- **Prefer fine-grained PATs** over classic PATs — scope to specific repos.
- **Rate limits apply.** Heavy automation can blow through 5000 req/hour. github-mcp exposes a `status` tool — check it before bulk operations.
