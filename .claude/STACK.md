# STACK — Полный стек инструментов разработки

Описание всех инструментов в проекте: что делает, зачем нужен, как использовать.
Структурировано по слоям — от агента до системных утилит.

---

## Карта стека

```
┌─────────────────────────────────────────────────────────────┐
│                  AGENT LAYER (Claude Code)                  │
│  Агенты + slash-команды + хуки + skills                     │
└─────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────┐
│                    MCP SERVERS (3 шт.)                      │
│  qex — поиск кода │ sentrux — архитектура │ context7 — доки │
└─────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────┐
│                     QUALITY GATES                           │
│  ruff │ mypy │ bandit │ pytest-cov │ pre-commit             │
└─────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────┐
│                    VISUALIZATION                            │
│  Mermaid │ PlantUML (pyreverse) │ pydeps │ Draw.io          │
└─────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────┐
│                     AUTOMATION                              │
│  Makefile │ scripts/ │ pre-commit hooks                     │
└─────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────┐
│                    BASE LAYER                               │
│  Python 3.12 │ uv │ git │ VS Code │ Ollama │ Node           │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Agent Layer — Claude Code

### Что это
**Claude Code** — CLI и IDE-расширение для AI-агента Anthropic. Понимает кодовую базу,
выполняет multi-step задачи, использует MCP-серверы и встроенные инструменты.

### Конфигурация — папка `.claude/`

| Подпапка | Что внутри |
|----------|------------|
| `agents/company/` | 10 ролей: developer, reviewer, manager, debugger, tester, teamlead, tech-writer, spec-writer, docs-writer, investigator |
| `commands/` | 37 slash-команд (dev, quality, analysis, spec, infra, team) |
| `modes/` | dev.md, spec.md — режимы работы |
| `hooks/` | SessionStart, PreToolUse, PostToolUse, PostCompact |
| `mcp/` | bootstrap.py, конфиги qex/sentrux/context7 |
| `templates/` | Шаблоны pyproject, pre-commit, Makefile, sentrux rules |

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

## 2. MCP Servers — три внешних сервера

### qex — семантический поиск кода

**Что делает:** индексирует кодовую базу, выполняет гибридный поиск (BM25 + dense vectors).
Позволяет агенту находить код по смыслу, а не только по тексту.

**Когда использовать:** «где используется X», «где код, который делает Y», поиск перед рефакторингом.

**Технология:** Ollama (`qwen3-embedding:4b` Win / `:8b` macOS) + Tantivy BM25 + brute-force dense vectors.
Индекс в `~/.qex/`.

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

**Когда использовать:** PySide6.10 API, новая версия Pydantic, миграция, незнакомая библиотека.

**Технология:** SaaS, OAuth, free tier. Установка глобально на машину (`~/.claude.json`).

**Установка:**
```bash
npx -y ctx7 setup --claude
```

**Документация:** [`mcp/context7/README.md`](mcp/context7/README.md)

---

## 3. Quality Gates — проверки качества

### ruff — линтер + форматтер

**Что делает:** заменяет flake8 + isort + black + многие плагины. Очень быстрый (Rust).

**Конфиг:** `[tool.ruff]` в `pyproject.toml` — `target-version = "py312"`, `line-length = 120`.

**Запуск:**
```bash
uv run ruff check .                # lint
uv run ruff check --fix .          # с автофиксом
uv run ruff format .               # формат
```

**В pre-commit:** запускается на каждый commit.

---

### mypy — статический типчекинг

**Что делает:** проверяет аннотации типов в Python-коде. Ловит баги до запуска.

**Стратегия:** **gradual typing** — `ignore_missing_imports = true`, типы добавляются постепенно.

**Конфиг:** `[tool.mypy]` в `pyproject.toml`.

**Запуск:**
```bash
uv run mypy <package> --ignore-missing-imports
```

**В pre-commit:** на **pre-push** (не блокирует каждый commit, но блокирует push).

---

### bandit — security scanning

**Что делает:** статический анализ безопасности. Ловит OWASP-уязвимости: hardcoded passwords,
SQL injection, eval(), небезопасный random, и т.д.

**Конфиг:** `[tool.bandit]` в `pyproject.toml` — исключения для тестов.

**Запуск:**
```bash
uv run bandit -r <package> -c pyproject.toml -q
```

**В pre-commit:** на каждый commit.

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
- **pre-commit:** ruff, ruff-format, bandit, trailing-whitespace, end-of-file-fixer, check-yaml, check-toml, check-merge-conflict, check-added-large-files (500KB), debug-statements
- **pre-push:** mypy (gradual)

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

### Mermaid — текстовые диаграммы

**Что делает:** диаграммы из markdown-текста. Рендерится в VS Code, GitHub, GitLab.

**Использование:** ручные диаграммы — C4 архитектура, sequence-диаграммы flows.

**Файлы:** `docs/diagrams/architecture.mmd`, `docs/diagrams/flows/*.mmd`.

**VS Code extension:** `bierner.markdown-mermaid`.

---

### PlantUML — UML классов

**Что делает:** генерирует UML-диаграммы классов из текстового описания.

**Источник:** `pyreverse` (часть pylint) автоматически генерирует `.puml` из Python-кода.

**Запуск:**
```bash
uv run pyreverse -o puml -p MyApp <package> -d docs/diagrams/classes/
```

**Импорт в Draw.io:** File → Import → PlantUML — можно редактировать визуально.

**VS Code extension:** `jebbs.plantuml` (предпросмотр).

---

### pydeps — граф зависимостей

**Что делает:** строит граф импортов между модулями. Помогает увидеть циклы и сильно связанные кластеры.

**Требует:** Graphviz (`dot` в PATH).

**Запуск:**
```bash
uv run pydeps <package> -o docs/diagrams/deps/graph.svg --cluster --max-bacon 2 --no-show
```

---

### Draw.io — визуальный редактор

**Что делает:** редактирование `.drawio.svg` прямо в VS Code. Импортирует PlantUML.

**Использование:** когда нужно докрутить автогенерированную диаграмму или нарисовать схему руками.

**VS Code extension:** `hediet.vscode-drawio`.

---

## 5. Automation — Makefile

**Что делает:** единая точка входа для всех операций.

**Файл:** `Makefile` в корне проекта.

**Targets:**

| Target | Что делает |
|--------|-----------|
| `make check` | ruff + mypy + bandit |
| `make test` | pytest с coverage |
| `make gate` | check + test (полный gate) |
| `make diagrams` | pyreverse + pydeps |
| `make clean` | удалить Python-кэши |
| `make validate` | scripts/validate.py |
| `make stats` | статистика кода |
| `make help` | справка |

**Зачем нужен:** заменяет 10+ ручных команд одной `make gate`.

---

## 6. Base Layer — фундамент

### Python 3.12

Текущая стабильная версия. Все инструменты совместимы.
В `pyproject.toml`: `requires-python = ">=3.12,<3.13"`.

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
- `.gitmessage` — шаблон commit-сообщений
- `.git/hooks/commit-msg` — валидация trailers
- `.git/hooks/pre-commit` — запуск pre-commit framework
- `.git/hooks/pre-push` — mypy + sentrux

---

## Зависимости между слоями

```
Agent Layer
   ↓ использует
MCP Servers (qex, sentrux, context7)
   ↓ зависят от
Ollama + Node + sentrux бинарь
   ↓ работают над
Кодом, который проверяется
   ↓ через
Quality Gates (ruff, mypy, bandit) + pre-commit
   ↓ запускаются через
Makefile / git hooks
   ↓ работают в
uv venv с зависимостями из pyproject.toml
```

---

## Что когда использовать — cheatsheet

| Задача | Инструмент |
|--------|------------|
| Найти где используется функция/класс | qex (`/qex-status`, `mcp__qex__search_code`) |
| Узнать API библиотеки | context7 |
| Проверить архитектуру | sentrux (`/sentrux-health`) |
| Найти циклы импортов | sentrux DSM (`/sentrux-dsm`) или pydeps |
| Увидеть UML классов | pyreverse → PlantUML |
| Линт + формат | ruff |
| Проверить типы | mypy |
| Security scan | bandit |
| Coverage отчёт | pytest-cov |
| Запустить всё сразу | `make gate` |
| Реализовать задачу | `/plan` → `/implement` → `/review` |

---

## Связанные документы

- [`BOOTSTRAP.md`](BOOTSTRAP.md) — установка с нуля
- [`VSCODE_EXTENSIONS.md`](VSCODE_EXTENSIONS.md) — VS Code расширения
- [`README.md`](README.md) — навигация по `.claude/`
- [`CLAUDE.md`](CLAUDE.md) — конфигурация Claude Code
