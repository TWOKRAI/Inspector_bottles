---
description: Meta-audit of .claude/ — agent/command frontmatter, orphaned slash scripts, MEMORY links, hooks
---

Run an audit of the `.claude/` infrastructure:

```bash
uv run --no-project python scripts/claude_md_audit/claude_md_audit.py
```

What's checked:
- **agents** — frontmatter (`description`) in `.claude/plugins/*/agents/**/*.md`
- **commands** — frontmatter in `.claude/commands/**/*.md`
- **skills** — every `.claude/skills/<name>/` has a `SKILL.md`
- **slash_scripts** — slash commands referencing `uv run --no-project python scripts/x.py` or `bash scripts/x.sh` don't mention non-existent files *(closes the "dangling command" class of bugs)*
- **memory_links** — `[Title](file.md)` in `MEMORY.md` points to an existing file
- **hooks_settings** — hooks in `.claude/settings.json` reference existing scripts

Config: [scripts/claude_md_audit/claude_md_audit.toml](../../scripts/claude_md_audit/claude_md_audit.toml). Details and issue kinds — [README.md](../../scripts/claude_md_audit/README.md).

Useful options:
- `uv run --no-project python scripts/claude_md_audit/claude_md_audit.py --format json` — for CI.
- `uv run --no-project python scripts/claude_md_audit/claude_md_audit.py --no-strict` — a report without failing.
- `uv run --no-project python scripts/claude_md_audit/claude_md_audit.py --claude-dir ../other/.claude` — audit another project.

**When to use:**
- After a seed update/upgrade — check that the migration didn't leave dangling links.
- In CI as a gate before merging into `main`.
- When onboarding a repo — a quick sanity-check of the infrastructure.
- After adding a new agent/command/skill — make sure everything is linked.

**Notes:**
- The frontmatter parser is a simple `key: value`, with no YAML nesting. For complex frontmatter (lists, objects) — only "field present/absent" is tracked.
- `slash_scripts` catches the format `uv run --no-project python scripts/...` / `bash scripts/...` / `uv run scripts/...`. Commands that orchestrate MCP tools or agents are out of scope.

$ARGUMENTS
