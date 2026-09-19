# {{PROJECT_NAME}}

## Goal

{{DESCRIPTION}}

## Architecture

> Replace with the real layers/modules. If this is a simple script, you can delete this section.

- **Layer 1:** what it does
- **Layer 2:** what it does

## Key paths

| What | Path | Who reads / writes |
|-----|------|-----|
| Main package | `src/{{PACKAGE}}/` | project code |
| Tests | `tests/` | pytest, tester agent |
| Scripts | `scripts/` | makefile, dev commands |
| Commit validator | `scripts/validate_commit/` | `commit-msg` hook |
| Documentation | `docs/` | people + agents |
| Project map | `docs/PROJECT_CONTEXT.md` + `src/{{PACKAGE}}/CONTEXT.md` | agents (orient first); rebuild via `/core:quality:sync-context` |
| Commit guide | `.claude/COMMIT_GUIDE.md` | agents when committing |
| Session logs | `docs/sessions/YYYY-MM-DD.md` | `/core:team:wrap-up`, `/core:memory:search` |
| Task plans (Plan-Driven Dev) | `plans/YYYY-MM-DD_<slug>.md` (single) or `plans/YYYY-MM-DD_<slug>/plan.md`+`phase-N.md` (multi-phase) | `/dev:plan`, `/dev:implement`, `/dev:ship` |
| Long-term memory | `.claude/memory/MEMORY.md` + `*.md` | agent (auto-memory rules) |
| Layer-enum config | `.claude/commit-layers.txt` | validate_commit.py |
| Data (gitignored) | `data/` | runtime |

**Principle:** one folder — one responsibility. The plan-driven workflow links them via the `Refs: plans/<slug>.md` trailer in every task commit. See [`.claude/COMMIT_GUIDE.md`](.claude/COMMIT_GUIDE.md), [`plans/README.md`](plans/README.md), [`.claude/CLAUDE.md`](.claude/CLAUDE.md) → "Memory (OVERRIDE)".

## `.claude/` lifecycle — `claude-kit-project` / `claude-kit-claude`

> `.claude/` (agents, commands, hooks, MCP, skills, templates) is generated
> and updated **only** via `claude-kit-project`/`claude-kit-claude`
> (`console_scripts` of the `claude-kit` package), never by hand-editing
> files. Commands not found → `uv run --no-project python <seed-clone>/scripts/install-global.py`.
> Full guide (install, MCP, VS Code, sanity checks, troubleshooting) — `.claude/BOOTSTRAP.md`.
> Legacy `claude-kit` 0.x (schema=1, before 0.7.0) on PATH — `plugin doctor` will warn
> in the "Legacy CLI" section; remove it with the manager you installed it with (`pipx`/`pip
> uninstall claude-kit`), not `uv tool uninstall` (that would remove the current tooling).

### Commands (for the agent)

| Task | Command |
|--------|---------|
| Bootstrap a new project | `claude-kit-project new <target>` |
| Add/update `.claude/` in a project | `claude-kit-project init <target> --apply` |
| Diagnose environment/plugins/`.claude/` | `claude-kit-claude plugin doctor <target>` (+`--verbose`, `--fix`) |
| Preview / apply a seed update | `claude-kit-claude plugin upgrade <target> --dry-run` / `--apply` |
| List plugins | `claude-kit-claude plugin list <target>` |
| Enable / disable a plugin + recompose | `claude-kit-claude plugin enable <id> <target>` / `claude-kit-claude plugin disable <id> <target>` |
| Recompose `.mcp.json`/`settings.json` | `claude-kit-claude plugin sync <target>` |
| Migrate schema=1 → schema=2 | `claude-kit-claude plugin migrate <target> --apply` (default — dry-run) |
| Package version | `claude-kit-claude --version` |

**Legacy layout** (`manifest.yaml` schema=1, or fully flat with no `enabled.yaml`) →
`plugin migrate --apply` (automatic, tar.gz backup + rollback), or, for a fully flat one,
`claude-kit-project init --apply --force` on top + your own agents/commands — as a third-party
plugin (`<seed-clone>/docs/PLUGIN_GUIDE.md` → the third-party plugin section, β-path vs vendoring), don't mix it with the managed tree.

**Do not hand-edit** (overwritten on `upgrade`): `.claude/plugins/<id>/**`,
`.claude/{COMMIT_GUIDE,BOOTSTRAP,STACK,CLAUDE}.md`, `.claude/docs/`. Edit seed content —
in the canonical seed (`plugins/<id>/`), then `plugin upgrade . --apply` in the project.

**Preserved on `upgrade`** (your files): `.claude/memory/`, `.claude/modes/_stack.md`,
`.claude/commit-layers.txt`, `.claude/settings.local.json`, `.claude/readonly-paths`,
`.claude/protected-branches`, `.claude/security-patterns.json`, the root `CLAUDE.md`.

**Something broke:** `plugin doctor . --verbose` → `--fix` → `plugin upgrade . --dry-run`
if it diverges from the seed → check `claude-kit-claude --version`.

## Stack

Toolchain, versions, commands — `.claude/modes/_stack.md` (READ FIRST, customized per project).

## Project rules

1. **Style:** ruff format + check automatically in pre-commit
2. **Types:** type hints required for public functions, pyright `standard` mode
3. **Tests:** required when logic changes
4. **Secrets:** only in `.env` (gitignored)
5. **Commit messages:** Conventional Commits, `Why:` trailer always
6. **Escalation:** one level up, never sideways and never a guess — ladder and format in `project-rules` §7

## Commands

### Makefile

| Command | What it does |
|---------|-----------|
| `make install` | Install deps + pre-commit hooks |
| `make check` | Lint (ruff) + typecheck (pyright) |
| `make test` | pytest with coverage |
| `make gate` | Full gate (check + test) before push |
| `make format` | Auto-fix via ruff |

### Slash commands (via Claude Code)

Commands live in `.claude/commands/<namespace>/<name>.md`. Full list by
namespace — `/help` in Claude Code, `ls .claude/commands/`, or
[`.claude/CLAUDE.md`](.claude/CLAUDE.md) → "Commands — quick reference".
Subagents (developer, reviewer, manager, teamlead, debugger, tester,
docs-writer, tech-writer, …) — `/core:team:team`.

## Tool routing (MCP)

Enable only what the project actually needs — `.claude/modes/_stack.md` → "MCP".
Heuristic: "find / what it does" → **qex** (codebase ≥ 5k LOC); symbol name + refs/rename → **serena**;
"what relates to what" → **graphify**; metrics/DSM/cycles → **sentrux**; exact string/regex → **Grep**
(cheapest of all). Project servers and fallback — [`.claude/CLAUDE.md`](.claude/CLAUDE.md) → "MCP routing".

## Agent memory (override)

Paths (`.claude/memory/`, role-scoped `.claude/agent-memory/<name>/`), write rules
and commands — [`.claude/CLAUDE.md`](.claude/CLAUDE.md) → "Memory (OVERRIDE)".

## `.claude/`

- [`.claude/BOOTSTRAP.md`](.claude/BOOTSTRAP.md) — install from scratch
- [`.claude/STACK.md`](.claude/STACK.md) — all tools
- [`.claude/modes/_stack.md`](.claude/modes/_stack.md) — project-specific customization
