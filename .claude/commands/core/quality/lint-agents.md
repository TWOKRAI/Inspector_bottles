---
description: Check agent .md files for consistency (frontmatter, model, tools, cross-ref with CLAUDE.md)
---

# /quality:lint-agents — agent definition linter

Runs `uv run --no-project python scripts/lint_agents.py` against `.claude/plugins/*/agents/`.
Checks the YAML frontmatter, the presence of required fields, model validity,
name-to-filename match, and cross-references from CLAUDE.md.

## When to use it

- After renaming / adding a new agent
- Periodically (once a month or during pre-merge review)
- When updating the model list (Opus/Sonnet/Haiku versions)
- In CI as a gate before merging changes to `.claude/plugins/*/agents/`

## What it checks

1. Frontmatter is present and parses
2. Required keys: `name`, `description`, `model`, `tools`
3. `name` matches the file name
4. `model` is a known Claude ID (claude-opus-4-7, claude-sonnet-5, etc.)
5. `tools` is a non-empty comma-separated list
6. `description` ≤ 500 characters
7. The body has at least one markdown heading
8. Cross-check: role names in CLAUDE.md have corresponding files

## Exit codes

- `0` — everything is green
- `1` — there are ERRORs (CI blocks the merge)
- `2` — only WARNs (review is recommended, but not a blocker)

With the `--strict` flag: warnings also become `exit 1`.

## Running it

```bash
# From the project root:
uv run --no-project python .claude/plugins/core/scripts/lint_agents.py

# Strict mode (warnings fail too):
uv run --no-project python .claude/plugins/core/scripts/lint_agents.py --strict

# A specific path:
uv run --no-project python .claude/plugins/core/scripts/lint_agents.py path/to/agents
```

## Implementation

Pure Python 3.9+, **no external dependencies** (no `pyyaml` — its own
minimal parser for flat key:value). 200 lines, easy to read and
extend. See `scripts/lint_agents.py`.

Alternative (considered in ROADMAP § B.1): `agnix` — a comprehensive
agent-file linter by a third-party author. Decided to write our own minimal one,
because:
- Node-based, adds an extra dependency
- Our use case is narrow (10 files, clear structure)
- Our own = we can add project-specific rules (threshold rules from CLAUDE.md)

If extension is needed in the future (lint complex YAML, multi-line
descriptions, etc.) — we can switch to agnix or add `pyyaml`.
