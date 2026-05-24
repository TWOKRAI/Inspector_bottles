# Stack — {{PROJECT_NAME}}

> **★ Per-project customization point ★**
> This is the only file you MUST edit after `claude-kit new`.
> Replace placeholders, delete sections that don't apply, add what's missing.

## Project

- **Name:** {{PROJECT_NAME}}
- **Purpose:** {{DESCRIPTION}}
- **Package:** `{{PACKAGE}}` (imported as `import {{PACKAGE}}`)

## Toolchain (defaults from seed — adjust if needed)

- **Language:** Python 3.11+
- **Package manager:** **`uv`** (Astral). Never `pip install` directly.
- **Test:** `uv run pytest -q`
- **Lint:** `uv run ruff check .`
- **Format:** `uv run ruff format .`
- **Type check:** `uv run pyright`
- **Smoke-test (developer):** `uv run python -m compileall -q src && uv run pytest -q`
- **Run CLI:** `uv run python -m {{PACKAGE}}` _(adjust if entrypoint differs)_
- **Add dep:** `uv add <pkg>` (runtime) / `uv add --group dev <pkg>` (dev)

## Stages (optional — delete if no staged delivery)

> Document phased dependency growth so each stage stays minimal and reviewable.
> Rule: don't pull stage-N dependencies before starting stage-N.
> Example pattern:
>
> - Stage 0: `python-dotenv`, `pytest`, `ruff`
> - Stage 1: `+ <deps for stage 1>`
> - Stage 2: `+ <deps for stage 2>`

## LLM runtime (optional — delete if no LLM)

- **Primary:** _(e.g., LM Studio + MLX, `LLM_BASE_URL=http://localhost:1234/v1`)_
- **Fallback:** _(e.g., Ollama, `LLM_BASE_URL=http://localhost:11434/v1`)_
- Single client (`openai` SDK), switched via `.env` (`LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`).

## Layout (src-layout)

```
src/{{PACKAGE}}/   — main package (imported as `{{PACKAGE}}`)
tests/             — pytest
data/              — runtime data, caches, DBs (gitignored)
scripts/           — one-off utilities
docs/              — human + agent-facing documentation
plans/             — Task-based plans (see plans/README.md)
```

## Plans & Specs

- **Plans root:** `plans/<slug>.md` (kebab-case, no dates)
- **Specs root:** `docs/direction/` (optional — leave empty for small projects)
- **Branch convention:** `<feat|fix|refactor>/<slug>`

## Commit format

- **Validator:** [x] enabled (commit-msg hook installed by `claude-kit new`)
- **Required trailers:** `Why:` always
- **`Layer:` trailer:** [ ] disabled by default
  - **Enable when:** project grows clear architectural layers worth gating.
  - **How:** populate `.claude/commit-layers.txt` with one layer per line.

## Language policy

- **User-facing output:** _(English / Russian / other — choose one)_
- **Code comments / docstrings:** _(English / Russian)_
- **System files (.claude/, settings.json, Makefile):** English (working interfaces)
- **Identifiers (function/variable names):** English (always)

## MCP — core (documented in `.claude/mcp/`)

- [x] **qex** — semantic code search (Ollama + BM25). Always-on в этом проекте.
- [x] **sentrux** — architectural DSM / metrics. Always-on (20+ модулей фреймворка).
- [x] **context7** — library docs (user-level, usually enabled globally).

## MCP — optional (activate per project via `.claude/mcp/<name>/SETUP_GUIDE.md`)

- [x] **qt-mcp** — runtime inspection for PyQt5/PySide6 GUI apps. Активен (проект — PySide6).
- [x] **graphify** — knowledge graph of the codebase (HTML + JSON + report).
- [x] **serena** — LSP-backed symbol-level retrieval (experimental — см. known issues).
- [x] **ast-grep** — structural AST search + rewrite (codemods на 20+ языках).
- [ ] **codegraph** — function-level call graph (callers/callees/impact). Conditional guard в агентах сохранён на случай активации.
- [ ] **playwright** — browser automation (web-only, проект не веб).
- [ ] **sequential-thinking** — externalized chain-of-thought scratchpad (для investigator/teamlead на 3-й гипотезе).
- [ ] **github** — GitHub MCP (Issues/PR/Actions). Локально используется `gh` CLI.

## Architecture notes

> Capture project-specific architectural invariants here. Examples:
>
> - **R1**: producer-consumer through `<queue>` — UI never blocks on background work.
> - **R2**: dict at process boundary; Pydantic only inside a process.
> - **N1**: external API client must respect rate limits (no "bypass" workarounds).
>
> Numbering: R# = rules, N# = constraints, D# = decisions.
> Detailed ADRs live in `docs/claude/DECISIONS/` or `<module>/DECISIONS.md`.
