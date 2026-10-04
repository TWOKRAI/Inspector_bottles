---
name: feedback-protect-branch-blocks-worktree-subagents
description: protect-branch hook denies git commit for subagents working in sibling worktrees — brief them to stage + write the message file; the lead commits and checks ruff
metadata:
  type: feedback
---

Правило перенесено в `.claude/skills/project-rules/SKILL.md` §5 и `.claude/plugins/dev/templates/team-brief.md` (2026-10-04).

**Why:** the agent then stops "DONE, not committed"; without a plan for it the lead discovers it per agent, and pre-commit
(ruff E501, format) runs only at the lead's commit — tester 2.2's file failed ruff and only the lead saw it.
