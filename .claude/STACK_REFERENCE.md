# STACK — Полный референс

Полные детали по каждому инструменту: что делает, как настраивать, как запускать.
Краткая карта и cheatsheet — [`STACK.md`](STACK.md).

---

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
- `.git/hooks/commit-msg` — валидация trailers (`scripts/validate_commit/validate_commit.py`, ставится `apply-seed.sh`)
- `.git/hooks/pre-commit` — запуск pre-commit framework (ruff)
- `.git/hooks/pre-push` — pyright (опц.)
- `.claude/commit-layers.txt` — whitelist для `Layer:` trailer (пустой → Layer optional)
- `.claude/COMMIT_GUIDE.md` — TL;DR гайд по commit-формату ([`COMMIT_GUIDE_REFERENCE.md`](COMMIT_GUIDE_REFERENCE.md) — полные детали)
- `.claude/protected-branches` — список веток где `git commit` блокируется хуком `protect-branch.sh`

---

## Связанные документы

- [`STACK.md`](STACK.md) — TL;DR с картой и cheatsheet
- [`BOOTSTRAP.md`](BOOTSTRAP.md) — установка с нуля
- [`VSCODE_EXTENSIONS.md`](VSCODE_EXTENSIONS.md) — VS Code расширения
- [`README.md`](README.md) — навигация по `.claude/`
- [`CLAUDE.md`](CLAUDE.md) — canonical instructions
