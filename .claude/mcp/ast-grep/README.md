# ast-grep — structural search and **rewrite** across 20+ languages

Optional MCP module. Where codegraph reads a call graph and qex does fuzzy semantic search, ast-grep does **safe structural patterns** — find and **rewrite** AST nodes by pattern across the codebase, polyglot.

> Upstream CLI: <https://github.com/ast-grep/ast-grep>
> MCP wrapper: <https://github.com/ast-grep/ast-grep-mcp>
> **License:** MIT · **Status as of 2026-05:** stable, 8k+★ for the CLI, MCP wrapper is active

## When to enable

✅ **Enable when:**
- You need **codemod-style refactoring** that Grep can't express (matching AST, not text)
- Polyglot codebase — same pattern in Python + TypeScript + Go + Rust + ...
- You want to enforce a code rule: "no bare `except:`", "every `useState` needs a type arg", etc.
- Migrating from one API to another across many files

❌ **Skip when:**
- Project is single-file scripts
- Plain Grep + sed covers your needs
- You don't do refactoring this month

## How it differs from the rest of the seed

| Task | Best tool | Why |
|------|-----------|-----|
| "Find places that call `foo()`" | **codegraph** or **Grep** | Call graph is faster than AST scan |
| "Find code that does fuzzy thing X" | **qex** | Semantic, not structural |
| "Replace `requests.get(url)` with `httpx.get(url)` across 200 files" | **ast-grep** | AST-aware codemod, won't touch strings/comments |
| "Find every Python `try:` block with bare `except:` and add a type" | **ast-grep** | Pattern with placeholder + structural replace |
| "Check the architecture is healthy" | **sentrux** | Metrics, not patterns |
| "Rename `Manifest.load` everywhere" | **serena** (LSP rename) | LSP knows scope; ast-grep treats strings as text |

**Bottom line:** ast-grep is for **structural codemods** — find AND rewrite — across many languages. It doesn't replace LSP rename (serena) for scope-aware renames, but it does what no other tool here does: pattern-based bulk transformation with AST safety.

## Supported languages

Tree-sitter-based: Python, TypeScript, JavaScript, Go, Rust, Java, C, C++, C#, Kotlin, Swift, Ruby, PHP, Bash, HTML, CSS, YAML, JSON, Lua, Scala, and more.

## Killer feature: rules file

`sgconfig.yml` + `rules/` lets you encode project-specific lints as ast-grep patterns. Run as a hook or CI step:

```yaml
# rules/no-print-in-prod.yml
id: no-print-in-prod
language: python
rule:
  pattern: print($$$ARGS)
  inside:
    kind: function_definition
    not:
      pattern: if __name__ == "__main__"
severity: warning
message: "Use logging, not print() outside __main__"
```

Then `ast-grep scan` runs all rules over the codebase. The MCP server exposes this same scan as a tool the agent can call.

## Tool routing snippet (paste into project `CLAUDE.md`)

> When ast-grep is enabled in this project:
> - **Pattern-based search + rewrite** across files → **ast-grep**
> - **Scope-aware rename** of one symbol → **serena** (LSP)
> - **Exact substring** → **Grep**
> - **Semantic intent** ("code that handles retry") → **qex**
> - **Call graph** ("who calls X") → **codegraph**

## Conflicts / overlap

- **Partial overlap with codegraph**: codegraph reads patterns, ast-grep rewrites them. Complementary, not duplicate.
- **Partial overlap with serena**: serena renames within scope (LSP-aware); ast-grep does pattern-replace (text-aware). Use serena for single-symbol refactors, ast-grep for bulk patterns.
- **No overlap with qex / sentrux / graphify**.

## Setup

See [SETUP_GUIDE.md](SETUP_GUIDE.md) — installs the CLI (`brew` / `cargo` / `winget`), wires the MCP server, includes a smoke test (find + dry-run rewrite).
