# codegraph — pre-indexed code graph, one-call exploration

Optional MCP module. Builds a local SQLite-backed semantic code graph (nodes = functions/classes, edges = calls/imports/inheritance) via tree-sitter, exposes it to the agent through **one** MCP tool (`codegraph_explore`), and keeps itself in sync via a native OS file-watcher.

> Upstream: <https://github.com/colbymchenry/codegraph>
> **License:** MIT · **Version pinned by this plugin:** 1.6.0 (checked 2026-09-03)

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
| "Who calls `Manifest.load()`?" | **codegraph** (`codegraph_explore`) | exact call graph, function-level |
| "If I rename `parse_args`, what breaks?" | **codegraph** (`codegraph_explore`) | blast radius arrives with the same answer |
| "How does the request reach `apply()`?" | **codegraph** (`codegraph_explore`) | call paths, dynamic-dispatch hops included |
| "Which handler serves `POST /api/seed/apply`?" | **codegraph** (framework routing) | URL → handler mapping |
| "Find code that parses YAML manifests" (fuzzy intent) | **qex** | dense embeddings, semantic |
| "Are there import cycles? Layer violations?" | **sentrux** | DSM, architectural rules |
| "God-nodes, hubs, shortest path between modules" | **graphify** | visual graph, community detection |
| "Exact substring `qex-launcher`" | **Grep** | always cheaper than MCP for literal strings |

**Bottom line:** codegraph fills a real gap — function-level call graph + impact + framework routing. It does **not** replace qex (no semantic embeddings), sentrux (no metrics / health gate), or graphify (no visualization).

## Supported languages

19+ via tree-sitter: TypeScript, JavaScript, Python, Go, Rust, Java, C#, PHP, Ruby, C, C++, Swift, Kotlin, Dart, Svelte, Vue, Scala, Pascal/Delphi, Liquid.

Framework-aware routing: Django, Flask, FastAPI, Express, Laravel, Rails, Spring, Gin, Axum, ASP.NET, Vapor, React Router, SvelteKit.

## MCP tools exposed (1)

| Tool | Purpose |
|------|---------|
| `codegraph_explore` | Answers almost any structural question in one call — "how does X work", a flow ("how does X reach Y"), or a survey of an area. Returns the relevant symbols' verbatim source grouped by file, the call paths between them (dynamic-dispatch hops included), and a blast-radius summary. Naming a file or symbol returns its current line-numbered source. |

Upstream measured that one strong tool steers agents better than a menu of narrow
ones, so since 1.x the seven narrow queries (node, search, callers, callees,
impact, files, status) ship but stay **unlisted** — everything they return already
arrives inline with the explore answer. Two ways to reach them anyway:

- put `CODEGRAPH_MCP_TOOLS=explore,node,search,callers` in the server's `env` to
  re-publish specific ones on the MCP surface;
- use the CLI equivalents, which are always available: `codegraph node`,
  `codegraph query`, `codegraph callers`, `codegraph callees`, `codegraph impact`,
  `codegraph affected`, `codegraph files`, `codegraph status`.

## Storage and footprint

- All data is local in `.codegraph/codegraph.db` (SQLite + FTS5 in WAL mode)
- No external API, no embeddings, no GPU
- Native `better-sqlite3` if available; falls back to WASM (5–10× slower) otherwise
- Add `.codegraph/` to project `.gitignore`

## Tool routing snippet (paste into project `CLAUDE.md`)

> When codegraph is enabled in this project:
> - Function-level **call paths / blast radius / rename safety** → **codegraph** (`codegraph_explore`)
> - **Fuzzy intent search** ("code that does X") → **qex**
> - **Architectural health** (cycles, layers, metrics) → **sentrux**
> - **Visual overview** (hubs, shortest path) → **graphify**
> - Exact substring or known file path → **Grep / Read** (never go through MCP for literals)
> Do not duplicate: if codegraph already gave you the answer, do not re-confirm with Grep.

## Why honest expectations matter

Upstream advertises "88% fewer tool calls, 53% faster, 44% cheaper" (re-measured 2026-08). That bench compares an agent with codegraph against a baseline agent with **only Read + Grep + Bash** — no MCP at all. In this seed the baseline is already qex + sentrux + graphify, so the marginal gain is much smaller. Upstream also reports the flip side honestly: one dense answer stays resident in the window, so end-of-session context occupancy runs ~80% **higher** than a grep-and-read agent's. Expect codegraph to help on the **call-graph / impact** class of questions specifically — that is where it has no substitute in the current stack. For everything else, qex / sentrux / graphify remain the right tools.

Run the smoke test in `SETUP_GUIDE.md` § 5 before committing to it — measure on your own questions, not the upstream README.

## Setup

See [SETUP_GUIDE.md](SETUP_GUIDE.md) for install, MCP wire-up, first index, and a 5-question smoke test.
## Launcher options

**Default** (used automatically by `claude-kit add codegraph`): see `.claude-plugin/plugin.json` → `mcpServers.codegraph`.

```
command: npx
args: ["-y", "@colbymchenry/codegraph", "serve", "--mcp"]
```

⚠ Requires `codegraph index` per-project before first use (see "Setup").

**Alternative** (`npm i -g @colbymchenry/codegraph`): see `templates/mcp-config.json.snippet`.

Switching: edit `.mcp.json` manually (it's not regenerated for non-manifest content).
