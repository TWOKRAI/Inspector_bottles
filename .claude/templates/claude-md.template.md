# {{PROJECT_NAME}}

## Цель

{{DESCRIPTION}}

## Архитектура

> Замени на реальные слои/модули. Если простой скрипт — можно удалить секцию.

- **Layer 1:** что делает
- **Layer 2:** что делает

## Ключевые пути

| Что | Путь | Кто читает / пишет |
|-----|------|-----|
| Главный пакет | `src/{{PACKAGE}}/` | код проекта |
| Тесты | `tests/` | pytest, tester-агент |
| Скрипты | `scripts/` | makefile, dev-команды |
| Валидатор коммитов | `scripts/validate_commit/` | `commit-msg` hook |
| Документация | `docs/` | люди + агенты |
| Гайд по коммитам | `.claude/COMMIT_GUIDE.md` | агенты при коммите |
| Журналы сессий | `docs/sessions/YYYY-MM-DD.md` | `/wrap-up`, `/memory:search` |
| Планы задач (Plan-Driven Dev) | `plans/YYYY-MM-DD_<slug>.md` (single) или `plans/YYYY-MM-DD_<slug>/plan.md`+`phase-N.md` (multi-phase) | `/plan`, `/implement`, `/ship` |
| Долговременная память | `.claude/memory/MEMORY.md` + `*.md` | агент (auto-memory rules) |
| Конфиг Layer-enum | `.claude/commit-layers.txt` | validate_commit.py |
| Данные (gitignored) | `data/` | runtime |

**Принцип:** одна папка — одна ответственность. Plan-driven workflow связывает их через `Refs: plans/<slug>.md` trailer в каждом коммите задачи. См. [`.claude/COMMIT_GUIDE.md`](.claude/COMMIT_GUIDE.md), [`plans/README.md`](plans/README.md), [`.claude/CLAUDE.md`](.claude/CLAUDE.md) → "Memory (OVERRIDE)".

## Стек

- **Python:** 3.11+
- **Package manager:** uv
- **Lint + format:** ruff
- **Type check:** pyright
- **Tests:** pytest + pytest-cov
- **Pre-commit:** ruff (commit) + pyright (push)

## Правила проекта

1. **Стиль:** ruff format + check автоматически в pre-commit
2. **Типы:** type hints обязательны для публичных функций, pyright `standard` mode
3. **Тесты:** обязательны при изменении логики
4. **Секреты:** только в `.env` (gitignored)
5. **Commit-сообщения:** Conventional Commits, trailer `Why:` всегда

## Команды

| Команда | Что делает |
|---------|-----------|
| `make install` | Установить deps + pre-commit hooks |
| `make check` | Lint + typecheck |
| `make test` | pytest с coverage |
| `make gate` | Полный gate (check + test) перед push |
| `make format` | Автофикс ruff |
| `/plan <task>` | Декомпозиция задачи (Manager-агент) |
| `/implement` | Реализация (Developer-агент) |
| `/ship` | Финальная проверка перед merge |

## Tool routing (MCP)

Шаблон даёт несколько MCP-инструментов на разные задачи. Правила маршрутизации
помогают агенту выбрать нужный, не дублируя работу. Активируй только те, что
реально нужны проекту — см. `.claude/modes/_stack.md` → "MCP".

| Тип запроса | Инструмент | Когда |
|-------------|-----------|-------|
| Семантический / fuzzy поиск по коду ("где у нас валидация прав", "найди код типа X") | **qex** | Codebase ≥ 5k LOC |
| Точные symbol-операции (refs, definition, rename, move across files) | **serena** (LSP) | Опц., experimental — см. `.claude/mcp/serena/README.md` |
| Архитектурный обзор / knowledge graph (god nodes, shortest path, hubs) | **graphify** | По требованию, не постоянно |
| Архитектурные метрики / DSM / cycles / quality gate | **sentrux** | Перед `/ship`, периодически |
| Документация библиотек | **context7** | Уточнение API чужих библиотек |
| Runtime inspection PyQt/PySide GUI (widget tree, screenshots, clicks) | **qt-mcp** | Только в GUI-проектах |
| Точное имя символа, полный список вхождений (`Grep` достаточно) | **Grep** | Дешевле всех остальных |

**Эвристика:** «найди / опиши / что делает» + поведение → **qex**.
Имя символа + действие (refs/callers/rename) → **serena**.
"Что с чем связано?" → **graphify**.
Точная строка / regex → **Grep**.

Подробнее об опциях и установке — `.claude/mcp/README.md`.

## Память агента (override)

Долговременная память живёт в [`.claude/memory/`](.claude/memory/) (под git, портативна между машинами), **а не** в нативном `~/.claude/projects/<project>/memory/`. Правила записи и команды — см. [`.claude/CLAUDE.md`](.claude/CLAUDE.md) → "Memory (OVERRIDE)".

Команды: `/memory:status`, `/memory:search <query>`, `/memory:init`.

## `.claude/`

- [`.claude/BOOTSTRAP.md`](.claude/BOOTSTRAP.md) — установка с нуля
- [`.claude/STACK.md`](.claude/STACK.md) — все инструменты
- [`.claude/modes/_stack.md`](.claude/modes/_stack.md) — кастомизация под проект
