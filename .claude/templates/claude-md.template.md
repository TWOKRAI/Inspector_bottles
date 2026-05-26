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

## `.claude/` lifecycle — `claude-kit`

> `.claude/` инфраструктура (agents, commands, hooks, MCP, skills, templates)
> сгенерирована **claude-kit** и обновляется через него, а **не** правкой файлов
> вручную. Тулза установлена глобально (`uv tool install --from <seed-repo> claude-kit`)
> и доступна как команда `claude-kit` в PATH.
>
> Если `claude-kit` не найдена — переустанови из canonical clone:
> `python <seed-clone>/scripts/install-global.py`.

### Команды (для агента)

| Задача | Команда |
|--------|---------|
| Диагностика окружения и `.claude/` | `claude-kit doctor` (+`--verbose`, `--fix`) |
| Превью обновления seed (без изменений) | `claude-kit upgrade . --dry-run` |
| Применить обновление seed | `claude-kit upgrade . --apply` |
| Список доступных компонентов | `claude-kit list-components` |
| Добавить MCP / skill / integration | `claude-kit add <name>` |
| Удалить компонент | `claude-kit remove <name>` |
| Отправить локальные правки `.claude/` в canonical seed | `claude-kit sync-back <seed-repo> --apply` |
| Версия пакета и bundled template | `claude-kit version` |
| Реконструировать SETUP-отчёт | `claude-kit show --regenerate` |
| Интерактивное меню (TUI) | `claude-kit` (без аргументов) |

### Что НЕ редактировать руками (перетрётся при `upgrade`)

- `.claude/agents/`, `.claude/commands/`, `.claude/hooks/`, `.claude/skills/`
- `.claude/templates/`, `.claude/scripts/`, `.claude/mcp/`
- `.claude/COMMIT_GUIDE.md`, `.claude/BOOTSTRAP.md`, `.claude/STACK.md`, `.claude/CLAUDE.md`
- `.claude/docs/` (SYSTEM_OVERVIEW.md, ROADMAP.md, VSCODE_EXTENSIONS.md, CLAUDE-SETUP.md)

**Workflow для правки seed-контента:** правишь в canonical seed → `claude-kit upgrade . --apply` в этом проекте. Если правка началась здесь — сначала `claude-kit sync-back <seed-repo> --apply`, потом upgrade обратно.

### Per-project артефакты (preserved при `upgrade`)

Эти файлы — твои, upgrade их **не трогает**:

- `.claude/memory/` — долговременная память агента
- `.claude/modes/_stack.md` — кастомизация под стек проекта
- `.claude/commit-layers.txt` — Layer-enum для validate_commit
- `.claude/settings.local.json` — локальные настройки CC
- `.claude/readonly-paths`, `.claude/protected-branches`
- `.claude/.seed-answers.yml` — машинно-читаемые ответы bootstrap'а (`schema_version=1`, используется `upgrade`/`add`/`remove`)
- корневой `CLAUDE.md` (этот файл) — содержит проектные плейсхолдеры

### Что делать при поломке

1. `claude-kit doctor --verbose` — первая команда. Секции: System / Project / Components / Services.
2. `claude-kit doctor --fix` — попытка авто-install отсутствующего (uv tools, MCP servers).
3. `claude-kit upgrade . --dry-run` — если расхождение с seed.
4. `claude-kit version` — сверить версию пакета и bundled template (могут разойтись после `git pull` в seed без `install-global.py`).

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

### Makefile

| Команда | Что делает |
|---------|-----------|
| `make install` | Установить deps + pre-commit hooks |
| `make check` | Lint (ruff) + typecheck (pyright) |
| `make test` | pytest с coverage |
| `make gate` | Полный gate (check + test) перед push |
| `make format` | Автофикс ruff |

### Slash-команды (через Claude Code)

Команды живут в `.claude/commands/<namespace>/<name>.md`. Полный список —
`/help` в Claude Code или `ls .claude/commands/`. Ключевые namespace'ы:

| Namespace | Назначение | Ключевые команды |
|-----------|-----------|------------------|
| `dev/` | Plan-Driven Dev цикл | `/plan`, `/implement`, `/test`, `/review`, `/debug`, `/ship`, `/pipeline`, `/plan-status`, `/adr` |
| `spec/` | Living spec (`docs/direction/`) | `/spec`, `/spec-sync` |
| `team/` | Команда агентов | `/team`, `/hire`, `/handoff`, `/docs`, `/wrap-up` |
| `memory/` | Долговременная память агента | `/memory:status`, `/memory:search <query>`, `/memory:init` |
| `quality/` | Качество кода + архитектура | `/quality:doctor`, `/quality:arch-review`, `/quality:lint-agents`, `/quality:lint-settings`, `/quality:sentrux-*`, `/quality:qex-*`, `/quality:code-stats*`, `/quality:test-ratio` |
| `infra/` | Инфраструктурные операции | `/infra:clean-cache`, `/infra:cold-start`, `/infra:diagrams`, `/infra:fw-test`, `/infra:run-proto` |
| `analysis/` | Анализ кодовой базы | `/analysis:todo-inventory` |
| `knowledge/` | Knowledge pipeline (если установлен university team) | `/transcribe`, `/curate`, `/synthesize`, `/research`, `/library`, `/translate`, `/digest`, `/compress`, `/search` |

Subagent'ы: `claude-kit` поставляет dev-команду (developer, reviewer, manager,
teamlead, debugger, tester, docs-writer, tech-writer) и опционально university
(curator, synthesizer, researcher, librarian, translator). Список — `/team`.

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
