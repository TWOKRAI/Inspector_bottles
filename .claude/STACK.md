# STACK — TL;DR

Карта инструментов seed-а. Один экран. Полные детали и опции — см.
`<details>` блок внизу или прыгайте по якорям из таблицы.

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
| **Claude Code** | Agent | CLI/IDE-агент: код, тесты, ревью | [§1](#1-agent-layer--claude-code) |
| **qex** | MCP | Семантический поиск по коду (BM25 + dense) | [§2.1](#qex--семантический-поиск-кода) |
| **sentrux** | MCP | Архитектурные метрики, DSM, blast radius | [§2.2](#sentrux--архитектурный-анализ) |
| **context7** | MCP | Актуальная документация библиотек | [§2.3](#context7--документация-библиотек) |
| **serena** | MCP | LSP-точные symbol-операции (refs, rename) | [§2.4](#serena--lsp-точные-symbol-операции) |
| **ruff** | Quality | Линтер + форматтер (Rust, заменяет flake8+black+isort) | [§3.1](#ruff--линтер--форматтер) |
| **pyright** | Quality | Статический type-checker (Microsoft) | [§3.2](#pyright--статический-типчекинг) |
| **pytest-cov** | Quality | Test runner + coverage | [§3.4](#pytest-cov--coverage-отчёты) |
| **pre-commit** | Quality | Фреймворк хуков для quality gates | [§3.5](#pre-commit--фреймворк-хуков) |
| **bandit** | Quality (opt) | Python security scanner (OWASP-like) | [§3.3](#bandit--security-scanning-опционально) |
| **Mermaid** | Visual | Текстовые диаграммы (C4, sequence) | [§4.1](#mermaid--текстовые-диаграммы) |
| **pyreverse** | Visual | UML классов из Python-кода → PlantUML | [§4.2](#plantuml--uml-классов) |
| **pydeps** | Visual | Граф импортов модулей (требует Graphviz) | [§4.3](#pydeps--граф-зависимостей) |
| **Makefile** | Automation | Единая точка входа: `make gate` / `test` / `check` | [§5](#5-automation--makefile) |
| **uv** | Base | Пакетный менеджер (замена pip + venv, 10-100×) | [§6.2](#uv--пакетный-менеджер) |
| **Ollama** | Base | Локальный LLM-runtime (embedding для qex) | [§6.3](#ollama--локальный-llm-runtime) |

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
| [`BOOTSTRAP.md`](BOOTSTRAP.md) | Установка с нуля + per-machine prerequisites |
| [`CLAUDE.md`](CLAUDE.md) | Canonical instructions для агентов |
| [`modes/_stack.md`](modes/_stack.md) | **Per-project** настройка стека (READ FIRST на задаче) |
| [`COMMIT_GUIDE.md`](COMMIT_GUIDE.md) | TL;DR commit-format |
| [`docs/VSCODE_EXTENSIONS.md`](docs/VSCODE_EXTENSIONS.md) | VS Code расширения |

---

<details>
<summary><strong>Полная справка по стеку</strong> — конфиги, запуск, опции, future options (~340 строк)</summary>

## 1. Agent Layer — Claude Code

### Что это
**Claude Code** — CLI и IDE-расширение для AI-агента Anthropic. Понимает кодовую базу,
выполняет multi-step задачи, использует MCP-серверы и встроенные инструменты.

### Конфигурация — папка `.claude/`

| Подпапка | Что внутри |
|----------|------------|
| `agents/company/` | 10 ролей: developer, reviewer, manager, debugger, tester, teamlead, tech-writer, spec-writer, docs-writer, investigator |
| `commands/` | 37+ slash-команд (dev, quality, analysis, spec, infra, team, memory) |
| `modes/` | dev.md, spec.md — режимы работы |
| `hooks/` | SessionStart, PreToolUse, PostToolUse, PostCompact, Stop |
| `mcp/` | Конфиги и SETUP_GUIDE для qex/sentrux/context7/serena/codegraph |
| `templates/` | Шаблоны pyproject, pre-commit, Makefile, sentrux rules, protected-branches, readonly-paths |
| `skills/` | caveman, grill-me, prototype, zoom-out (project-local) |
| `memory/` | Долговременная память (override native path → git-tracked) |

### Использование

| Команда | Что делает |
|---------|-----------|
| `/plan <task>` | Декомпозиция задачи в ТЗ (Manager) |
| `/implement` | Реализация (Developer) |
| `/test` | Написание тестов |
| `/review` | Код-ревью |
| `/ship` | Финальная проверка перед merge |
| `/pipeline` | Полный цикл plan→implement→test→review→ship |

---

## 2. MCP Servers

### qex — семантический поиск кода

**Что делает:** индексирует кодовую базу, выполняет гибридный поиск (BM25 + dense vectors).
Позволяет агенту находить код по смыслу, а не только по тексту.

**Когда использовать:** «где используется X», «где код, который делает Y», поиск перед рефакторингом.

**Технология:** Ollama (`qwen3-embedding:4b` Win / `:8b` macOS) + Tantivy BM25 + brute-force dense vectors.
Индекс в `~/.qex/` (а не в проекте).

**Команды:**
- `/qex-status` — статус индекса
- `/qex-reindex` — инкрементальная переиндексация
- `/qex-rebuild` — полная переиндексация с нуля

**Документация:** [`mcp/qex/SETUP_GUIDE.md`](mcp/qex/SETUP_GUIDE.md)

---

### sentrux — архитектурный анализ

**Что делает:** статический анализ структуры проекта. 14 метрик качества (modularity, acyclicity,
depth, equality), дерево зависимостей, blast radius, проверка архитектурных правил.

**Когда использовать:** перед/после рефакторинга, перед `/ship`, при подозрении на архитектурный долг.

**Технология:** бинарь `sentrux` (Go), читает `.sentrux/rules.toml`, генерирует health-отчёты.

**Команды:**
- `/sentrux-health` — снимок здоровья (scan + metrics)
- `/sentrux-dsm` — Dependency Structure Matrix, циклы
- `/sentrux-gaps` — модули без тестов
- `/sentrux-baseline` — зафиксировать состояние
- `/sentrux-diff` — дельта с baseline
- `/sentrux-check` — CI-friendly проверка правил
- `/arch-review` — комплексный отчёт (health + DSM + gaps)

**Документация:** [`mcp/sentrux/README.md`](mcp/sentrux/README.md)

---

### context7 — документация библиотек

**Что делает:** актуальная документация по любой публичной библиотеке/фреймворку. Заменяет
устаревшие знания агента или Google-поиск.

**Когда использовать:** новая версия API библиотеки, миграция, незнакомая зависимость.

**Технология:** SaaS, OAuth, free tier. Установка глобально на машину (`~/.claude.json`).

**Установка:**
```bash
npx -y ctx7 setup --claude
```

**Документация:** [`mcp/context7/README.md`](mcp/context7/README.md)

---

### serena — LSP-точные symbol операции

**Что делает:** language-server-backed точные операции по символам: find_declaration,
find_referencing_symbols, rename_symbol, find_implementations. Дополняет qex (где qex
ищет «по смыслу», serena ищет «по AST/LSP»).

**Когда использовать:** рефакторинг (переименовать символ во всём проекте), поиск всех
вызовов функции с гарантией полноты, переход к определению.

**Документация:** [`mcp/serena/README.md`](mcp/serena/README.md), [`mcp/serena/SETUP_GUIDE.md`](mcp/serena/SETUP_GUIDE.md)

---

## 3. Quality Gates

### ruff — линтер + форматтер

**Что делает:** заменяет flake8 + isort + black + многие плагины. Очень быстрый (Rust).

**Конфиг:** `[tool.ruff]` в `pyproject.toml` — `target-version = "py311"`, `line-length = 100`. `.claude/` в `extend-exclude` — seed/тулинг не часть проектного кода.

**Запуск:**
```bash
uv run ruff check .                # lint
uv run ruff check --fix .          # с автофиксом
uv run ruff format .               # формат
```

**В pre-commit:** запускается на каждый commit.

---

### pyright — статический типчекинг

**Что делает:** проверяет аннотации типов в Python-коде. Ловит баги до запуска. Microsoft, используется внутри Pylance в VS Code.

**Стратегия:** mode `standard` по умолчанию (между `basic` и `strict`). Можно постепенно поднимать до `strict` модуль за модулем через `# pyright: strict` в файле.

**Конфиг:** `[tool.pyright]` в `pyproject.toml`. `.claude/` в `exclude` — seed/тулинг не часть проектного кода.

**Запуск:**
```bash
uv run pyright src
```

**В pre-commit:** на **pre-push** (не блокирует каждый commit, но блокирует push).

**Опциональный hook на Edit:** `hooks/python/typecheck-changed.sh` — non-blocking pyright на изменённый файл. Активация: `export CLAUDE_TYPECHECK_ON_EDIT=1`. По умолчанию выключен (cold-start латентен).

**Future option:** [`ty`](https://github.com/astral-sh/ty) от Astral — новый type checker написанный на Rust. На альфа-стадии в 2026. Когда стабилизируется — заменит pyright (та же роль, быстрее).

---

### bandit — security scanning (опционально)

**Что делает:** статический анализ безопасности. Ловит OWASP-уязвимости: hardcoded passwords, SQL injection, `eval()`, небезопасный `random`.

**Когда включать:** проекты которые обрабатывают untrusted input (веб, API, CLI с публичным доступом). Для персональных утилит обычно не нужен.

**Включение:** раскомментировать секцию в `.pre-commit-config.yaml` + добавить `[tool.bandit]` в `pyproject.toml`.

```bash
uv add --group dev "bandit[toml]"
uv run bandit -r src -c pyproject.toml -q
```

---

### pytest-cov — coverage-отчёты

**Что делает:** интеграция pytest + coverage.py. Показывает покрытие тестами.

**Конфиг:** `[tool.coverage]` в `pyproject.toml`.

**Запуск:**
```bash
uv run pytest --cov=<package> --cov-report=term-missing
```

**Опция:** включить `fail_under = 60` в `[tool.coverage.report]` чтобы CI падал при низком покрытии.

---

### pre-commit — фреймворк хуков

**Что делает:** запускает все quality gates автоматически перед commit/push.

**Конфиг:** `.pre-commit-config.yaml`.

**Текущие хуки:**
- **pre-commit:** ruff (lint+fix), ruff-format, gitleaks, bandit, trailing-whitespace, end-of-file-fixer, check-yaml, check-toml, check-json, check-merge-conflict, check-added-large-files (500KB), check-case-conflict, mixed-line-ending (→LF), debug-statements
- **pre-push:** pyright, sentrux-check, pip-audit
- **Глобально:** `exclude: '^\.claude/'` — seed/тулинг не линтится
- **Опционально (документировано):** interrogate, vulture, radon

**Установка:**
```bash
uv run pre-commit install                       # pre-commit hooks
uv run pre-commit install --hook-type pre-push  # pre-push hooks
```

**Ручной запуск:**
```bash
uv run pre-commit run --all-files
```

---

## 4. Visualization — диаграммы из кода

Четыре инструмента, по убыванию частоты использования:

| Инструмент | Назначение | Запуск / VS Code ext |
|---|---|---|
| **Mermaid** | Текстовые диаграммы в Markdown (C4, sequence). Файлы `docs/diagrams/*.mmd`. | `bierner.markdown-mermaid` |
| **pyreverse → PlantUML** | UML классов из Python-кода. | `uv run pyreverse -o puml -p MyApp <package> -d docs/diagrams/classes/`; ext `jebbs.plantuml` |
| **pydeps** | Граф импортов модулей (требует Graphviz в PATH). | `uv run pydeps <package> -o docs/diagrams/deps/graph.svg --cluster --max-bacon 2 --no-show` |
| **Draw.io** | Ручная редактировка `.drawio.svg` прямо в VS Code; импорт PlantUML. | ext `hediet.vscode-drawio` |

---

## 5. Automation — Makefile

**Что делает:** единая точка входа для всех операций.

**Файл:** `Makefile` в корне проекта.

**Targets:**

| Target | Что делает |
|--------|-----------|
| `make install` | uv sync + pre-commit install |
| `make check` | ruff + pyright |
| `make test` | pytest с coverage |
| `make gate` | check + test (полный gate) |
| `make format` | автофикс ruff |
| `make help` | справка |

> Дополнительные цели (`diagrams`, `clean`, `stats`) — опциональны; если нужны, добавь в `Makefile` ссылками на скрипты из `scripts/`.

**Зачем нужен:** заменяет 10+ ручных команд одной `make gate`.

---

## 6. Base Layer — фундамент

### Python 3.11+

Минимальная поддерживаемая версия — 3.11 (для `tomllib` в стандартной библиотеке).
В `pyproject.toml`: `requires-python = ">=3.11"`. На практике `uv sync` выберет последнюю установленную (часто 3.12 или 3.13).

### uv — пакетный менеджер

**Что делает:** замена pip + virtualenv + pip-tools. В 10-100x быстрее.

**Команды:**
```bash
uv sync --group dev --group diagrams   # установить зависимости
uv add --group dev <package>           # добавить пакет
uv run <command>                       # запустить в venv
uv lock                                # обновить lock-файл
```

**Конфиг:** `pyproject.toml` (стандарт PEP 621) + `uv.lock`.

### Ollama — локальный LLM-runtime

**Что делает:** запускает embedding-модели для qex локально (без OpenAI API).

**Модели:**
- macOS: `qwen3-embedding:8b` (4096-dim, мощнее)
- Windows: `qwen3-embedding:4b` (2560-dim, легче)

**Запуск:** `ollama serve` (фоном). qex стучится на `http://localhost:11434`.

### Node.js — для Context7

**Что делает:** требуется для запуска `npx ctx7`.

**Установка:** один раз на машину, не нужен в проекте.

### Git — VCS

**Конфиг проекта:**
- `.git/hooks/commit-msg` — валидация trailers (`scripts/validate_commit/validate_commit.py`, ставится `claude-kit new`)
- `.git/hooks/pre-commit` — запуск pre-commit framework (ruff)
- `.git/hooks/pre-push` — pyright (опц.)
- `.claude/commit-layers.txt` — whitelist для `Layer:` trailer (пустой → Layer optional)
- `.claude/COMMIT_GUIDE.md` — TL;DR + полная справка по commit-формату (см. `<details>` блок там)
- `.claude/protected-branches` — список веток где `git commit` блокируется хуком `protect-branch.sh`

</details>
