# .claude/ — Конфигурация Claude Code

Папка с агентами, командами, режимами, хуками и MCP-инфраструктурой для проекта **Inspector_bottles**.
Проектный контекст (стек, пути, правила) — в корневом [`CLAUDE.md`](../CLAUDE.md).

> **Кросс-платформа.** Все скрипты работают и на **macOS**, и на **Windows**: `bootstrap.py` и `qex-launcher.py` сами определяют ОС, hooks написаны через bash (на Windows — Git Bash).

---

## Файлы и папки

| Файл / Папка | Назначение |
|--------------|-----------|
| [`CLAUDE.md`](CLAUDE.md) | Project extensions: режимы (modes), language policy |
| [`../CLAUDE.md`](../CLAUDE.md) | **Главный** — проектный контекст (single source of truth) |
| [`CLAUDE-SETUP.md`](CLAUDE-SETUP.md) | Как перенести `.claude/` в новый проект |
| [`settings.json`](settings.json) | Tools allowlist + хуки + statusLine |
| `settings.local.json` | Локальный override (gitignored) |
| [`agents/`](agents/) | Sub-агенты (`company/`, `_template.md`) |
| [`commands/`](commands/) | Slash-команды (см. ниже) |
| [`modes/`](modes/) | Режимы работы (`dev.md`, `spec.md`) |
| [`hooks/`](hooks/) | Хуки на события (validate-safe, autoformat, check-imports) |
| [`skills/`](skills/) | Skills для агентов (`kb-discover/`, `kb-lint/`) |
| [`mcp/`](mcp/) | **MCP-инфраструктура** — template, launcher, bootstrap |
| [`platforms/`](platforms/) | Platform-specific overrides (macOS / Windows) |

---

## MCP-серверы

Подробнее в [`mcp/README.md`](mcp/README.md).

| Сервер | Уровень | Назначение |
|--------|---------|------------|
| **qex** | проектный (`.mcp.json`) | Семантический поиск по коду (Ollama + BM25) |
| **sentrux** | проектный (`.mcp.json`) | Архитектурный health-gate (DSM, метрики, gaps) |
| **Context7** | user-level (`~/.claude.json`) | Актуальная документация библиотек |

**Установка в новом проекте:**
```bash
python3 .claude/mcp/bootstrap.py    # macOS / Linux
python .claude/mcp/bootstrap.py     # Windows
```

---

## Агенты IT-Команды (`agents/company/`)

| Агент | Модель | Роль |
|-------|--------|------|
| `manager` | Opus | Декомпозиция задачи → ТЗ с уровнями сложности (Task X.Y) |
| `teamlead` | Opus | Старший разработчик — Senior+ задачи, экспресс-ревью |
| `developer` | Sonnet | Реализация кода по ТЗ, smoke-тесты, коммиты |
| `reviewer` | Opus | Финальный код-ревью (архитектура + безопасность) |
| `tester` | Sonnet | Тесты по acceptance criteria |
| `debugger` | Sonnet | Диагностика падающих тестов, регрессий, непонятных ошибок |
| `docs-writer` | Haiku | Простая документация — docstrings, README, STATUS.md |
| `tech-writer` | Sonnet | Сложная документация — DECISIONS.md (ADR), ARCHITECTURE.md, RFC |
| `spec-writer` | Sonnet | Живое ТЗ (`docs/direction/`) с точки зрения пользователя |
| `_template` | — | Шаблон для `/hire` (в корне `agents/`) |

### Workflow разработки

```
/plan → /implement → /test → /review → /docs → /ship
Полный автомат: /pipeline
Нанять нового специалиста: /hire <роль>
```

### Пороги сложности

| Объём | Исполнитель |
|-------|-------------|
| 1-3 файла, <80 строк | Director (main) |
| 4-9 файлов | Developer → TeamLead (экспресс-ревью) |
| 10+ файлов, архитектура | Manager → Developer → Reviewer |

---

## Slash-команды (`commands/`)

### Workflow разработки

| Команда | Файл | Действие |
|---------|------|----------|
| `/pipeline` | `pipeline.md` | Полный цикл разработки |
| `/plan` | `plan.md` | Manager → декомпозиция → ТЗ |
| `/implement` | `implement.md` | Developer → реализация Task X.Y |
| `/test` | `test.md` | Tester → тесты |
| `/review` | `review.md` | Reviewer → код-ревью |
| `/debug` | `debug.md` | Debugger → диагностика |
| `/docs` | `docs.md` | Docs Writer → документация |
| `/ship` | `ship.md` | Финальная проверка перед merge |

### Спецификации

| Команда | Файл | Действие |
|---------|------|----------|
| `/spec` | `spec.md` | Создать/обновить живое ТЗ |
| `/spec-sync` | `spec-sync.md` | Синхронизировать ТЗ с кодом |

### Проектные

| Команда | Файл | Действие |
|---------|------|----------|
| `/validate` | `validate.md` | `python scripts/validate.py` |
| `/fw-test` | `fw-test.md` | `python scripts/run_framework_tests.py` |
| `/qex-status` | `qex-status.md` | Статус qex-индекса |
| `/qex-reindex` | `qex-reindex.md` | Переиндексация qex |
| `/run-proto` | `run-proto.md` | Запуск прототипа PySide6 |
| `/cold-start` | `cold-start.md` | Холодный старт: Ollama + venv |

### Инфраструктура

| Команда | Файл | Действие |
|---------|------|----------|
| `/team` | `team.md` | Показать состав команды |
| `/hire` | `hire.md` | Создать нового агента |
| `/handoff` | `handoff.md` | Документ для cross-machine handoff |

---

## Хуки (`hooks/`)

Все хуки **кросс-платформенные** (работают через Git Bash на Windows).

| Скрипт | Тип | Действие |
|--------|-----|----------|
| `validate-safe-command.sh` | PreToolUse (Bash) | Блокирует опасные команды (`rm -rf /`, `dd if=/dev/zero` и т.п.) |
| `autoformat-python.sh` | PostToolUse (Edit/Write) | `ruff format` + `ruff check --fix` (поддержка `venv/Scripts/ruff.exe` на Windows) |
| `check-imports.sh` | PostToolUse (Edit/Write) | `python -m py_compile` (проверка синтаксиса) |
| `session-end-daily-log.sh` | (отключён) | Был для KnowledgeOS, оставлен как пример |

`hooks/tests/test_hooks.sh` — smoke-тесты для хуков.

---

## Двух-машинный workflow (Windows днём + macOS вечером)

| Что | Как синхронизируется |
|-----|----------------------|
| `.claude/` целиком | через git (всё в репозитории) |
| `.mcp.json` | через git (после `bootstrap.py`) |
| `qex-launcher.py` | сам определяет ОС → подбирает модель Ollama (`8b` macOS / `4b` Windows) |
| MCP биндинги | sentrux ставится на каждой машине (brew/exe), Context7 — OAuth раз на машину |
| Hooks | работают через Git Bash на Windows (нужен Git for Windows) |
| `settings.local.json` | gitignored — на каждой машине свой (см. `platforms/`) |
| qex-индекс (`~/.qex/`) | у каждой машины свой, после `git pull` запусти `/qex-reindex` |

При переезде:

```bash
# 1. На Windows-машине (днём)
git pull
python .claude/mcp/bootstrap.py     # проверит зависимости
# /qex-reindex (если кодовая база заметно изменилась)

# 2. На macOS-машине (вечером)
git pull
python3 .claude/mcp/bootstrap.py
# /qex-reindex
```

---

## Добавить нового специалиста

1. Запусти `/hire <роль>` — создаст агента по `agents/_template.md`
2. Заполни: `name`, `description`, `model`, `tools`, workflow
3. Обнови таблицы в `.claude/README.md`
4. При необходимости добавь slash-команду в `commands/`
