---
name: feedback-enabled-false-does-not-unload-a-plugin
description: enabled false в enabled.yaml не мешает Claude Code читать папку плагина — агенты и команды грузятся в контекст; выгружает только физический вынос из .claude/plugins/
metadata:
  node_type: memory
  type: feedback
  originSessionId: a30dc0c4-173f-4906-87e3-7f7992305a87
  modified: 2026-08-15T21:39:42.861Z
---

`enabled.yaml` — абстракция **claude-kit**, а не Claude Code. Она управляет композицией
(`.mcp.json`, `settings.json`), но **не тем, какие папки читает Claude Code**.

Измерено 2026-08-16: плагин `knowledge` стоял `enabled: false`, при этом все его **9 агентов
`sci-*` и 7 команд** (`/curate`, `/research`, `/synthesize`, `/transcribe`, `/translate`, `/kb`,
`/library`) присутствовали в списке доступных — то есть занимали контекст каждую сессию
(~780 токенов). Claude Code сканирует `.claude/plugins/*/agents/` и `*/commands/` напрямую.

**Проверка, а не вера в флаг:** искать имя агента/команды в фактически доступном списке, а не
читать `enabled.yaml`. Флаг говорит о намерении, список — о факте.

**Как выгрузить на самом деле:** физически вынести папку за пределы `.claude/`
(здесь — `git mv .claude/plugins/knowledge docs/claude/frozen/knowledge-plugin`, по правилу
владельца FREEZE, а не KILL). После выноса запись в `enabled.yaml` остаётся и даёт статус
missing — безвредно.

**Смежное:** `.claude/commands/` — composed-копия команд из плагинов, файлы лежат дважды,
но Claude Code дедуплицирует по имени, поэтому удаление копии **не экономит контекст**.
Считать экономию надо по записям в списке, а не по файлам на диске: подсчёт по файлам
завысил оценку вчетверо.

**Why:** это класс «названный механизм — не обязательство» ([[feedback_named_mechanism_is_not_a_commitment]]) —
выключатель есть, имя правильное, а выключения нет. Отказ тихий: ничего не падает, просто
контекст платится за то, что считается отключённым.

**Related:** [[project_devseed_overwrites_claude_dir.md]], [[feedback_freeze_over_kill]].
