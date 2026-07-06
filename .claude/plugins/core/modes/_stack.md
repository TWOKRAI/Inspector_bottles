# Stack — {{PROJECT_NAME}}

> **★ Per-project customization point ★**
> This is the only file you MUST edit after `claude-kit-project new`.
> Replace placeholders, delete sections that don't apply, add what's missing.

## Project

- **Name:** {{PROJECT_NAME}}
- **Purpose:** {{DESCRIPTION}}
- **Package:** `{{PACKAGE}}` (imported as `import {{PACKAGE}}`)

{{TOOLCHAIN_BLOCK}}

{{STAGES_BLOCK}}

## LLM runtime (optional — delete if no LLM)

- **Primary:** _(e.g., LM Studio + MLX, `LLM_BASE_URL=http://localhost:1234/v1`)_
- **Fallback:** _(e.g., Ollama, `LLM_BASE_URL=http://localhost:11434/v1`)_
- Single client (`openai` SDK), switched via `.env` (`LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`).

{{LAYOUT_BLOCK}}

## Plans & Specs

- **Plans root:** `plans/<slug>.md` (kebab-case, no dates)
- **Specs root:** `docs/direction/` (optional — leave empty for small projects)
- **Branch convention:** `<feat|fix|refactor>/<slug>`

## Commit format

- **Validator:** [x] enabled (commit-msg hook installed by `claude-kit-project new`)
- **Required trailers:** `Why:` always
- **`Layer:` trailer:** [ ] disabled by default
  - **Enable when:** project grows clear architectural layers worth gating.
  - **How:** populate `.claude/commit-layers.txt` with one layer per line.

## Language policy

> Set the language ONCE here; agents read this file every session. The choice below is
> the single source of truth for the language the assistant uses with you.

- **User-facing output (assistant replies in chat):** _(English / Russian / other — choose one)_.
  Applies to ALL user-facing prose — answers, status updates, questions, summaries — on
  EVERY reply, starting with the first reply of the session, **even when the working
  context (plans, code, sub-agent reports) is in another language**. Do not drift to the
  context language.
- **Code comments / docstrings:** _(English / Russian — choose one; English matches most codebases)_
- **System files (.claude/, settings.json, Makefile):** English (working interfaces)
- **Identifiers (function/variable names):** English (always)
- **Internal reasoning / thinking:** any language (English is usually best for quality) —
  this setting governs OUTPUT, not thinking. Identifiers, paths, flags, commands and
  commit messages stay as-is regardless.

## MCP — core (documented in `.claude/plugins/core/mcp/`)

- [ ] **qex** — semantic code search (Ollama + usearch HNSW, no Docker/Qdrant since 0.0.2). Enable for codebases ≥ 5k LOC.
- [ ] **sentrux** — architectural DSM / metrics. Enable when ≥ 10 modules.
  - `claude-kit-project new` auto-deploys `.sentrux/rules.toml` from the `src-package`
    archetype with your package name already substituted — green from day one
    (`max_cycles` + `no_god_files` active), no manual edit. The `[[boundaries]]`
    block ships COMMENTED with the package pre-filled: uncomment it once your layer
    folders (`src/<pkg>/core` …) exist — an active boundary that matches nothing
    passes silently, so don't enable it early. To switch to `layered` / `hexagonal`,
    copy that archetype over it (see `.claude/plugins/mcp-sentrux/README.md` →
    "Стартовые архетипы правил"), replace `your_package`, AND uncomment its
    `[[boundaries]]` block once the folders exist (it ships commented too, same as
    the default). Note: sentrux 0.5.7 resolves only ABSOLUTE imports — relative
    imports (`from ..core import …`) silently bypass boundaries.
- [x] **context7** — library docs (user-level, usually enabled globally).

## MCP — optional (activate per project via `.claude/plugins/mcp-<name>/SETUP_GUIDE.md`)

- [ ] **qt-mcp** — runtime inspection for PyQt5/PySide6 GUI apps. Enable for PySide/PyQt projects.
- [ ] **graphify** — knowledge graph of the codebase (HTML + JSON + report).
- [ ] **serena** — LSP-backed symbol-level retrieval (experimental — see SETUP_GUIDE caveats).
- [ ] **ast-grep** — structural AST search + rewrite (codemods across 20+ languages).
- [ ] **codegraph** — function-level call graph (callers/callees/impact). Conditional guards in agents work without it too.
- [ ] **playwright** — browser automation (web-only). For web projects: verify-done golden-path in the browser.
- [ ] **sequential-thinking** — externalized chain-of-thought scratchpad (investigator/teamlead on the 3rd hypothesis).
- [ ] **github** — GitHub MCP (Issues/PR/Actions). Alternative: `gh` CLI.

## Architecture notes

> Capture project-specific architectural invariants here. Examples:
>
> - **R1**: producer-consumer through `<queue>` — UI never blocks on background work.
> - **R2**: dict at process boundary; Pydantic only inside a process.
> - **N1**: external API client must respect rate limits (no "bypass" workarounds).
>
> Numbering: R# = rules, N# = constraints, D# = decisions.
> Detailed ADRs live in `docs/decisions/` or `<module>/DECISIONS.md`.
