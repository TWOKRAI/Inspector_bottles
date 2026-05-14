# AI Dev Tooling — улучшение инфраструктуры разработки

**Slug:** `ai-dev-tooling`
**Ветка:** `infra/ai-dev-tooling`
**Статус:** 🟡 В работе
**Создан:** 2026-05-14

---

## Контекст

Текущее состояние: `.claude/` система зрелая (10 ролей, 30+ команд, MCP qex/sentrux), ruff настроен,
pytest работает. Но нет визуализации кода (UML/блок-схемы), type checking, security scanning,
единой точки входа (Makefile), coverage-отчётов.

**Цель:** замкнутый цикл AI-разработки — агент пишет → инструменты проверяют → диаграммы обновляются →
ты правишь схему → агент приводит код → проверяют снова.

---

## Фаза 1 — Makefile + Diagrams-as-Code

**Проблема:** sentrux даёт treemap, но нет редактируемых блок-схем. 20+ скриптов без единой точки входа.

### Task 1.1 — Makefile с основными targets
**Level:** Junior (Sonnet)
**Assignee:** developer
**Goal:** единая точка входа для всех операций
**Files:** `Makefile`
**Steps:**
1. Создать Makefile с targets: `check`, `test`, `gate`, `diagrams`, `clean`
2. Интегрировать существующие скрипты (validate, run_framework_tests, code_stats)
**Acceptance criteria:**
- [ ] `make check` — ruff lint
- [ ] `make test` — pytest
- [ ] `make gate` — check + test + sentrux check
- [ ] `make diagrams` — pyreverse + pydeps (заглушки до установки)
- [ ] `make clean` — удаление __pycache__, .pytest_cache, *.pyc

### Task 1.2 — Структура docs/diagrams/
**Level:** Junior (Sonnet)
**Assignee:** developer
**Goal:** создать каталог для diagrams-as-code
**Files:** `docs/diagrams/README.md`, `docs/diagrams/.gitkeep`
**Steps:**
1. Создать `docs/diagrams/classes/`, `docs/diagrams/deps/`, `docs/diagrams/flows/`
2. README с описанием структуры и командами генерации
**Acceptance criteria:**
- [ ] Директории созданы
- [ ] README описывает workflow

### Task 1.3 — Начальная Mermaid-диаграмма архитектуры
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** C4 Container-level диаграмма в Mermaid
**Files:** `docs/diagrams/architecture.mmd`
**Steps:**
1. Описать основные процессы (SystemLauncher → ProcessManager → Workers)
2. Показать IPC-слой (Message → Router → SharedResources)
3. Показать GUI-слой (frontend_module → PySide6)
**Acceptance criteria:**
- [ ] Диаграмма рендерится в Mermaid Preview
- [ ] Покрывает основные слои архитектуры

---

## Фаза 2 — Quality Gates (pre-commit усиление)

**Проблема:** pre-commit ловит только стиль (ruff), но не типы, не безопасность.

### Task 2.1 — mypy конфигурация
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** добавить type checking в pipeline
**Files:** `pyproject.toml`, `.pre-commit-config.yaml`
**Steps:**
1. Добавить `[tool.mypy]` секцию в pyproject.toml (python 3.12, gradual typing)
2. Добавить mypy хук в pre-commit
3. Добавить mypy в dev-зависимости
**Acceptance criteria:**
- [ ] `mypy` конфиг в pyproject.toml
- [ ] Хук в pre-commit (можно с `--ignore-missing-imports` на старте)
- [ ] mypy в dependency-groups.dev

### Task 2.2 — bandit (security scanning)
**Level:** Junior (Sonnet)
**Assignee:** developer
**Goal:** базовое security scanning
**Files:** `pyproject.toml`, `.pre-commit-config.yaml`
**Steps:**
1. Добавить bandit хук в pre-commit
2. Настроить исключения для тестов
**Acceptance criteria:**
- [ ] Хук bandit в pre-commit
- [ ] Тесты исключены из сканирования

### Task 2.3 — pytest-cov (coverage)
**Level:** Junior (Sonnet)
**Assignee:** developer
**Goal:** coverage-отчёты при запуске тестов
**Files:** `pyproject.toml`
**Steps:**
1. Добавить pytest-cov в dev-зависимости
2. Настроить `[tool.coverage]` секцию
3. Обновить Makefile target `test` для генерации coverage
**Acceptance criteria:**
- [ ] pytest-cov в dependency-groups.dev
- [ ] `make test` показывает coverage-отчёт
- [ ] Конфиг coverage в pyproject.toml

---

## Фаза 3 — Slash-команды для визуализации

### Task 3.1 — /diagrams команда
**Level:** Junior (Sonnet)
**Assignee:** developer
**Goal:** регенерация диаграмм одной командой
**Files:** `.claude/commands/infra/diagrams.md`
**Steps:**
1. Создать команду, вызывающую `make diagrams`
2. Описать workflow: генерация → правка → коммит
**Acceptance criteria:**
- [ ] `/diagrams` запускает генерацию

### Task 3.2 — /arch-review команда
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** комплексный архитектурный обзор
**Files:** `.claude/commands/quality/arch-review.md`
**Steps:**
1. Объединить sentrux health + DSM + test_gaps в один отчёт
2. Добавить секцию с диаграммами
**Acceptance criteria:**
- [ ] `/arch-review` выдаёт единый отчёт

---

## Фаза 4 — Dev-зависимости и документация

### Task 4.1 — Обновить pyproject.toml
**Level:** Junior (Sonnet)
**Assignee:** developer
**Goal:** добавить все новые dev-зависимости
**Files:** `pyproject.toml`
**Steps:**
1. Добавить: mypy, bandit, pytest-cov, pylint (для pyreverse), pydeps
2. Отдельная группа `[dependency-groups] diagrams`
**Acceptance criteria:**
- [ ] Все зависимости добавлены
- [ ] `uv sync --group dev --group diagrams` работает

---

## Рекомендуемые VS Code extensions

- **Draw.io Integration** (`hediet.vscode-drawio`) — редактирование .drawio в VS Code
- **Mermaid Preview** (`bierner.markdown-mermaid`) — рендер .mmd
- **PlantUML** (`jebbs.plantuml`) — рендер .puml
- **Excalidraw** (`pomdtr.excalidraw-editor`) — быстрые наброски
