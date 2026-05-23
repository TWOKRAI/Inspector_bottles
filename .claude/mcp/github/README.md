# github-mcp — official GitHub MCP server

Optional MCP module. Wraps the GitHub REST/GraphQL API behind 80+ MCP tools — Issues, PRs, Actions, Projects, releases, repo search, OAuth-scoped access.

> Upstream: <https://github.com/github/github-mcp-server>
> **License:** MIT · **Status as of 2026-05:** ~20k★, official, OAuth scope filtering, remote (`mcp.github.com`) + local builds

## When to enable

✅ **Enable when:**
- You routinely do PR / issue / Actions work and currently rely on shell `gh` calls
- You want the agent to read CI logs / failing checks without screen-scraping
- The project lives on GitHub and the team uses Projects / Issues actively
- You're hitting `gh`-rate limits or want OAuth-scoped read-only tokens

❌ **Skip when:**
- Project isn't on GitHub (GitLab, Bitbucket, self-hosted Gitea)
- You only need read-only repo metadata once in a while — `gh` CLI is fine
- Strict no-network policy

## How it differs from shell `gh`

| Question | `gh` CLI | github-mcp |
|----------|----------|------------|
| "What checks failed on PR #42?" | parse text output | structured JSON + log streaming |
| "List open issues mentioning auth" | yes, but verbose | one tool call, paginated |
| "Trigger workflow X on branch Y" | yes | yes |
| Streaming a 50MB CI log | shell-buffered | structured chunks |
| Scope-limited token | manual `--repo` per call | OAuth scope filter enforced |
| Rate-limiting visibility | none | exposed in `status` tool |

The agent can still call `gh` — github-mcp is preferred for any task that becomes a multi-step shell parse.

## Recommended scope (OAuth)

Default to the **minimum** scope. The README enumerates per-tool scope requirements. Common safe defaults:

- `repo:read` + `actions:read` + `issues:read` — read-only audit / CI inspection
- `repo` + `issues:write` + `pull_requests:write` — task automation (add this only when needed)

Avoid `repo:write` until the agent has a track record in the project. The seed's principle (least privilege at MCP layer) applies double here.

## Setup

See [SETUP_GUIDE.md](SETUP_GUIDE.md) for both remote (OAuth) and local (PAT) wire-ups.

## Tool routing snippet (paste into project `CLAUDE.md`)

> When github-mcp is enabled in this project:
> - **PR / issue / Actions / project board** queries → **github-mcp**
> - `git` local ops (status, log, diff, commit) → **shell `git`** (always cheaper)
> - One-off repo lookup without auth setup → **`gh` CLI**
> - Do NOT call github-mcp to read files at a known path — read locally.

## Conflicts / overlap in this seed

- **Replaces ad-hoc `gh` usage** in `/ship`, `/handoff`, `/review`. Worth updating those commands' prompts after enabling.
- **Does NOT replace** `git` local ops — those stay shell-based for speed.
- No overlap with qex / sentrux / graphify / serena / codegraph (different domain — GitHub state vs local code).
