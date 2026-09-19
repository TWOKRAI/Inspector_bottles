---
description: Project long-term memory status — what's in .claude/memory/
---

Show the current state of project memory.

## Steps

1. Check that `.claude/memory/` exists. If not — suggest `/core:memory:init`, stop.
2. Read `.claude/memory/MEMORY.md` (if present). Index line format:
   `- [Title](file.md) — hook`.
3. `ls .claude/memory/*.md` — collect the list of memory files other than `MEMORY.md`.
4. For each file extract the frontmatter (`name`, `description`,
   `metadata.type`, optionally `metadata.last-verified`).
5. Group by type: `user`, `feedback`, `project`, `reference`, `other` (if type isn't specified).
6. Run the mechanical lint:
   ```bash
   uv run --no-project python .claude/plugins/core/scripts/memory_lint.py .claude/memory --repo-root .
   ```
   Show each WARN (`dead-link` / `orphan` / `oversized` / `broken-body-ref`
   / `stale`) on its own line — this is exactly the "out of sync" case below that
   used to be checked by hand.
7. If `.claude/agent-memory/` exists — run the same lint with `--roles` (without
   the flag, the CLI silently finds 0 warnings on this tree — there's no
   `MEMORY.md` index of the form the default mode checks):
   ```bash
   uv run --no-project python .claude/plugins/core/scripts/memory_lint.py .claude/agent-memory --roles
   ```
   Show each WARN (`role-oversized` / `possible-duplicate`) on its own line.

## Output

```
Memory: .claude/memory/
Index:  MEMORY.md (N lines)
Files:  M entries

User:        <count>
Feedback:    <count>
Project:     <count>
Reference:   <count>

Last 3 modified:
- <file> (type) — description
- ...
```

A WARN from `memory_lint.py` in step 6 (`dead-link` / `orphan`) is exactly this out-of-sync case — warn and suggest a sync.
