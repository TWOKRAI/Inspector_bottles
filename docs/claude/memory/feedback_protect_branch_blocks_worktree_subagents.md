---
name: feedback-protect-branch-blocks-worktree-subagents
description: "protect-branch hook denies git commit for subagents working in sibling worktrees — brief them to stage + write the message file; the lead commits and checks ruff (хук / hook, субагенты, коммит)"
mechanism: [hooks, agents]
metadata:
  type: feedback
---

Правило перенесено в `.claude/skills/project-rules/SKILL.md` §5 и `.claude/plugins/dev/templates/team-brief.md` (2026-10-04). Ниже — доказательная база урока.

Subagents (tester, developer) working in `../Inspector_bottles--<task>` worktrees cannot `git commit`: the protect-branch hook
reads the branch from the main tree's cwd (`main`), not from the worktree. Measured 2026-10-02, layer-render wave 3: 5 of 5
writers blocked. The lead's own `cd <worktree> && git commit` passes.

**Why:** the agent then stops "DONE, not committed"; without a plan for it the lead discovers it per agent, and pre-commit
(ruff E501, format) runs only at the lead's commit — tester 2.2's file failed ruff and only the lead saw it.

**How to apply:** in every writer brief say: stage explicit paths, run `ruff check` + `ruff format` yourself, write the
message to `docs/reviews/<date>_task-<X.Y>-commit-msg.txt`; the lead commits with `git commit -F` and deletes the file.
The message file must live inside the worktree — a subagent's scratchpad path is not the lead's. Fix of the hook itself is
recorded in `docs/claude/OPEN_QUESTIONS.md`. Related: [[feedback-qex-full-rebuild-runbook]].

**Обратная сторона (2026-11-09, atlas-passport).** Хук читает ветку из каталога СЕССИИ, поэтому лид, чья сессия стоит в worktree, вносит `cd <main> && git commit` на `main` без отказа — защита обходится случайно (три коммита подряд: `6d6b36720`, `73968f13d`, `49a4a2b89`); тот же коммит из сессии в основном дереве блокируется. Слияние в `main` не завершать «через обход»: решает владелец (`.claude/protected-branches` или `~/.claude/settings.local.json`); при отказе — `git merge --abort`, чтобы не оставлять `MERGE_HEAD` в общем дереве, куда коммитят соседние линии. Гипотеза о причине не проверялась по коду хука.
