---
name: feedback-precommit-rollback-drops-unstaged-edits
description: Откат pre-commit при конфликте авто-фиксов молча теряет НЕзастейдженные правки в посторонних файлах — перед коммитом дерево должно быть без незастейдженных хвостов
metadata:
  type: feedback
---

Если хук pre-commit что-то авто-исправил (`ruff format`) **и** в дереве есть незастейдженные
правки, pre-commit пытается наложить свой патч поверх возвращаемого стеша, получает конфликт и
делает «Rolling back fixes». Откат **не сообщает о потере**: коммит не создаётся, а
незастейдженная правка в постороннем файле исчезает.

**Живьём (2026-08-14, Task 3.1).** Коммит кода упал так:

```
ruff format .......... Failed  - files were modified by this hook
[WARNING] Stashed changes conflicted with hook auto-fixes... Rolling back fixes...
error: patch failed: docs/claude/memory/MEMORY.md:61
error: docs/claude/memory/MEMORY.md: patch does not apply
```

После этого `MEMORY.md` пропал из `git status` вовсе — строка индекса, дописанная агентом,
откатилась к HEAD. Файл записи при этом остался untracked, то есть потеря была ЧАСТИЧНОЙ и
незаметной: запись есть, ссылки на неё нет.

Отдельный участник конфликта — хук `append session log to docs/sessions/`: он дописывает файл на
каждом коммите, и этот же файл почти всегда висит в состоянии `MM` (застейджен и снова изменён).

**Как применять.** Перед `git commit`:

1. `git status --porcelain` — не должно остаться строк с изменением во ВТОРОЙ колонке
   (` M`, `MM`); `git add` их или отложи явно;
2. если хук всё же переформатировал — `git add` затронутые файлы и повторить коммит
   ([[feedback-commit-msg-format]]);
3. после падения коммита **проверить соседние файлы**, а не только те, что коммитил: откат мог
   съесть чужую правку. Дешёвая проверка — `grep` по ожидаемой строке, а не взгляд на `git status`
   (в статусе потеря выглядит как чистота).

Связано: [[feedback-commit-msg-format]], [[feedback-commit-takes-the-whole-index]],
[[feedback-plan-dual-save]].
