---
description: Show the current development team — agents, models, roles
---

Show the project's current agent roster (auto-discovery).

## Steps

1. Read the contents of `.claude/plugins/*/agents/` (agents are spread across plugins: `core`, `dev`, `knowledge`).
2. For each `*.md` file extract the frontmatter: `name`, `model`, `description`.
3. Group by subfolder (or by a flag field in the frontmatter, if present).
4. Print a table:

```
## Agents

| Category  | Agent | Model  | When to call (description)   |
|-----------|-------|--------|------------------------------|
| dev       | manager     | sonnet | Task decomposition, writing the spec |
| dev       | developer   | sonnet | Implementation per spec |
| dev       | reviewer    | opus   | PR code review |
| dev       | tester      | sonnet | Tests from acceptance criteria |
| ...       | ...         | ...    | ... |
```

5. At the end — an overall summary:
   ```
   Total: N agents (by category: dev=K, knowledge=M, ...)
   ```

## Output rules

- If the frontmatter is broken — mark the agent `[malformed]` and continue.
- If a subfolder contains only `_WORKTREE_PATTERN.md` or `README.md` — skip it, don't count it as an agent.
- Don't make up agents that aren't on disk.

## Workflow hints

If the standard `manager`, `developer`, `tester`, `reviewer` exist — suggest the standard pipeline:
```
/dev:plan → /dev:implement → /dev:test → [FAIL → /dev:debug] → /dev:review → /core:team:docs → /dev:ship
```

Hire a new agent: `/core:team:hire <role>` (creates it from the template `.claude/plugins/core/templates/agent.template.md`).
