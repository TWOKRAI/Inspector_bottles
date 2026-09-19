# qex — semantic code search across the codebase

This folder is **everything needed to set up qex + Ollama in a new project**.
Copy it as a whole into the new project, go through the 5 steps below, and search works.

## What this is

**qex** (v0.0.2, feature `vector`) is a local MCP server (Rust) that performs
hybrid (BM25 + dense) semantic search over the codebase. It plugs into Claude Code via MCP.

- **BM25** is indexed by Tantivy — a local file under `~/.qex/`.
- **Dense vectors** are computed by Ollama (Windows — `qwen3-embedding:0.6b-qex`, 1024-dim; macOS — `qwen3-embedding:8b-qex`, 4096-dim) and stored under `~/.qex/` (a JSON file, brute-force cosine).
- **Chunking** — tree-sitter over the AST (classes, functions, methods).
- **Ignore rules** are read from `.gitignore` and `.ignore` (like ripgrep) automatically.

Docker and Qdrant are **not needed**. The only external dependency is Ollama.

Full documentation with architecture, diagnostics and troubleshooting — in [SETUP_GUIDE.md](./SETUP_GUIDE.md).

## Quick-start (5 steps)

Assumes the `qex` binary and Ollama are already installed globally
(instructions in [SETUP_GUIDE.md](./SETUP_GUIDE.md), sections 3–5). For a **new project**:

### 1. Copy the `.ignore` template into the project root

```bash
cp .claude/plugins/mcp-qex/templates/ignore.template .ignore
```

Open `.ignore` and edit the whitelist block for your project — keep only the active
working directories, exclude everything else. This is critical for search quality:
less noise = cleaner ranking. See the comments inside the template.

### 2. Create `.mcp.json` in the project root

Copy the `templates/mcp-config.json.snippet` template into `.mcp.json` (project root).
Replace the two placeholders:

- `<QEX_BINARY_PATH>` — absolute path to `qex` (usually `~/.cargo/bin/qex` on macOS, `~\.cargo\bin\qex.exe` on Windows)
- `<PROJECT_ABSOLUTE_PATH>` — absolute path to the project root

### 3. Start Ollama

```bash
# Ollama — REQUIRED before starting Claude Code
ollama serve &

# Check
curl -s http://localhost:11434/ && echo " Ollama OK"
```

### 4. Restart Claude Code

So the new MCP configuration is picked up. In VS Code: `Ctrl/Cmd+Shift+P → Developer: Reload Window`.

### 5. First indexing

In a chat with Claude Code:

```
mcp__qex__index_codebase(path="<PROJECT_ABSOLUTE_PATH>", force=true)
```

After 30-40 minutes (depends on codebase size and GPU) — done. Check:

```
mcp__qex__get_indexing_status(path="<PROJECT_ABSOLUTE_PATH>")
mcp__qex__search_code(path="<PROJECT_ABSOLUTE_PATH>", query="main application class")
```

## Daily startup

```bash
ollama serve &
# Start Claude Code — qex comes up automatically
```

## When to reindex

- After major code changes — `mcp__qex__index_codebase(path=..., force=true)`.
- After changing the embedding model — `clear_index` → `index_codebase(force=true)`.
- After editing `.ignore` — `clear_index` + `index_codebase(force=true)` is mandatory, otherwise excluded files stay in the index.
- Optional: a git post-commit hook for automatic reindexing — see `hooks/git/post-commit.d/qex-reindex.sh`.

## When qex is NOT needed

- You know the exact file path → use Read / Grep directly, it's faster and more precise.
- You're searching by an exact, unique symbol name → Grep with `-n` is faster.
- qex is needed when you're searching **by meaning** or **don't remember the path**.

## Folder structure

```
.claude/plugins/mcp-qex/
├── README.md                       # this file
├── SETUP_GUIDE.md                  # full guide (Windows + macOS, diagnostics)
├── hooks/git/post-commit.d/
│   └── qex-reindex.sh              # post-commit PART, run by the core dispatcher
└── templates/
    ├── ignore.template             # .ignore template for the whitelist filter
    └── mcp-config.json.snippet     # JSON for .claude/mcp.json
```

## Links

- [SETUP_GUIDE.md](./SETUP_GUIDE.md) — full manual (architecture, diagnostics, common issues)
- [templates/ignore.template](./templates/ignore.template) — .ignore template
- [templates/mcp-config.json.snippet](./templates/mcp-config.json.snippet) — MCP config
- [hooks/git/post-commit.d/qex-reindex.sh](./hooks/git/post-commit.d/qex-reindex.sh) — post-commit PART
## Launcher options

**Default** (used automatically by `claude-kit add qex`): see `.claude-plugin/plugin.json` → `mcpServers.qex`.

```
command: python
args: [".claude/plugins/mcp-qex/qex-launcher.py"]
```

Only one launcher — qex bootstraps itself via the local Python interpreter.

Switching: edit `.mcp.json` manually (it's not regenerated for non-manifest content).
