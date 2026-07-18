---
name: feedback_walk_skips_worktrees
description: Скрипты, переписывающие файлы по всему проекту (os.walk/grep-replace), обязаны исключать .claude/worktrees/
metadata:
  type: feedback
---

Массовая замена строки по проекту (project-wide rename, обновление ссылок) через `os.walk(".")` залезает в `.claude/worktrees/agent-*` — это ПОЛНЫЕ git-чекауты других агентов (каждый со своим .git, на своей ветке). Так можно наследить в десятках файлов чужих worktree (было при переносе probes, C.2).

**Why:** worktrees gitignored из основного дерева (в `git status` их правок не видно), но физически на диске они есть — скрипт их модифицирует, засоряя чужую незакоммиченную зону.

**How to apply:** в любом walk/replace по проекту явно скипать `.claude/worktrees` (и `.git`): `if "/.claude/worktrees" in root or "/.git" in root: continue`. Откат чужих worktree — реверс-заменой строки (git checkout на worktree отклоняется классификатором), проверив `git -C <wt> status` что там были ТОЛЬКО мои правки. Связано с [[feedback_git_stash_pop_wrong_stash]] и worktree-ловушками.
