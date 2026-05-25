# graphify — Setup Guide

Cross-platform install + activation. ~5 minutes for CLI, +5 for MCP server.

> Source: <https://github.com/safishamsi/graphify>. Defer to upstream if instructions diverge.

---

## Prerequisites

- Python **3.10+** on PATH.
- `uv` installed (`brew install uv` / `winget install astral-sh.uv` / `curl -LsSf https://astral.sh/uv/install.sh | sh`).
- ~200 MB disk for graphify + its dependencies.

---

## 1. Install (cross-platform)

The PyPI package name is **`graphifyy`** (double-y — the short name was taken). The CLI binary is `graphify`.

```bash
# Recommended — directly from upstream (guaranteed latest, explicit source):
uv tool install git+https://github.com/safishamsi/graphify

# Or via PyPI:
uv tool install graphifyy

# Alternative — pipx:
pipx install graphifyy
```

Verify:

```bash
graphify --help
```

### Register skill in Claude Code

```bash
# Linux / macOS:
graphify install --platform claude

# Windows:
graphify install --platform windows
```

Writes `~/.claude/skills/graphify/SKILL.md` and registers `/graphify` system-wide. Available in every project — **user-global, not project-local**.

Other supported platforms: `codex`, `opencode`, `aider`, `claw`, `droid`, `trae`, `gemini`, `cursor`, `antigravity`, `hermes`, `kiro`, `pi`.

---

## 2. Generate a graph for your project

From the project root:

```bash
graphify .
```

Output appears in `./graphify-out/`:

- `graph.html` — open in any browser
- `GRAPH_REPORT.md` — Markdown overview
- `graph.json` — full graph data

**Recommended**: add `graphify-out/` to your project's `.gitignore` — output is reproducible from source.

---

## 3. Wire the MCP server (roadmap — not yet released)

> **Status as of May 2026**: MCP-server version is on the upstream roadmap ([issue #146](https://github.com/safishamsi/graphify/issues/146)) but **not shipped**. The `templates/mcp-config.json.snippet` in this directory is a placeholder for when it ships. For now, use the skill via `/graphify` (inside Claude Code) or the CLI (`graphify .`).
>
> The skill-based path covers most workflows: Claude reads `graphify-out/graph.json` directly via the file system and uses the BFS/DFS query tools the skill exposes. No MCP server needed for that.

### Why `--with mcp` (when it ships)

The PyPI package is **`graphifyy`** (double-y, not `graphify-mcp`). The CLI binary it installs is just `graphify`. When the upstream MCP module ships, the launcher will need an explicit `--with mcp` because **graphifyy does NOT pull the `mcp` package into its dependencies** — running `python -m graphify.serve graph.json` straight from a `graphifyy` install fails with `ModuleNotFoundError: No module named 'mcp'`.

Workaround (already baked into the snippet):

```bash
uv tool run --from graphifyy --with mcp python -m graphify.serve graphify-out/graph.json
```

`--with mcp` tells `uv` to inject `mcp` into the temporary tool environment alongside `graphifyy`. Until upstream adds `mcp` to its dependencies (or to a `[serve]` extra), this is the working invocation.

> If you see `MCP server graphify failed to start: ModuleNotFoundError` in `/mcp` output after enabling the block, the `--with mcp` flag was lost during merge into `.mcp.json` — check `args` and reapply from the snippet.

---

## 4. Restart Claude Code and verify

After `graphify install`, restart Claude Code. The `/graphify` slash command should be in the skills list.

---

## 5. Use it

CLI (always available after install):

```bash
graphify .                       # regenerate the graph
graphify . --include "src/**"    # restrict to src/
```

MCP (after server registered):

```
> What are the most-connected modules in this project?
> Show me the shortest path from `cli` to `database`.
> Walk me through the architecture.
```

---

## Recommended workflow

1. **First time on a new codebase** — run `graphify .`, open `GRAPH_REPORT.md`, read the agent's questions.
2. **Before a large refactor** — run `graphify .`, save the report. After the refactor, run again, diff the reports.
3. **For periodic reviews** — `graphify .` once a month, commit `GRAPH_REPORT.md` only (not the JSON) for change tracking.

---

## Troubleshooting

### `graphify: command not found`

- `uv tool install` puts binaries in `~/.local/bin` (Linux/macOS) or `%USERPROFILE%\.local\bin` (Windows). Ensure that's on PATH:

  ```bash
  # macOS / Linux
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc

  # Windows (PowerShell, persistent)
  [Environment]::SetEnvironmentVariable("Path", "$env:Path;$env:USERPROFILE\.local\bin", "User")
  ```

### Graph generation is slow

- Large repos with many languages take time. Filter: `graphify . --include "src/**" --exclude "data/**"`.
- Video/audio extraction is the slowest — `--exclude "**/*.mp4" --exclude "**/*.mp3"` if you don't need them.

### MCP server can't find graph.json

- Regenerate first: `graphify .`. The snippet assumes `graphify-out/graph.json` exists.
- If you generated into a custom path, edit the `args` in `.mcp.json` accordingly.

---

## Uninstall

```bash
uv tool uninstall graphify
rm -rf graphify-out/                    # macOS / Linux
Remove-Item -Recurse -Force graphify-out\   # Windows PowerShell
```

Remove the `graphify` block from `.mcp.json` and restart Claude Code.

---

## Security notes

- graphify reads source files only — no network, no execution of project code.
- The HTML visualization runs in your browser; treat `graph.html` like any local HTML — open via `file://`, don't host it.
- Output may contain code snippets / comments / docstrings — exclude from publication if your code is private.
