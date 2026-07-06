# Serena — LSP-backed symbol-level code retrieval

Optional MCP module. Adds IDE-like code intelligence to the agent: precise references, cross-file renames, symbol moves — backed by language servers, not by embeddings.

> Upstream: <https://github.com/oraios/serena>
> **Status:** Experimental in this seed (see Known Issues below).

## When to enable

✅ **Enable when:**
- Codebase ≥ 10k LOC with many cross-file references
- Frequent refactoring: renames, moves, "find all callers"
- A Language Server exists and is stable for your language (Python via Pyright, TS/JS, Rust via rust-analyzer, Go via gopls)
- You're frustrated with qex returning "similar but not exact" results when you want exact symbol references

❌ **Skip when:**
- Project is < 5k LOC — overkill
- Your language has weak LSP support (some Lua / DSL / niche stack)
- You're already happy with qex semantic search + Grep for symbols
- Project has no `pyproject.toml` / `tsconfig.json` / `Cargo.toml` — LSP can't resolve imports correctly

## How it differs from qex

| Question | Pick |
|----------|------|
| "Where is `validate_user` **defined**?" | **Serena** (LSP definition) |
| "All callers of `HttpClient.fetch`" | **Serena** (LSP references — 100% accurate) |
| "Rename `_normalize_id` → `normalize_user_id` everywhere" | **Serena** (atomic cross-file rename) |
| "Find code that **does something like** error retry with backoff" | **qex** (semantic, fuzzy) |
| "Where do we **handle** auth failures?" (no exact symbol in mind) | **qex** |
| Architectural "what's connected to what" overview | **graphify** |

**Bottom line:** Serena and qex answer **different** questions. Either keep both (different commands), or A/B-test on your codebase and pick the primary.

## Known Issues (Status: experimental)

As of this seed version:

- **First-time LSP startup can take 30–60 seconds** (Pyright warming up). Subsequent queries are fast.
- **Per-language LSP must be installed** — not bundled. Pyright is auto-fetched by uv tool; rust-analyzer / gopls need separate install.
- **Reports from this team's pilot:** Serena sometimes fails to start on Windows when the project venv path contains spaces or Cyrillic characters. Workaround: place project at an ASCII-only path.
- **No fallback** if LSP crashes — Claude won't silently degrade to qex. Be explicit in prompts which tool you want.

The MCP module is included so a project can opt in and try it. **Run [SETUP_GUIDE.md](SETUP_GUIDE.md) end-to-end before relying on Serena for production refactoring** — verify the smoke test passes for your specific stack.

## Supported languages

30+ via LSP. Best-tested: Python (Pyright), TypeScript / JavaScript, Rust (rust-analyzer), Go (gopls), Java (jdtls), C++ (clangd). Less mature: Kotlin, Scala, Ruby.

## Setup

See [SETUP_GUIDE.md](SETUP_GUIDE.md) for install + per-language LSP setup + smoke test.

## Tool routing (when Serena works on your project)

Add this to your project's `CLAUDE.md` if Serena passes the smoke test:

> - Запросы по точному символу (refs / definition / rename / move) → **Serena**
> - Семантические запросы по описанию поведения → **qex**
> - Архитектурный обзор → **graphify**
> - При падении Serena (язык без LSP, проект без manifest) → fallback к qex + Grep
## Launcher options

**Default** (used automatically by `claude-kit-claude plugin enable mcp-serena`): see `.claude-plugin/plugin.json` → `mcpServers.serena`. Launches through `uvx`, so no separately-installed `serena` binary needs to be on PATH.

```
command: uvx
args: ["--from", "serena-agent", "serena", "start-mcp-server", "--context", "claude-code", "--project", "."]
```

**Alternative** (only if you've run `uv tool install serena-agent` and prefer the bare binary): `command: serena`, `args: ["start-mcp-server", "--context", "claude-code", "--project", "."]`. The copy-paste `.mcp.json` block is in `templates/mcp-config.json.snippet`.

Switching: edit `.mcp.json` manually (it's not regenerated for non-manifest content).
