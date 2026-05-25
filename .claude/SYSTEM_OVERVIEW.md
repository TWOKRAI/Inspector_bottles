# Система как единый организм

Карта `.claude/`-инфраструктуры этого seed'а: восемь слоёв, кто за что отвечает, как они стыкуются, где намеренные дыры и куда идти за чем. Читать первый раз — за 10 минут получаешь полную картину. Дальше — как индекс для tool routing.

> **Статус:** актуально на 2026-05-20. Дата правится при добавлении новых модулей.

---

## TL;DR — система за 60 секунд

Восемь слоёв. Снизу вверх:

1. **Memory** — `.claude/memory/` git-tracked .md — что система знает между сессиями
2. **Modes** — `dev.md` / `spec.md` / `_stack.md` — контекст-якорь, что читать первым
3. **Agents** — `agents/company/*` — 10 ролей с разными моделями (Opus/Sonnet/Haiku)
4. **Commands** — `commands/*` — 40+ slash-команд, явные точки входа
5. **Skills** — `skills/*` — 6 auto-invoke паттернов поведения
6. **Hooks** — `hooks/*` — реакции на lifecycle-события CC
7. **MCP servers** — `mcp/*` — внешние инструменты с собственным процессом
8. **Observability** — `observability/` — замеры токенов и tool calls

Поток задачи проходит через все слои:

```
идея → brainstorm(skill) → /plan → manager(agent) → /implement → developer(agent)
     → MCP-инструменты (qex, codegraph, ast-grep, ...) → /test → tester(agent)
     → verify-done(skill) → /review → reviewer(agent) → /ship → memory update
                                                              → observability snapshot
```

---

## 1. Архитектура слоёв

### Layer 1: Memory — что система помнит

**Где:** `.claude/memory/MEMORY.md` (индекс) + per-entry `*.md` файлы. Git-tracked.

**Зачем:** общая память между сессиями. Без неё каждая новая сессия начинает с нуля. С ней — агент знает правила, прошлые feedback'и, project-факты.

**Четыре типа записей:**
- `user` — о пользователе (роль, экспертиза, предпочтения)
- `feedback` — корректировки и валидированные решения
- `project` — текущие инициативы, ответственные, дедлайны
- `reference` — указатели на внешние системы (Linear, Grafana и т.п.)

**Override:** native CC хранит в `~/.claude/projects/`, мы переопределяем на `.claude/memory/` ради git-портативности. См. `.claude/CLAUDE.md` → "Memory (OVERRIDE)".

### Layer 2: Modes — контекст-якорь

**Где:** `.claude/modes/`

| Mode | Когда читать |
|------|-------------|
| `dev.md` | Любая разработческая задача — код, тесты, рефакторинг, CI |
| `spec.md` | Работа с product-спеками в `docs/direction/` |
| `_stack.md` | **Каждый раз первым** — стек проекта, layers, конвенции |

Modes — это статичный контекст. Они не выполняются — они **читаются** агентом перед задачей. `_stack.md` — единственный обязательный к правке файл при адаптации seed под проект.

### Layer 3: Agents — роли

**Где:** `agents/company/*`. 10 агентов, каждый со своей моделью и инструментами.

| Агент | Модель | Зона |
|-------|--------|------|
| `manager` | Sonnet | Декомпозиция задачи, ТЗ |
| `teamlead` | Opus | Senior-уровень реализации, архитектура |
| `developer` | Sonnet | Реализация по ТЗ, в scope |
| `tester` | Sonnet | Pytest-тесты по acceptance |
| `reviewer` | Opus | Код-ревью, security, IPC |
| `debugger` | Sonnet | Root-cause для багов |
| `investigator` | Sonnet | Read-only recon перед `/plan` |
| `spec-writer` | Sonnet | Product-спеки |
| `docs-writer` | Haiku | Документация, README |
| `tech-writer` | Sonnet | ADR, ARCHITECTURE.md |

**Threshold rule** (когда какого звать):
- 1–3 файла, <80 строк → агенты не нужны, делает основной thread
- 4–9 файлов → developer → teamlead (express review)
- 10+ файлов / архитектура → manager → developer/teamlead → reviewer
- Полный auto → `/pipeline`

См. `~/.claude/TEAM_REFERENCE.md` для деталей и `agents/_WORKTREE_PATTERN.md` для параллельного запуска.

### Layer 4: Commands — явные точки входа

**Где:** `commands/<namespace>/<name>.md`. Активация: пользователь печатает `/<name>`.

Шесть namespace'ов:

| Namespace | Что внутри |
|-----------|-----------|
| `dev/` | `/plan`, `/implement`, `/test`, `/review`, `/debug`, `/ship`, `/pipeline`, `/plan-status`, `/adr` |
| `spec/` | `/spec`, `/spec-sync` |
| `team/` | `/team`, `/hire`, `/handoff`, `/docs`, `/wrap-up` |
| `memory/` | `/memory:init`, `/memory:status`, `/memory:search` |
| `quality/` | `/sentrux-*` (8 шт), `/qex-*` (3 шт), `/code-stats`, `/test-ratio`, `/lint-agents`, `/lint-settings`, `/arch-review` |
| `infra/` | `/cold-start`, `/clean-cache`, `/diagrams`, `/fw-test`, `/run-proto` |
| `analysis/` | `/todo-inventory` |

Команда = промпт + workflow. Не код. Использует тех агентов и MCP, которых перечислит в своём теле.

### Layer 5: Skills — auto-invoke паттерны

**Где:** `skills/<name>/SKILL.md`. Активация: Claude **сам** решает по `description`, что пора вызвать.

Шесть skills закрывают конкретные failure modes:

| Skill | Closes failure mode |
|-------|---------------------|
| `caveman/` | Многословный вывод когда нужна сжатость |
| `grill-me/` | Поверхностный плана без стресс-теста |
| `zoom-out/` | Правка кода без понимания контекста |
| `prototype/` | Преждевременная фиксация дизайна |
| `brainstorm/` | Прыжок от идеи к плану без рассмотрения альтернатив |
| `verify-done/` | «Тесты зелёные = готово» (не равно) |

Разница со slash command: skill активируется автоматически, slash — явным вводом пользователя.

### Layer 6: Hooks — lifecycle reactions

**Где:** `hooks/`

| Hook | Событие | Что делает |
|------|---------|-----------|
| `core/validate-safe-command.sh` | PreToolUse Bash | Блокирует опасные команды (regex) |
| `core/protect-branch.sh` | PreToolUse Git | Защита main/master от force-push |
| `core/protect-readonly.sh` | PreToolUse Edit/Write | Блокирует правки в read-only путях |
| `core/restore-context.sh` | PostCompact | Восстанавливает навигацию + commit format |
| `core/precompact-context-save.sh` | PreCompact | Заставляет дамп решений в memory ДО компактификации |
| `git/pre-commit-session-log.sh` | pre-commit (git) | Пишет journal в `docs/sessions/YYYY-MM-DD.md` и сам `git add`'ит — попадает в текущий коммит |
| `core/session-end-daily-log.sh` | Stop (CC) | **Fallback** для проектов без pre-commit (по умолчанию выключен) |
| `core/session-health-check.sh` | SessionStart | Проверка чистоты репо, актуальности модели |
| `core/session-plan-status.sh` | SessionStart | Показывает open-plans |
| `core/filter-test-output.sh` | PostToolUse pytest | Чистит шумные pytest-output |
| `python/autoformat-python.sh` | PostToolUse Edit | Ruff format на изменённых .py |
| `python/check-imports.sh` | PostToolUse Edit | Проверка импортов |
| `python/typecheck-changed.sh` | PostToolUse Edit | Pyright на изменённых |

Hooks — **не агенты**. Это shell-скрипты, которые CC выполняет в фоне. Они либо блокируют операцию, либо выводят текст в контекст.

### Layer 7: MCP servers — внешние процессы

**Где:** `mcp/<name>/`. Активация: в проектном `.mcp.json` или user-level `~/.claude.json`.

**Core (документировано в seed, активируется bootstrap'ом):**

| MCP | Уровень | Покрытие |
|-----|---------|----------|
| **qex** | проектный | Семантический поиск (BM25 + dense via Ollama) |
| **sentrux** | проектный | Архитектурный health-gate (DSM, метрики, циклы) |
| **context7** | user-level | Актуальная документация библиотек |

**Optional (документировано, активируется когда надо):**

| MCP | Покрытие | Когда |
|-----|----------|-------|
| **qt-mcp** | PyQt/PySide runtime inspection | GUI-проекты |
| **graphify** | Knowledge graph с визуализацией | Architectural overview |
| **serena** | LSP-symbol операции | Точные refs/rename |
| **codegraph** | Call graph + impact + framework routing | Refactor-heavy projects |
| **github** | Issues/PR/Actions/Projects | GitHub-проекты |
| **ast-grep** | Structural search **и rewrite** на 20+ языках | Codemods, bulk transformations |
| **playwright** | Browser automation (navigate, screenshot, click) | Веб-проекты, verify-done для UI |
| **sequential-thinking** | Externalized chain-of-thought scratchpad | Investigator на 3+ гипотез, teamlead эскалация |

**Routing-карта между MCP** живёт в `.claude/mcp/ROUTING.md` (single source of truth для авторов агентов и verify-скрипта; агенты её **не читают runtime** — у каждого свой самодостаточный routing-блок в `.md`).

**Test-drive:** `/doctor` (slash-command) или `bash .claude/scripts/doctor.sh` — единая проверка здоровья всех слоёв (MCP / configs / routing / indexes / hooks / plans).

### Layer 8: Observability — замеры

**Где:** `observability/`

Три слоя:
- Native OTel (`CLAUDE_CODE_ENABLE_TELEMETRY=1`)
- Docker stack (`claude-code-otel`)
- Lightweight statusline (`ccusage`, `ccstatusline`)

Назначение: дать **измеримый ответ** на вопросы «помогает ли codegraph», «сколько стоит сессия», «какие tool calls дороже всего». До observability эти вопросы решаются на глаз — неправильно.

---

## 2. За что отвечает каждый инструмент — таблица ownership

| Инструмент | Зона ответственности (чёткая граница) | НЕ отвечает за |
|-----------|---------------------------------------|----------------|
| **memory/** | Долговременные правила, feedback, project state | Текущий план сессии (это `plans/`), временный контекст (это modes/) |
| **modes/dev.md** | Универсальный workflow разработки | Стек конкретного проекта (это `_stack.md`) |
| **modes/_stack.md** | Стек, layers, конвенции **этого** проекта | Универсальные правила |
| **manager agent** | Декомпозиция большой задачи на Task X.Y | Не пишет код, не делает review |
| **developer agent** | Реализация одной Task X.Y по ТЗ | Не выходит за scope, не рефакторит соседнее |
| **teamlead agent** | Senior+ реализация, сложная архитектура | Не для тривиальных правок |
| **reviewer agent** | Финальное code review (Opus) | Не пишет код, не запускает тесты |
| **tester agent** | Pytest по acceptance criteria | Не меняет логику приложения |
| **debugger agent** | Root-cause для багов | Не делает feature work |
| **investigator agent** | Read-only recon ДО плана | Не правит файлы |
| **`/plan`** | Создаёт `plans/<slug>.md` + ветку | Не реализует задачу |
| **`/implement`** | Запускает developer на Task X.Y | Не пишет тесты |
| **`/test`** | Запускает tester | Не правит логику |
| **`/review`** | Запускает reviewer | Не реализует правки ревью |
| **`/ship`** | Финальный gate: тесты + lint + ревью diff | Не пушит без явного approval |
| **`/pipeline`** | Полный цикл: plan → implement → test → review → ship | Не магия — последовательность команд |
| **`brainstorm` skill** | Генерация 2–4 опций ДО плана | Не пишет код |
| **`grill-me` skill** | Стресс-тест существующего плана | Не создаёт план с нуля |
| **`verify-done` skill** | Проверка «фикс реально работает» ДО `/ship` | Не запускает тесты |
| **`zoom-out` skill** | Карта модулей и callers перед правкой | Не делает правки |
| **`prototype` skill** | Throwaway prototype для проверки идеи | Не для production-кода |
| **`caveman` skill** | Сжатие ответов на 75% токенов | Не меняет содержание |
| **PreCompact hook** | Заставляет дамп решений в memory ДО компактификации | Не сохраняет сам (это делает агент) |
| **PostCompact hook** | Восстанавливает навигацию ПОСЛЕ компактификации | Не повторяет всё содержимое |
| **validate-safe-command hook** | Блокирует опасный bash (regex) | Не AST-валидация (будущая работа) |
| **pre-commit-session-log hook** | Per-commit запись в `docs/sessions/YYYY-MM-DD.md` (primary с v0.4.0) | Не суммаризация (это `/wrap-up`) |
| **session-end-daily-log hook** | Stop-фоллбэк для проектов без pre-commit | Не суммаризация |
| **qex MCP** | Семантический поиск по коду (intent-based) | Не call graph, не метрики |
| **sentrux MCP** | Архитектурный health, циклы, layer rules | Не поиск, не семантика |
| **graphify MCP** | Knowledge graph + HTML viz | Не call graph функций (это codegraph) |
| **serena MCP** | LSP refs/rename одного символа | Не bulk pattern (это ast-grep) |
| **codegraph MCP** | Function callers/callees/impact + framework routing | Не codemods (это ast-grep), не семантика (это qex) |
| **github MCP** | Issues/PR/Actions/Projects на GitHub | Не локальный git (это shell) |
| **ast-grep MCP** | Pattern search **и rewrite** на 20+ языках | Не scope-aware rename (это serena) |
| **context7 MCP** | Документация внешних библиотек | Не код проекта |
| **observability** | Замер токенов, tool calls, стоимости | Не оптимизация — только видимость |

---

## 3. Coverage matrix — типичная задача → primary tool

| Задача разработчика | Primary | Fallback |
|---------------------|---------|----------|
| «Где определён символ X?» | Grep / serena | qex |
| «Где упоминается X (текстово)?» | Grep | qex |
| «Найди код, который делает что-то похожее на Y» (intent) | qex | graphify |
| «Кто вызывает функцию X?» | **codegraph** | Grep + ручной разбор |
| «Если переименую X, что сломается?» | **codegraph** (impact) | serena (rename) |
| «Переименуй X → Y во всём scope» | serena | ast-grep |
| «Заменить `requests.get` на `httpx.get` в 200 файлах» | **ast-grep** | sed (опасно) |
| «Есть ли циклические зависимости?» | sentrux | graphify |
| «Какие модули без тестов?» | sentrux | глаза |
| «Визуальный обзор архитектуры» | graphify | sentrux |
| «Прочитай актуальную документацию `httpx`» | context7 | WebFetch |
| «Кто закрыл PR #42, что в CI?» | github MCP | shell `gh` |
| «Какой handler обрабатывает POST /api/X?» | codegraph (framework routing) | Grep |
| «Спланировать задачу на 5+ файлов» | manager agent через `/plan` | direct discussion |
| «Реализовать одну подзадачу» | developer agent через `/implement` | direct edit |
| «Стресс-тест плана» | grill-me skill | manual review |
| «Сгенерировать опции перед планом» | brainstorm skill | direct ideation |
| «Проверить что фикс работает» | verify-done skill | manual smoke test |
| «Запустить тесты на изменённых файлах» | typecheck-changed hook (auto) | manual `pytest` |
| «Защититься от `git push --force`» | protect-branch hook (auto) | внимательность |
| «Замерить, помогает ли новый MCP» | observability + 5 smoke-вопросов | глаза (ненадёжно) |
| «Найти стейл-секрет в коде» | TruffleHog (не интегрирован, см. ROADMAP § B.6) | gitleaks (внешний) |

---

## 4. Tool routing decision tree

Для агента в новой сессии — алгоритм выбора инструмента:

```
Задача про код?
├── Знаю точное имя символа / путь?
│   ├── Хочу найти текст → Grep
│   ├── Хочу refs + rename → serena
│   └── Хочу call graph → codegraph
├── Знаю только смысл, не имя?
│   ├── Семантический поиск → qex
│   └── Бульк-паттерн → ast-grep
├── Хочу понять архитектуру?
│   ├── Метрики, циклы, gate → sentrux
│   └── Визуальный граф → graphify
└── Хочу сделать codemod?
    └── ast-grep (всегда --dry-run сначала)

Задача про процесс?
├── Большая задача, 4+ файла → `/plan` → `/implement` → `/test` → `/review` → `/ship`
├── Маленькая правка → прямой edit без агентов
└── Fuzzy идея → `brainstorm` skill → `/plan`

Задача про данные / БД / web / GitHub?
├── GitHub state → github MCP (если включён) / `gh` CLI
├── Postgres → Postgres MCP Pro (см. ROADMAP § D.13 — не в seed)
├── Browser automation → Playwright MCP (см. ROADMAP § D.11 — не в seed)
└── Web docs → context7
```

---

## 5. Gap analysis — что покрыто, что слабо

### Покрыто сильно ✅

- **Workflow дисциплина** — `/plan → /implement → /test → /review → /ship` + threshold rule + 2-iteration limit. Лучше многих kitchen-sink toolkits.
- **Архитектурный gate** — sentrux + sentrux rules в pre-commit. Уникально среди seed'ов.
- **Семантический поиск** — qex с Ollama + BM25. Зрелое.
- **Call graph + impact** — codegraph (только что добавлен). Закрыта историческая дыра.
- **Codemods** — ast-grep (только что добавлен).
- **Memory дисциплина** — git-tracked, типизированная, не централизованная SQLite. Портативно.
- **Commit discipline** — validator + COMMIT_GUIDE + opt-in Layer trailer.

### Покрыто адекватно ⚠️

- **Hooks** — 11 шт, основные lifecycle-события покрыты, но нет TruffleHog (secrets), OSV-Scanner (vuln), AST-bash validator (Dippy).
- **Skills** — 6 шт, базовые failure modes покрыты, но нет `systematic-debugging` (отдельная skill для root-cause workflow).
- **MCP-набор** — 10 шт включая optional, разнообразный, но нет Playwright (browser), Semgrep (SAST), Postgres MCP (БД) — это намеренно opt-in per-project.

### Слабо или не покрыто (намеренно или по списку) ❌

- **Browser automation** — Playwright MCP документирован в ROADMAP § D.11, **не реализован**. Делать когда появится web-проект.
- **SAST на код агента** — Semgrep MCP в ROADMAP § D.12, **не реализован**. Делать когда код агента идёт в прод.
- **БД-MCP** — Postgres MCP Pro / DBHub в ROADMAP § D.13, **не реализован**. Делать при первом БД-проекте.
- **Plugins packaging** — seed не упакован как `.claude-plugin`. Re-eval Q3 2026 (ROADMAP § K).
- **Параллельные агенты** — `isolation: worktree` задокументирован в `agents/_WORKTREE_PATTERN.md`, **не применён**. Применять, когда `/pipeline` пойдёт в параллель.
- **TruffleHog/OSV-Scanner hooks** — в ROADMAP § B.6, **не реализованы**. Делать перед первым прод-релизом.
- **A/B claude-context vs qex** — давний open в ROADMAP § D.1. Сделать через observability/, когда тот будет запущен в проекте.

### Сознательно отклонено (для контекста)

- **agnix** (отклонён 2026-05-19) — заменён `lint_agents.py`
- **Letta / Ralph** — конфликтуют с CC loop
- **claude-mem** (centralized SQLite) — конфликтует с git-tracked memory; opt-in кандидат
- **Snyk MCP** — CVE Feb 2026
- **Codacy / SonarQube** — vendor lock
- **Kitchen-sink toolkits** (rohitg00) — хуже governance, объём ≠ качество

---

## 6. Lifecycle workflow — один поток задачи

Как все слои стыкуются на одной задаче:

```
Пользователь: "хочу X"
     │
     ▼
[brainstorm skill]  ← если идея fuzzy: генерируем 2–4 опции
     │
     ▼
[/plan <task>]      ← manager создаёт plans/<slug>.md + ветку
     │   ├── читает: modes/_stack.md, memory/, CLAUDE.md
     │   └── использует: investigator agent для recon
     ▼
[grill-me skill]    ← опционально: стресс-тест плана
     │
     ▼
[/implement Task X.Y]
     │   ├── developer agent (или teamlead если Senior+)
     │   ├── использует MCP: qex/codegraph/serena/ast-grep по нужде
     │   ├── hooks: typecheck-changed, autoformat, check-imports
     │   └── коммит с trailer "Refs: plans/<slug>.md"
     ▼
[/test]
     │   └── tester agent пишет/запускает тесты по acceptance
     ▼
[verify-done skill] ← фикс реально работает? entry point exercise?
     │
     ▼
[/review]           ← reviewer agent (Opus) даёт правки или approve
     │
     ▼
[/ship]
     │   ├── финальные gate: lint + types + tests + sentrux check
     │   ├── проверяет commit messages (Refs: trailer на месте)
     │   └── НЕ пушит без явного approval
     ▼
[/wrap-up]          ← docs/sessions/YYYY-MM-DD.md + memory update
     │
     ▼
[observability]     ← Grafana: сколько токенов, какие tool calls, $$
```

Hooks тихо работают в фоне на каждом шаге. PreCompact срабатывает, если разговор длинный — сохраняет решения в memory.

---

## 7. Anti-patterns — чего НЕ делать

Полный список в `ROADMAP.md` § J. Кратко:

- **Не превышай потолки:** ≤15 skills, ≤15 hooks, ≤12 агентов
- **Не хукай каждое событие** — спам и фрагментация
- **Не копируй kitchen-sink toolkits** (135 агентов rohitg00) — governance важнее объёма
- **Не используй `--dangerously-skip-permissions`** по умолчанию
- **Не запускай ast-grep rewrite** без `--dry-run`
- **Не давай codegraph и Grep на одну задачу** одновременно — это дублирование, не дополнение
- **Не превращай CLAUDE.md в свалку** — у каждого правила должно быть место (modes / memory / `_stack`)
- **Не пиши новый skill** для разовой задачи — пиши skill только когда триггерил руками ≥3 раза

---

## 8. Maintenance — как поддерживать систему

| Действие | Триггер | Кто делает |
|----------|---------|-----------|
| Добавить новый агент | Triggered ≥5 раз руками типичная задача | через `/hire` + ревью |
| Удалить агента | Не вызывался >месяц | при `/team` ревизии |
| Добавить новый skill | Триггеришь руками ≥3 раз | руками + добавить в `skills/README.md` |
| Удалить skill | Не активировался >месяца + не вспоминаешь зачем | при `/team` ревизии |
| Добавить MCP | Конкретная задача, замер маржи через observability | как opt-in `mcp/<name>/`, документ + snippet |
| Удалить MCP | Замер показал маржу <5% и есть альтернатива | удалить папку + ROADMAP пункт в § H |
| Обновить ROADMAP | После каждого решения «добавить» или «отклонить» | сразу |
| Замерить эффект MCP | Перед/после добавления любого нового tool | observability/ + 5 smoke-вопросов |
| Sync seed с проектами | После HIGH-priority изменений в seed | `sync-back.sh` |

---

## 9. Куда смотреть когда сломалось

| Симптом | Куда |
|---------|------|
| Агент не знает контекст проекта | `modes/_stack.md` заполнен? root `CLAUDE.md` есть? |
| Memory пуст / не подгружается | `.claude/memory/MEMORY.md` существует? Override прописан в `.claude/CLAUDE.md`? |
| `/mcp` показывает failed | `mcp/<name>/SETUP_GUIDE.md` → troubleshooting; проверить конфиг сервера в `SETUP_GUIDE.md` |
| Hook ничего не делает | `.claude/settings.json` → hook включён? путь правильный? executable? |
| Skill не активируется | `description` слишком общий — переписать триггеры конкретнее |
| Slash command "not found" | `commands/<ns>/<name>.md` существует? namespace правильный? |
| `/pipeline` падает на этапе X | Проверить лог агента, фолбэк на debugger через `/debug` |
| Тесты падают после рефакторинга | `/sentrux-diff` показал просадку quality_signal? |
| Слишком много токенов на сессию | Включить observability, посмотреть top tool calls |

---

## 10. Источники и стандарты

- [Claude Code best practices (Anthropic)](https://www.anthropic.com/engineering/claude-code-best-practices)
- [Claude Code hooks reference](https://code.claude.com/docs/en/hooks)
- [Claude Code agents docs](https://code.claude.com/docs/en/agents)
- [Claude Skills docs](https://docs.claude.com/en/docs/agents-and-tools/skills)
- [Model Context Protocol (modelcontextprotocol.io)](https://modelcontextprotocol.io/)
- ROADMAP внутреннего сида: `template/ROADMAP.md`
- Memory rules: системный промпт CC + `.claude/CLAUDE.md` → "Memory (OVERRIDE)"

---

**Last review:** 2026-05-20.
**Next review trigger:** добавление любого нового MCP / skill / hook + раз в квартал плановый.
