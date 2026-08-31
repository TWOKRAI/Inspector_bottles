---
name: project-devseed-overwrites-claude-dir
description: claude-kit upgrade (devseed) перетирает часть .claude/ — ценное класть только в preserved-места; _stack.md был шаблоном с плейсхолдерами и врал про Layer-trailer
metadata:
  node_type: memory
  type: project
  originSessionId: a30dc0c4-173f-4906-87e3-7f7992305a87
  modified: 2026-08-15T21:22:30.382Z
---

`.claude/` этого проекта собран claude-kit (devseed, `enabled.yaml` schema 2, seed_version 1.0.0).
`claude-kit upgrade --apply` **перетирает** часть дерева, и молча: ошибки нет, правило просто
перестаёт действовать.

**Переживает upgrade (`=preserved`) — сюда можно класть проектное:**
`CLAUDE.md` (корневой и `.claude/`), `.claude/modes/_stack.md`, `settings.local.json`,
`commit-layers.txt`. Плюс всё вне `.claude/`: `docs/claude/memory/`, `plans/`, `docs/`.

**Не переживает — восстанавливать из backup после каждого upgrade:**
`settings.json` (permissions, hooks, statusLine), остальные `modes/*`, composed-файлы
(`.mcp.json`), orphan-хуки не удаляются, но и не обновляются.

**Живой пример вреда (2026-08-16):** `_stack.md` пролежал незаполненным шаблоном seed'а —
`{{PROJECT_NAME}}`, `{{PACKAGE}}`, src-layout, «Python 3.11+», `uv run pytest -q`. Мало того
что плейсхолдеры: он **противоречил** проекту в критичном месте — «`Layer:` trailer disabled
by default», тогда как здесь `Layer:` обязателен и commit-hook без него отклоняет коммит.
Ещё codegraph / github / sequential-thinking были помечены выключенными при `enabled: true`
в `enabled.yaml`. Файл читается модами перед задачей — то есть дезинформация была на пути
исполнения. Заполнен правдой в этот же день.

**Why:** seed таргетит standalone-Python-dev (src-layout, uv-pytest, Layer опционален),
а здесь четырёхслойный фреймворк с обязательными трейлерами и своим тест-раннером.
Дефолты seed'а здесь не нейтральны — они неверны.

**How to apply:** перед `claude-kit upgrade --apply` — backup (`--backup-dir .claude/_backups`),
после — diff `settings.json` и `modes/*` с backup. Проектные факты класть в `_stack.md` или
`CLAUDE.md`, никогда в перетираемые `modes/*`. См. [[project_claude_kit_migration]].
