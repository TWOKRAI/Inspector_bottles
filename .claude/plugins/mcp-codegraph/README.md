# codegraph — pre-indexed call graph + symbol navigation

Optional MCP module. Builds a local SQLite-backed semantic code graph (nodes = functions/classes, edges = calls/imports/inheritance) via tree-sitter, exposes a **single** `codegraph_explore` MCP tool (verbatim source + call path + blast-radius in one call), and keeps itself in sync via a native OS file-watcher.

> Upstream: <https://github.com/colbymchenry/codegraph>
> **License:** MIT · **Package:** `@colbymchenry/codegraph` v0.4.x — single-tool API (`codegraph_explore`).

## When to enable

✅ **Enable when:**
- You need **caller/callee/impact** queries on the function level (not module level — sentrux already covers modules)
- Refactor-heavy work: "if I rename `X`, what breaks?", "what tests cover changes in file `Y`?"
- Project uses a **web framework** with explicit routes (FastAPI / Django / Express / Rails / etc.) — codegraph maps URL patterns to handlers
- Codebase is mid-to-large (5k–500k LOC) and qex+Ollama feels heavy / slow / not always available (CI runners without GPU)
- You want **auto-sync** without a post-commit hook (native file-watcher)

❌ **Skip when:**
- Project < 5k LOC — Read + Grep already cover this
- You only do semantic / intent search ("find code that does X") — that's qex's job, not codegraph's
- You don't want a Node 18+ dependency in this project's tooling
- qex + sentrux + graphify already give you the answers you need

## How it differs from the rest of the seed

| Question | Best tool | Why |
|----------|-----------|-----|
| "Who calls `Manifest.load()`?" | **codegraph** (`codegraph_explore`) | call path in the response, function-level |
| "If I rename `parse_args`, what breaks?" | **codegraph** (`codegraph_explore`) | blast-radius section across files |
| "What tests are affected by changes in `runner.py`?" | **codegraph** (`codegraph_explore`) | covering tests listed in blast-radius |
| "Which handler serves `POST /api/seed/apply`?" | **codegraph** (framework routing) | URL → handler mapping |
| "Find code that parses YAML manifests" (fuzzy intent) | **qex** | dense embeddings, semantic |
| "Are there import cycles? Layer violations?" | **sentrux** | DSM, architectural rules |
| "God-nodes, hubs, shortest path between modules" | **graphify** | visual graph, community detection |
| "Exact substring `qex-launcher`" | **Grep** | always cheaper than MCP for literal strings |

**Bottom line:** codegraph fills a real gap — function-level call graph + impact + framework routing. It does **not** replace qex (no semantic embeddings), sentrux (no metrics / health gate), or graphify (no visualization).

## Supported languages

19+ via tree-sitter: TypeScript, JavaScript, Python, Go, Rust, Java, C#, PHP, Ruby, C, C++, Swift, Kotlin, Dart, Svelte, Vue, Scala, Pascal/Delphi, Liquid.

Framework-aware routing: Django, Flask, FastAPI, Express, Laravel, Rails, Spring, Gin, Axum, ASP.NET, Vapor, React Router, SvelteKit.

## MCP tool exposed (1)

The installed package exposes a **single** tool — one call replaces the whole search/Read/Grep loop:

| Tool | Purpose |
|------|---------|
| `codegraph_explore(query, maxFiles?, projectPath?)` | `query` = NL question **or** bag of symbol/file names. Returns: verbatim line-numbered source grouped by file (Read-equivalent) + call path (callers/callees) + blast-radius (what depends on it + covering tests) + relationships (extends/instantiates/calls). |

> Earlier docs listed 8 separate tools (`codegraph_search` / `callers` / `callees` / `impact` / `context` / `node` / `files` / `status`). The current `@colbymchenry/codegraph` collapses all of that into the one `codegraph_explore` call above.

## Storage and footprint

- All data is local in `.codegraph/codegraph.db` (SQLite + FTS5 in WAL mode)
- No external API, no embeddings, no GPU
- Native `better-sqlite3` if available; falls back to WASM (5–10× slower) otherwise
- Add `.codegraph/` to project `.gitignore`

## Tool routing snippet (paste into project `CLAUDE.md`)

> When codegraph is enabled in this project:
> - Function-level **callers / callees / impact / rename safety** → **codegraph** (`codegraph_explore`)
> - **Fuzzy intent search** ("code that does X") → **qex**
> - **Architectural health** (cycles, layers, metrics) → **sentrux**
> - **Visual overview** (hubs, shortest path) → **graphify**
> - Exact substring or known file path → **Grep / Read** (never go through MCP for literals)
> Do not duplicate: if codegraph already gave you the answer, do not re-confirm with Grep.

## Why honest expectations matter

Upstream advertises "94% fewer tool calls, 77% faster". That bench compares an agent with codegraph against a baseline agent with **only Read + Grep + Glob** — no MCP at all. In this seed the baseline is already qex + sentrux + graphify, so the marginal gain is much smaller. Expect codegraph to help on the **call-graph / impact** class of questions specifically — that is where it has no substitute in the current stack. For everything else, qex / sentrux / graphify remain the right tools.

Run the smoke test in `SETUP_GUIDE.md` § 5 before committing to it — measure on your own questions, not the upstream README.

## Setup

See [SETUP_GUIDE.md](SETUP_GUIDE.md) for install, MCP wire-up, first index, and a 5-question smoke test.
## Launcher options

**Default** (used automatically by `claude-kit-claude plugin enable mcp-codegraph`): see `.claude-plugin/plugin.json` → `mcpServers.codegraph`.

```
command: npx
args: ["-y", "@colbymchenry/codegraph", "serve", "--mcp"]
```

⚠ Requires `codegraph index` per-project before first use (see "Setup").

**Alternative** (`npm i -g @colbymchenry/codegraph`): see `templates/mcp-config.json.snippet`.

Switching: edit `.mcp.json` manually (it's not regenerated for non-manifest content).
