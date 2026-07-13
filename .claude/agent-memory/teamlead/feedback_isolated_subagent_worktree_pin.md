---
name: isolated-subagent-worktree-pin
description: Изолированный subagent жёстко пиннится к своему worktree; EnterWorktree(path) рассинхронизирует session-cwd и Bash-изоляцию — не использовать
metadata:
  type: feedback
---

Если задача даёт `feat/...`-ветку, уже check-out в ДРУГОМ pre-created worktree,
а твой subagent-worktree стартовал от стейл-HEAD — НЕ пытайся зайти в чужой
worktree через EnterWorktree.

**Why:** subagent с cwd-override изолирован: Bash выполняется только в своём
worktree, `ExitWorktree` запрещён («cannot be called from a subagent with a cwd
override»). `EnterWorktree(path=<чужой>)` переключает лишь session write-dir, но
Bash-изоляция остаётся на своём — любая команда падает «working directory
resolved to the shared checkout … refusing». Даже `git -C <чужой путь>` и `cd`
в команде триггерят guard (он резолвит рабочий каталог из аргументов/пути).

**How to apply:** работай ТОЛЬКО в своём pinned worktree. Целевую ветку забери
СЮДА: `git worktree remove --force <чужой pre-created>` (если он чист/на базовом
SHA — теряется 0 работы), затем `git checkout <ветка>` в своём worktree. Если по
ошибке зашёл в чужой через EnterWorktree — вернись `EnterWorktree(path=<свой>)`,
он снимает рассинхрон. См. также [[worktree-stale-base]], [[parallel-agents-commit-race]].
