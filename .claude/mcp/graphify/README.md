# graphify — knowledge graph of the codebase

Optional MCP module + CLI. Turns code (and docs, SQL schemas, videos) into a queryable knowledge graph: HTML visualization, Markdown report, JSON for programmatic access.

> Upstream: <https://github.com/safishamsi/graphify>

## When to enable

✅ **Enable when you want:**
- A **bird's-eye view** of an unfamiliar codebase (god nodes, unexpected connections)
- Architecture documentation refreshed automatically from source
- A graph the agent can query — "what depends on `auth.py`?", "shortest path between `cli` and `database`?"
- Periodic review of how the project's structure evolves

❌ **Skip if:**
- Project is < 1k LOC — qex + Grep cover it without needing a graph
- You already use sentrux for DSM analysis (overlap, decide on one)
- Your codebase is single-file scripts

## How it differs from related tools

| Tool | What it does best | When to choose |
|------|-------------------|---------------|
| **graphify** | Visual graph of nodes + edges, interactive HTML, MCP for querying | Architecture review, onboarding, finding unexpected coupling |
| **qex** | Hybrid semantic + BM25 search over code chunks | "Find code that does X" — fuzzy intent search |
| **sentrux** | Dependency Structure Matrix, architectural metrics, rule violations | Enforce invariants, catch cycles, gate quality in CI |
| **Serena** (LSP) | Symbol-level operations (refs, renames, moves) | Exact refactoring on known symbols |

These complement each other; graphify is the **map**, the others are the **GPS** and **tools**.

## What graphify produces

Running `graphify <path>` creates a `graphify-out/` folder with:

- **`graph.html`** — interactive visualization (open in any browser)
- **`GRAPH_REPORT.md`** — architecture overview + recommended questions to ask
- **`graph.json`** — full graph, machine-readable

The MCP server (when enabled) exposes:
- `query_graph(natural_language)` — ask questions in plain English
- `get_node(name)` — full info on one node
- `shortest_path(a, b)` — connection between two nodes

## Supported languages

31 languages: Python, TypeScript/JavaScript, Go, Rust, Java, C/C++, Ruby, PHP, C#, Kotlin, Swift, Scala, R, Lua, SQL schemas, Markdown, PDF, Office docs, video/audio.

## Status

- Actively maintained as of 2026.
- Cross-platform (uses Python + uv tool ecosystem).
- Output is reproducible from source — safe to add `graphify-out/` to `.gitignore`.

## Setup

See [SETUP_GUIDE.md](SETUP_GUIDE.md) for install. The CLI works standalone; the MCP server is opt-in on top.

## Tool routing

When graphify is active:

| Question | Where to start |
|----------|----------------|
| "Give me an architectural overview" | `/quality:graph` (run graphify CLI) — read `GRAPH_REPORT.md` |
| "What are the god nodes / hubs of this codebase?" | graphify MCP — `query_graph` |
| "Show me modules with no incoming dependencies" (entry points) | graphify MCP |
| "How are `auth` and `database` connected?" | graphify MCP — `shortest_path` |
| "Find the function that parses XML responses" | qex (semantic search) — graphify is structure, not semantics |
