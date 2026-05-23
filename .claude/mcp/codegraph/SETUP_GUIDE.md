# codegraph — Setup Guide

Cross-platform install + MCP wire-up + first index. ~5 minutes for a small repo, ~minutes for hundreds of thousands of nodes.

> Source: <https://github.com/colbymchenry/codegraph>. Defer to upstream if instructions diverge.

---

## Prerequisites

- **Node.js 18+** on PATH. Verify: `node --version`.
- ~50 MB disk for the package; the index `.codegraph/codegraph.db` grows with the repo (thousands–hundreds of thousands of nodes; tens of MB typical).
- Native `better-sqlite3` is **not** required — codegraph ships a WASM fallback. Install of build tools is optional.

> If your machine has no Node yet:
> - **macOS:** `brew install node`
> - **Windows:** `winget install OpenJS.NodeJS.LTS`
> - **Linux:** use your distro's package or `nvm install --lts`

---

## 1. Install

Two equivalent paths — pick one.

### Option A: global (recommended for daily use)

```bash
npm install -g @colbymchenry/codegraph
codegraph --version
```

### Option B: zero-install via npx

Skip global install; the MCP server snippet uses `npx -y …` and downloads on first run. Slower first invocation, but no system-wide footprint.

---

## 2. Initialize the project

From the project root:

```bash
codegraph init
```

Creates `.codegraph/` with the database and config. Add it to `.gitignore`:

```bash
echo ".codegraph/" >> .gitignore
```

> The seed's root `.gitignore` template does **not** yet list `.codegraph/`. Add the line once per project, or extend `templates/gitignore.template.gitignore` in the seed if you want it everywhere.

---

## 3. First index

```bash
codegraph index .
```

Runtime expectations:

| Repo size | Approx. time |
|-----------|--------------|
| <10k LOC | seconds |
| 10k–100k LOC | <1 min |
| 100k–500k LOC | 1–5 min |
| >500k LOC (e.g. Swift Compiler ~25k files) | <5 min |

Verify:

```bash
codegraph status
codegraph query "<some symbol you know exists>"
```

---

## 4. Wire the MCP server

Append the snippet from `templates/mcp-config.json.snippet` to the project's `.mcp.json` under `mcpServers`. After installing globally:

```json
{
  "codegraph": {
    "command": "codegraph",
    "args": ["serve", "--mcp"]
  }
}
```

Or, without global install (uses npx):

```json
{
  "codegraph": {
    "command": "npx",
    "args": ["-y", "@colbymchenry/codegraph", "serve", "--mcp"]
  }
}
```

The server uses the project root (= Claude Code's working directory) and auto-starts a file-watcher.

### Auto-install via codegraph's own installer (alternative)

codegraph ships an interactive installer that auto-detects Claude Code / Cursor / Codex / opencode and writes their MCP configs for you:

```bash
codegraph install
```

Use this if you want a one-shot setup that also targets other AI tools. The seed pattern is to keep `.mcp.json` under git, so prefer the manual snippet above for reproducibility.

---

## 5. Restart Claude Code and smoke-test

1. Reload Claude Code: `Cmd/Ctrl + Shift + P` → `Developer: Reload Window` (or restart the terminal).
2. `/mcp` should show `codegraph` as connected.
3. Ask the agent the 5 smoke-test questions — these are the ones where codegraph should clearly win against qex / Grep:

   ```
   1. Who calls function <some_function> in this project?
   2. If I rename <some_symbol>, which files break?
   3. What does <some_function> call (callees, recursive depth 2)?
   4. Which test files are affected by changes in <some_source_file>?
   5. Which handler serves <some_route_in_a_web_framework>?   (skip if not a web project)
   ```

   Watch the tool calls. If the agent goes through `codegraph_callers` / `codegraph_impact` / `codegraph_callees` instead of Grep+Read loops, the wire-up works.

   If the agent ignores codegraph and falls back to Grep — see § Tool routing below.

---

## 6. Tool routing — pin it in CLAUDE.md

Without explicit routing, the agent may double-dip (codegraph + Grep on the same question), which **increases** tool calls instead of cutting them. Paste this block into the project's root `CLAUDE.md` under a `## Tool routing` section:

```markdown
## Tool routing (MCP)

- **codegraph** → callers / callees / impact / rename safety / route→handler
- **qex** → fuzzy intent ("find code that does X")
- **sentrux** → architectural health, layer rules, cycles
- **graphify** → visual / structural overview, hubs, shortest path
- **Grep / Read** → exact string or known file path; do NOT route literals through MCP

Do not duplicate: if codegraph already answered "who calls X", do not re-verify with Grep.
```

---

## 7. Keeping the index fresh

The MCP server runs a native OS file-watcher (FSEvents / inotify / ReadDirectoryChangesW) when active. Idle reindex is incremental.

If you edited files **outside** an active Claude Code session, force a sync:

```bash
codegraph sync .
```

Full rebuild (after `.codegraph/` corruption or a major refactor):

```bash
codegraph index . --rebuild
```

---

## Troubleshooting

### `/mcp` shows codegraph as failed

```bash
# Is the binary on PATH (global install path)?
codegraph --version    # or: where codegraph  /  which codegraph

# If using npx, ensure node + npx work:
node --version
npx --version
```

If the binary is fine but MCP still red — restart Claude Code (window reload, not just chat clear).

### "WASM fallback in use — 5–10× slower than native"

codegraph logs this when `better-sqlite3` native module didn't load (no build toolchain on Windows, ARM Mac without Rosetta, etc.). It still works. To get native speed:

```bash
npm rebuild better-sqlite3
```

On Windows you may need `npm i -g windows-build-tools` first (one-time).

### Indexer hangs on huge directories

codegraph respects `.gitignore` by default but **not** `.ignore` (qex's format). If you have generated code, vendor dumps, or `node_modules/large-tree/` outside `.gitignore`, add them there. Or pass `--exclude`:

```bash
codegraph index . --exclude "data/**" --exclude "**/*.generated.ts"
```

### Tool calls didn't drop — agent still uses Grep

Tool routing was likely not pinned. Re-read § 6. If routing is in `CLAUDE.md` and the agent still ignores it, this is a model behavior issue — open an issue upstream with a transcript.

---

## Uninstall

```bash
# Global
npm uninstall -g @colbymchenry/codegraph

# Per-project index
rm -rf .codegraph/          # macOS / Linux
Remove-Item -Recurse -Force .codegraph\   # Windows PowerShell
```

Remove the `codegraph` block from `.mcp.json` and restart Claude Code.

---

## Security notes

- codegraph reads source files only — no network calls, no execution of project code.
- The index database (`.codegraph/codegraph.db`) contains symbol names, file paths, and short text snippets from your code. Treat it like any local cache; do not commit it.
- MCP server binds to stdio (Claude Code IPC), not a network port. Safe by default.
