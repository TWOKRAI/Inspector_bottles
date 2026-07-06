---
description: Rebuild docs/PROJECT_CONTEXT.md from per-module CONTEXT.md and DECISIONS.md
---

# /core:quality:sync-context — обновить project-wide context registry

Запускает `scripts/aggregate_context` для сборки сводного реестра
per-module знаний в `docs/PROJECT_CONTEXT.md`.

## Когда использовать

- После создания нового `<module>/CONTEXT.md` или `<module>/DECISIONS.md`
- После добавления нового ADR в существующий `DECISIONS.md` модуля
- После переименования модуля или изменения `module_code` в frontmatter
- В CI — для гарантии что registry не дрифтует

## Использование

```
/core:quality:sync-context              # write-режим — обновить registry
/core:quality:sync-context --check      # CI-режим — diff + exit 1 при дрифте
/core:quality:sync-context --list       # список зарегистрированных sync-модулей
/core:quality:sync-context --only render_context   # только один модуль
```

## Что делает

1. Сканирует проект, находит все `**/CONTEXT.md` и `**/DECISIONS.md`
   (с exclusions: `_archive`, `node_modules`, `.venv`, `__pycache__`, …)
2. Парсит per-module файлы, извлекает Purpose / sections / ADR headers.
3. Рендерит три таблицы в `docs/PROJECT_CONTEXT.md` между маркерами
   `CONTEXT-INDEX`, `ADR-CODES`, `ADR-INDEX`.
4. Текст вне маркеров **не трогает**.

## Pre-requisites

- `docs/PROJECT_CONTEXT.md` **сеется бутстрапом** (`claude-kit-project new`)
  вместе со стартовым `src/<package>/CONTEXT.md`. Если файла нет (legacy-проект) —
  создай из `.claude/plugins/core/templates/PROJECT_CONTEXT.template.md`.
- Хотя бы один модуль имеет CONTEXT.md или DECISIONS.md (свежий проект уже имеет
  `src/<package>/CONTEXT.md`).

Если registry-файл отсутствует — скрипт выдаст человечную ошибку и
exit 2.

## Разделы per-module CONTEXT.md

Шаблон `.claude/plugins/core/templates/CONTEXT.template.md` (все секции опциональны,
оставляй только нетривиальное):

- **Purpose** — что и зачем делает модуль (1-3 фразы).
- **Key decisions** — ссылки на ADR / якорные решения дизайна.
- **Gotchas** — footguns и неочевидные грабли (самое ценное для агента).
- **Glossary** — local-термины, значащие здесь не то, что в индустрии.
- **Open questions** — осознанно нерешённое (трогать без согласования не стоит).
- **Migration notes** — важные миграции и почему живёт legacy-код.

Aggregator индексирует наличие этих секций (колонки P/K/G/Gl/O/M в registry),
сам текст CONTEXT.md не трогает.

## Обоснование наличия в seed

Pattern портирован из Inspector_bottles (там 20+ модулей с
DECISIONS.md). Польза для агентной системы: при заходе в модуль X
агент сразу читает `<X>/CONTEXT.md` — знает Gotchas, design decisions,
glossary. Снижает «слепое чтение» исходников.

## Связанные команды

- `/dev:adr` — создать **глобальный** (cross-module) ADR в `docs/decisions/`
- `/mcp-sentrux:sentrux-dsm` — view зависимостей между модулями (визуальный pendant)
- skill `module-contract` — при создании нового модуля рекомендует
  CONTEXT.md если есть Gotchas или Key decisions

## Что НЕ делает

- Не создаёт CONTEXT.md / DECISIONS.md per-module — это делает агент
  или человек руками из шаблона.
- Не редактирует тело ADR — только индекс.
- Не парсит markdown за пределами H2-заголовков — структура простая.
