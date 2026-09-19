# Stack — {{PROJECT_NAME}}

> **★ Per-project customization point ★**
> This is the only file you MUST edit after `claude-kit new`.
> Replace placeholders, delete sections that don't apply, add what's missing.
>
> **This file survives `claude-kit upgrade`** — it is a preserved per-project
> artifact, unlike `settings.json` and the other `modes/*`, which the upgrade
> regenerates from the seed. Your edits here are safe; edits there are not.

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

- **Plans root:** `plans/YYYY-MM-DD_<slug>.md` (single) or `plans/YYYY-MM-DD_<slug>/plan.md` + `phase-N.md` (multi-phase) — see `manager.md` "Plan naming convention"
- **Specs root:** `docs/direction/` (optional — leave empty for small projects)
- **Branch convention:** `<feat|fix|refactor>/<slug>`

## Commit format

- **Validator:** [x] enabled (commit-msg hook installed by `claude-kit new`)
- **Required trailers:** `Why:` always
- **`Layer:` trailer:** [x] **required** — `.claude/commit-layers.txt` ships with the
  `src-package` archetype active (`cli`/`services`/`core`/`utils` + cross-cutting
  `tests`/`docs`/`scripts`/`infra`/`ci`/`build`/`mixed`), deliberately sharing one
  vocabulary with the sentrux rule archetypes.
  - **Switch archetype:** comment the active block out, uncomment `layered` or
    `hexagonal` in the same file.
  - **Turn it off:** comment out **every** non-comment line. An empty (comments-only)
    config makes `Layer:` optional; a **missing** file does the opposite — the
    validator then falls back to its own `DEFAULT_LAYERS` and still requires the
    trailer. Do not delete the file to disable the gate.
- **Tests-discipline gate:** [x] on by default — even with the block below
  absent. Staged code with no staged test and no matching `Tested:` trailer is
  rejected; see `.claude/COMMIT_GUIDE.md` for the `Tested:` grammar it enforces.
  Configured **only** by this fenced `ini` block — the validator reads nothing
  else, so the prose around it can name the keys and their values freely:

```ini
# Tests-discipline commit gate — read by scripts/validate_commit/validate_commit.py.
# Every key is optional; the values below are also what applies with no block at all.
tests_gate = on                      # on | off — off restores the free-form `Tested:` trailer
tests_gate_code = src/**/*.py        # staged paths the gate applies to (comma-separated globs)
tests_gate_exclude = **/template/**  # subtracted from tests_gate_code before the gate fires

# Pre-report gate — read by hooks/subagent-stop-gate.sh (SubagentStop).
pre_report_gate = {{PRE_REPORT_GATE}}          # on | off — off allows without running anything
pre_report_gate_tests = tests                  # space-separated test paths passed to pre_report_gate.py --tests
pre_report_gate_base =                         # merge-base ref for the gate's diff scope; empty = @{upstream} → origin/HEAD → main → master
report_status = on                             # on | off — off skips the STATUS: line check entirely; independent of pre_report_gate

# Subagent context budget — read by hooks/agent-context-ceiling.sh (PreToolUse).
agent_context_budget = 100000                  # soft: start + N -> checkpoint (finish or hand off), repeated every +50000; off = none
agent_context_hard_budget = off                # hard: start + N -> deny all but commit / handoff / report; off (default) = never deny

# Document size budget — read by scripts/lint_doc_size.py and hooks/doc-size-guard.sh.
doc_size = on                                   # on | off — off disables every finding
doc_size_warn_kb = 32                           # a whole markdown FILE over this many KB is flagged
doc_section_warn_kb = 8                         # a single heading-delimited SECTION over this many KB is flagged
doc_size_exempt = CHANGELOG.md, **/_archive/**, **/fixtures/**, **/node_modules/**  # comma-separated globs, REPLACES the default list when set

# Executor brief lint - read by dev/hooks/lint-brief.sh (PreToolUse on Agent).
brief_lint = on                                 # on | off — off allows every writer spawn without checking the brief
brief_max_files = 6                             # FILES block's numbered/bulleted entry count above this is denied
brief_lint_roles = developer, teamlead, tester, junior, debugger  # subagent_type values the lint applies to; others pass silently

# Web search routing - read by hooks/web-search-routing.sh (PreToolUse on WebSearch|WebFetch).
web_search = auto                               # auto | delegate | allow — auto allows only sonnet/opus/haiku main sessions
web_search_deny_agents = cto                    # comma-separated subagent_type values denied even in auto (top-tier roles)
```

  - **Several globs per key** — comma-separated on one line, e.g.
    `tests_gate_code = src/**/*.py, lib/**/*.py`.
  - **`tests_gate_exclude`** is for paths that are not application code —
    bundled templates, prompt/doc files under `template/`.
  - **Disable:** edit the block itself (`tests_gate = off`). The same words in
    a sentence are documentation, not a switch; an unrecognised value leaves
    the gate ON, so a typo can never disable it silently.
  - **`pre_report_gate`** runs `pre_report_gate.py` (exec-bit, contract-lite,
    lint, tests fail-fast checks) in a gated-role subagent's own worktree
    right before it reports done, and blocks (reason ≤ 10 lines, capped at 2
    blocks per agent) when red. Turn it **on** to enforce it project-wide;
    `pre_report_gate_tests` picks which test paths the gate's own test check
    runs (narrow it, e.g. `tests/unit`, once the suite is slow — the gate
    allows 240 s); `pre_report_gate_base` pins the ref the gate diffs against (leave
    empty for auto-detection).
  - **`agent_context_budget` / `agent_context_hard_budget`** count from the
    subagent's own start (its first turn: system prompt, CLAUDE.md, skills), so
    the startup cost never eats the budget; the hard level is off unless set.
    To change the budget of one running agent, write
    `.claude/logs/agents/<agent_id>.budget` (e.g. `soft=250000 hard=off`) —
    it applies from that agent's next tool call and is gitignored.

## Language policy

> This file is not auto-loaded. The reply language reaches the model only through the native
> `language` key in `.claude/settings.json` (set by `init`/`new`; to change it, edit
> `.claude/plugins/core/settings.partial.json` and run `plugin sync`) — keep the first line below
> in step with it.

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
  - `claude-kit new` auto-deploys `.sentrux/rules.toml` from the `src-package`
    archetype with your package name already substituted — green from day one
    (`max_cycles` + `no_god_files` active), no manual edit. The `[[boundaries]]`
    block ships COMMENTED with the package pre-filled: uncomment it once your layer
    folders (`src/<pkg>/core` …) exist — an active boundary that matches nothing
    passes silently, so don't enable it early. To switch to `layered` / `hexagonal`,
    copy that archetype over it (see `.claude/plugins/mcp-sentrux/README.md` →
    its starter rule archetypes section), replace `your_package`, AND uncomment its
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
> Detailed ADRs live in `docs/claude/DECISIONS/` or `<module>/DECISIONS.md`.
