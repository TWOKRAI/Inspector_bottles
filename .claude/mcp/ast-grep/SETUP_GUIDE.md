# ast-grep — Setup Guide

CLI + MCP wrapper. ~5 minutes.

> CLI: <https://github.com/ast-grep/ast-grep>. MCP: <https://github.com/ast-grep/ast-grep-mcp>.

---

## 1. Install the CLI

### macOS

```bash
brew install ast-grep
```

### Linux

```bash
# via cargo (if you have Rust)
cargo install ast-grep --locked

# or via npm
npm install -g @ast-grep/cli

# or download a release binary
# https://github.com/ast-grep/ast-grep/releases
```

### Windows

```powershell
winget install ast-grep.ast-grep
# or
scoop install main/ast-grep
# or via npm:
npm install -g @ast-grep/cli
```

### Verify

```bash
ast-grep --version    # or `sg --version`
```

---

## 2. Smoke-test the CLI (no MCP yet)

From a project root:

```bash
# Find all Python print() calls outside __main__
ast-grep --pattern 'print($$$)' --lang python

# Dry-run a rewrite (preview only)
ast-grep --pattern 'requests.get($URL)' --rewrite 'httpx.get($URL)' --lang python --dry-run

# Apply for real (only after dry-run looks correct)
ast-grep --pattern 'requests.get($URL)' --rewrite 'httpx.get($URL)' --lang python --interactive
```

`--interactive` prompts on each match — safer than blind rewrite. Use this until you fully trust the pattern.

---

## 3. Optional: project rules file

If you want repeatable lints, create `sgconfig.yml` at repo root:

```yaml
ruleDirs:
  - ./.ast-grep/rules
```

And `.ast-grep/rules/no-print.yml`:

```yaml
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

Then:

```bash
ast-grep scan       # runs all rules
```

This is also what the MCP exposes to the agent.

---

## 4. Wire the MCP server

### Variant A: via npx (zero install, slower first run)

Append to project `.mcp.json`:

```json
{
  "ast-grep": {
    "command": "npx",
    "args": ["-y", "@ast-grep/mcp", "--root", "."]
  }
}
```

### Variant B: global install

```bash
npm install -g @ast-grep/mcp
```

```json
{
  "ast-grep": {
    "command": "ast-grep-mcp",
    "args": ["--root", "."]
  }
}
```

The snippet is in `templates/mcp-config.json.snippet`.

---

## 5. Restart Claude Code and test

`/mcp` → `ast-grep` should be connected. Ask the agent:

```
Use ast-grep to find all bare `except:` blocks in this Python codebase
and propose adding `except Exception:` where appropriate. Dry-run only.
```

If the agent returns AST-matched locations (file + line + AST kind) — wired up.

---

## 6. Recommended workflow with the agent

The seed's principle "destructive ops require confirmation" applies double here. The default pattern:

1. Agent **searches** with ast-grep (read-only) — finds candidates
2. Agent shows you the diff `--dry-run` would produce
3. You approve (or narrow the pattern)
4. Agent applies with `--interactive` (or just runs it, if you've confirmed)
5. Run tests / type-check / `/verify-done` skill

Never let the agent run a non-`--dry-run` ast-grep rewrite without you having seen the dry-run output first.

---

## Troubleshooting

### "command not found: ast-grep"

PATH issue. `npm i -g @ast-grep/cli` puts the binary in `npm config get prefix`/bin. Add that to PATH.

### Pattern matches too much

ast-grep patterns use `$VAR` for single-capture and `$$$VAR` for multi-capture. Wrong sigil = too-greedy match. Re-read the [pattern docs](https://ast-grep.github.io/guide/pattern-syntax.html).

### Pattern matches nothing but should

- Wrong `--lang`? File extension isn't auto-detected if odd
- Tree-sitter grammar mismatch — try the [playground](https://ast-grep.github.io/playground.html) with your pattern and snippet first

### Rewrite produced something weird

Always `--dry-run` first. If the dry-run already looks weird — the pattern is wrong, not the tool. Refine in the playground.

### Agent ignores ast-grep and just uses Grep

Tool routing isn't pinned. Add the snippet from [README.md § Tool routing](README.md) to project `CLAUDE.md`.

---

## Uninstall

```bash
# CLI
brew uninstall ast-grep    # or `cargo uninstall ast-grep` / `npm uninstall -g @ast-grep/cli`

# MCP wrapper (if installed globally)
npm uninstall -g @ast-grep/mcp
```

Remove the `ast-grep` block from `.mcp.json`. Remove `sgconfig.yml` and `.ast-grep/` if you set up project rules.

---

## Security notes

- Read-only mode (search, scan) is safe.
- **Rewrites modify files** — always `--dry-run` first when you don't trust the pattern.
- No network calls; everything is local.
- Rules can include shell-style placeholders but ast-grep does **not** execute code in patterns.
