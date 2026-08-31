# Stack — Inspector_bottles

> Per-project customization point. `=preserved` при `claude-kit upgrade` (devseed) —
> правки здесь переживают апгрейд, в отличие от `settings.json` и остальных `modes/*`.
> Единственный источник правды по архитектуре и путям — корневой `CLAUDE.md`.
> Здесь только то, чего там нет, и то, что seed заполнил бы неверно.

## Project

- **Name:** Inspector_bottles — фреймворк многопроцессных приложений + прототип инспекции дефектов
- **Layout:** НЕ src-layout. Слои: `multiprocess_framework/` → `Services/` → `Plugins/` → `multiprocess_prototype/` (composition root)
- **Точка входа:** `multiprocess_prototype/run.py`

## Toolchain (правится под проект — дефолты seed здесь неверны)

- **Language:** Python **3.12** (не 3.11+ из seed)
- **Package manager:** `uv`, но **пакеты ставит пользователь** — не выполнять install самому.
  `uv sync` сносит необъявленное → только `--inexact`
- **Test:** `python scripts/run_framework_tests.py` / `python scripts/validate.py` / `make test`.
  Ручной pytest — из корня проекта, иначе `ModuleNotFoundError`. НЕ `uv run pytest -q`
- **Gate:** `make gate` (= `make check` + `make test`); `make check` = ruff + pyright + bandit
- **Агентские прогоны:** всегда `QT_QPA_PLATFORM=offscreen` — Qt-окно вешает агента

## Commit format

- **Validator:** [x] enabled (`.git/hooks/commit-msg`)
- **Required trailers:** `Why:` **и** `Layer:` — оба обязательны (seed по умолчанию считает
  `Layer:` выключённым; здесь это неверно, хук отклонит коммит)
- **Layer values:** framework | services | plugins | prototype | docs | scripts | tests | infra | mixed
- **Refs:** обязателен, если задача из плана — `Refs: plans/<slug>.md`

## Language policy

- **User-facing output:** русский, строго (см. `.claude/CLAUDE.md` § Language policy)
- **Code comments / docstrings:** русский
- **System files (.claude/, settings.json, memory):** английский

## Plans & Specs

- **Plans root:** `plans/<slug>.md` или `plans/<slug>/plan.md` (multi-phase)
- **Specs root:** `docs/direction/` — живые спеки продукта
- **Branch:** `<type>/<slug>`, стандарт `feat/`, не `feature/`

## MCP — фактическое состояние (сверено с `.claude/enabled.yaml`)

Включены: **qex** (семантический поиск), **sentrux** (DSM/метрики), **serena** (LSP-символы),
**context7** (доки библиотек), **graphify** (граф кода), **qt-mcp** (инспекция PySide6),
**ast-grep** (структурный поиск), **codegraph**, **backend-ctl** (живой бэкенд),
**github**, **sequential-thinking**, **sentry**.
Выключены: **playwright** (проект не веб), **hello-world**, **knowledge**.

Схемы MCP-инструментов отложены (ToolSearch) — держать сервер включённым дёшево.

## Architecture notes

- **R1** — Dict at Boundary: между процессами только `dict` (`to_dict`/`from_dict`), Pydantic внутри процесса
- **R2** — обратные импорты между слоями запрещены, enforced через `.sentrux/rules.toml`
- **R3** — имя процесса (`targets`) ≠ канал Router (`FieldRouting.channel`); см. `ROUTING_GLOSSARY.md`
- **R4** — логи только через `ObservableMixin` / менеджеры, пути из env (`MULTIPROCESS_LOG_DIR` / `INSPECTOR_LOG_DIR`)
- ADR: локальные → `modules/X/DECISIONS.md`, глобальные → `multiprocess_framework/DECISIONS.md`;
  после правок — `python -m scripts.sync`
