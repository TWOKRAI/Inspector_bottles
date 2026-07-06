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

## 3. Wire the MCP server (optional)

> graphify MCP is **optional** (`enabled.yaml` → `mcp-graphify.enabled: false`). The `/graphify` skill is the primary path — Claude reads `graphify-out/graph.json` directly and uses the BFS/DFS query tools the skill exposes. Enable the MCP only if you want a live-query server layer.

The upstream MCP server ships as the `graphify-mcp` console script (package **`graphifyy`**, double-y; MCP extra `graphifyy[mcp]`, available since graphifyy 0.8.36). Install with the extra, then register the launcher:

```bash
uv tool install 'graphifyy[mcp]'   # pin: graphifyy >= 0.8.42
```

Canonical launcher (already in `templates/mcp-config.json.snippet`, matching `.claude-plugin/plugin.json`):

```bash
uvx graphify-mcp serve graphify-out/graph.json
```

`uvx` is the single launcher upstream supports. Run `graphify .` first to produce `graphify-out/graph.json` (the server reads it), then merge the snippet block into your project's `.mcp.json` under `"mcpServers"`.

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
