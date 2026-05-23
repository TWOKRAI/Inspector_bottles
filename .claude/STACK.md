# STACK — TL;DR

Карта инструментов seed-а. Один экран. Полный референс с конфигами и запуском: **[`STACK_REFERENCE.md`](STACK_REFERENCE.md)**.

---

## Карта стека

```
┌─────────────────────────────────────────────────────────────┐
│                  AGENT LAYER (Claude Code)                  │
│  agents/ + commands/ + hooks/ + skills/                     │
└─────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────┐
│                       MCP SERVERS                           │
│  qex • sentrux • context7 • serena • (graphify, qt-mcp)     │
└─────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────┐
│                     QUALITY GATES                           │
│  ruff • pyright • pytest-cov • pre-commit • (bandit opt.)   │
└─────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────┐
│                  VISUALIZATION (opt.)                       │
│  Mermaid • PlantUML (pyreverse) • pydeps • Draw.io          │
└─────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────┐
│                     AUTOMATION                              │
│  Makefile • scripts/ • pre-commit framework                 │
└─────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────┐
│                       BASE LAYER                            │
│  Python 3.11+ • uv • git • VS Code • Ollama • Node          │
└─────────────────────────────────────────────────────────────┘
```

---

## Инструменты — одной таблицей

| Инструмент | Слой | Назначение | Детали |
|---|---|---|---|
| **Claude Code** | Agent | CLI/IDE-агент: код, тесты, ревью | [REFERENCE §1](STACK_REFERENCE.md#1-agent-layer--claude-code) |
| **qex** | MCP | Семантический поиск по коду (BM25 + dense) | [REFERENCE §2.1](STACK_REFERENCE.md#qex--семантический-поиск-кода) |
| **sentrux** | MCP | Архитектурные метрики, DSM, blast radius | [REFERENCE §2.2](STACK_REFERENCE.md#sentrux--архитектурный-анализ) |
| **context7** | MCP | Актуальная документация библиотек | [REFERENCE §2.3](STACK_REFERENCE.md#context7--документация-библиотек) |
| **serena** | MCP | LSP-точные symbol-операции (refs, rename) | `mcp/serena/README.md` |
| **ruff** | Quality | Линтер + форматтер (Rust, заменяет flake8+black+isort) | [REFERENCE §3.1](STACK_REFERENCE.md#ruff--линтер--форматтер) |
| **pyright** | Quality | Статический type-checker (Microsoft) | [REFERENCE §3.2](STACK_REFERENCE.md#pyright--статический-типчекинг) |
| **pytest-cov** | Quality | Test runner + coverage | [REFERENCE §3.4](STACK_REFERENCE.md#pytest-cov--coverage-отчёты) |
| **pre-commit** | Quality | Фреймворк хуков для quality gates | [REFERENCE §3.5](STACK_REFERENCE.md#pre-commit--фреймворк-хуков) |
| **bandit** | Quality (opt) | Python security scanner (OWASP-like) | [REFERENCE §3.3](STACK_REFERENCE.md#bandit--security-scanning-опционально) |
| **Mermaid** | Visual | Текстовые диаграммы (C4, sequence) | [REFERENCE §4.1](STACK_REFERENCE.md#mermaid--текстовые-диаграммы) |
| **pyreverse** | Visual | UML классов из Python-кода → PlantUML | [REFERENCE §4.2](STACK_REFERENCE.md#plantuml--uml-классов) |
| **pydeps** | Visual | Граф импортов модулей (требует Graphviz) | [REFERENCE §4.3](STACK_REFERENCE.md#pydeps--граф-зависимостей) |
| **Makefile** | Automation | Единая точка входа: `make gate` / `test` / `check` | [REFERENCE §5](STACK_REFERENCE.md#5-automation--makefile) |
| **uv** | Base | Пакетный менеджер (замена pip + venv, 10-100×) | [REFERENCE §6.2](STACK_REFERENCE.md#uv--пакетный-менеджер) |
| **Ollama** | Base | Локальный LLM-runtime (embedding для qex) | [REFERENCE §6.3](STACK_REFERENCE.md#ollama--локальный-llm-runtime) |

---

## Cheatsheet — что когда использовать

| Задача | Инструмент |
|---|---|
| Найти где используется функция/класс | **qex** (`mcp__qex__search_code`) |
| Refs / definition / rename точного символа | **serena** (LSP) |
| Узнать API библиотеки / migration guide | **context7** |
| Архитектурное здоровье / DSM / циклы | **sentrux** (`/sentrux-health`, `/sentrux-dsm`) |
| Модули без тестов | **sentrux** (`/sentrux-gaps`) |
| Линт + автоформат | **ruff** (`uv run ruff check . --fix` + `ruff format .`) |
| Проверить типы | **pyright** (`uv run pyright src`) |
| Security scan | **bandit** (опц.) |
| Coverage отчёт | **pytest-cov** (`uv run pytest --cov=<package>`) |
| Запустить всё сразу | `make gate` |
| Декомпозировать задачу | `/plan <task>` (Manager) |
| Реализовать задачу | `/implement Task X.Y` (Developer) |
| Финальная проверка перед push | `/ship` |
| Полный цикл одной командой | `/pipeline <task>` |
| Точная regex/string-проверка | **Grep** (всегда дешевле других) |

**Эвристика выбора:** «найди / опиши / что делает» → **qex**. Имя символа + действие (refs/callers/rename) → **serena**. «Что с чем связано / hubs / shortest path» → **graphify** (опц.). Точная строка / regex → **Grep**.

---

## Ключевые команды Claude Code

| Команда | Что делает |
|---|---|
| `/plan <task>` | Manager → план в `plans/<slug>.md` + ветка `<type>/<slug>` |
| `/implement Task X.Y` | Developer → код + commit с `Refs:` trailer |
| `/test` | Tester → pytest по acceptance criteria |
| `/review` | Reviewer → проверка diff'а (max 2 итерации → teamlead) |
| `/debug` | Debugger → reproduce → root cause |
| `/ship` | Quality gate + проверка Refs-цепочки + push |
| `/pipeline <task>` | Полный цикл: plan → implement → test → review → ship |
| `/team` | Состав команды (агенты + модели) |
| `/wrap-up` | Семантическое закрытие сессии → `docs/sessions/` |
| `/memory:search <q>` | Поиск по проектной памяти |

Полный список — `commands/*/` (37 команд по namespace'ам: dev, quality, spec, team, infra, analysis, memory).

---

## Зависимости между слоями

```
Agent Layer (.claude/)
   ↓ использует
MCP Servers (qex, sentrux, context7, serena)
   ↓ зависят от
Ollama + Node + sentrux-бинарь
   ↓ работают над
Кодом проекта
   ↓ проверяется через
Quality Gates (ruff, pyright, pytest-cov, опц. bandit)
   ↓ запускаются через
Makefile + git hooks (pre-commit framework)
   ↓ работают в
uv venv с зависимостями из pyproject.toml
```

---

## Где читать дальше

| Документ | Зачем |
|---|---|
| [`STACK_REFERENCE.md`](STACK_REFERENCE.md) | Полные детали: конфиги, запуск, опции, future options |
| [`BOOTSTRAP.md`](BOOTSTRAP.md) | Установка с нуля + per-machine prerequisites |
| [`CLAUDE.md`](CLAUDE.md) | Canonical instructions для агентов |
| [`modes/_stack.md`](modes/_stack.md) | **Per-project** настройка стека (READ FIRST на задаче) |
| [`COMMIT_GUIDE.md`](COMMIT_GUIDE.md) | TL;DR commit-format |
| [`VSCODE_EXTENSIONS.md`](VSCODE_EXTENSIONS.md) | VS Code расширения |
