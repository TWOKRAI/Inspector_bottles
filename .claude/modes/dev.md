# Dev Mode — Команда разработки

Загружается при задачах: написать код, реализовать фичу, исправить баг, рефакторинг, миграция, тесты, ревью, документация к коду.

> **Перед стартом** прочитай `.claude/modes/_stack.md` — там стек, слои, конвенции конкретного проекта.

## Pipeline

```
spec-writer → manager → developer/teamlead → tester → (debugger on FAIL) → reviewer → ship
```

Скилл `/pipeline` прогоняет цепочку целиком с failure-recovery через debugger.

## Состав команды (`.claude/agents/company/`)

| Агент | Модель | Skill | Когда вызывать |
|-------|--------|-------|----------------|
| **spec-writer** | Sonnet 4.6 | `/spec`, `/spec-sync` | Живое продуктовое ТЗ — с точки зрения пользователя |
| **manager** | Sonnet 4.6 | `/plan` | Декомпозиция этапа → Task X.Y с уровнями сложности. НЕ пишет код |
| **developer** | Sonnet 4.6 | `/implement` | Типовая реализация Task по ТЗ (Middle/Middle+). Код + smoke-test + коммит |
| **teamlead** | Opus 4.6 | Agent tool | Senior+: архитектура, рефакторинг, интеграция. Эскалация 3-й итерации ревью/отладки |
| **tester** | Sonnet 4.6 | `/test` | Pytest по acceptance criteria из ТЗ. НЕ меняет логику |
| **debugger** | Sonnet 4.6 | `/debug` | Воспроизведение → гипотезы → root cause. Чинит в scope или выдаёт диагноз |
| **investigator** | Opus 4.6 | Agent tool | Read-only диагностика cross-module проблем. Не пишет код, выдаёт отчёт |
| **reviewer** | Opus 4.6 | `/review` | Full review (10+ файлов, архитектура, безопасность). Max 2 итерации — далее эскалация в teamlead. НЕ пишет код |
| **docs-writer** | Haiku 4.5 | `/docs` | Простая док: docstrings, README модуля, STATUS.md |
| **tech-writer** | Sonnet 4.6 | Agent tool | Сложная док: DECISIONS.md (ADR), ARCHITECTURE.md, MIGRATION_*.md, RFC-*.md |

## Граничные правила

- **developer vs teamlead** — teamlead для архитектуры/рефакторинга (Opus); developer для типовой реализации (Sonnet). Если не уверен — developer
- **debugger vs investigator** — debugger чинит в scope (1-5 строк); investigator read-only диагностирует cross-module / архитектурные проблемы
- **reviewer vs teamlead** — reviewer только читает и указывает; teamlead пишет код (express review ≤3 файлов или Senior+ implementation)
- **docs-writer vs tech-writer** — ADR / ARCHITECTURE / MIGRATION / RFC → tech-writer; всё остальное → docs-writer
- **3 итерации — стоп** — reviewer не даёт апрув → teamlead эскалация; debugger не нашёл root cause за 3 гипотезы → investigator или teamlead эскалация
- **Параллельное делегирование** — при независимых подзадачах вызывай агентов в одном сообщении (несколько Agent tool calls), не последовательно

## Module Design Discipline (contract-first)

При создании нового **публичного** модуля — следуем contract-first: модуль рождается как пара «контракт + тесты-примеры», реализация пишется после.

| Уровень | Когда | Артефакты |
|---------|-------|-----------|
| **full** | пакетный модуль (≥3 файла или ≥2 публичных класса) | `README.md` + `__init__.py` (`__all__`) + `interface.py` (Protocol + DbC) + `_impl/` + `tests/contract/test_<module>.py` |
| **lite** | однофайловый модуль с публичным API | `<module>.py` с module docstring (Purpose/API/Stability) + `__all__` + DbC в публичных функциях + `tests/contract/test_<module>.py` |
| **none** | модуль приватный (`_*`) или < 50 строк или без `__all__` | дисциплина не применяется |

**Design by Contract** — pre/post/invariants в docstring (соглашение, без `icontract`/`deal`). Каждая Pre/Post строка покрыта хотя бы одним given/when/then тестом в `tests/contract/`.

**Skill `module-contract`** auto-invokes при намерении создать модуль и даёт inline-примеры структуры + чек-листы.

**Reviewer** проверяет соответствие на PR через специализацию **Module Contract Compliance** (см. `reviewer.md`). Activation/skip правила и MCP-routing описаны там.

**Stability marker** — каждый модуль декларирует уровень в README или module docstring:
`**Stability:** contract` (full) / `lite` / `partial` / `legacy`. Legacy → доводится до `contract` или `lite` при первом существенном касании.

## Типовые сценарии

```
Задача средней сложности         →  /pipeline
Новая фича — отдельными шагами   →  /plan  →  /implement  →  /test  →  /review  →  /ship
Архитектурное решение / рефактор →  teamlead через Agent tool (без skill-обёртки)
Падающий тест / регрессия        →  /debug
Cross-module архитектурный баг   →  investigator через Agent tool
ADR (architectural decision)     →  /adr <title>  (обёртка над tech-writer)
Migration guide / ARCHITECTURE   →  tech-writer через Agent tool
Живое ТЗ                         →  /spec  → пользователь редактирует → /spec-sync
Быстрая проверка диффа           →  /ship  (тесты + линтер + diff review)
Проверка здоровья системы        →  /doctor (MCP + agents + hooks + indexes + plans)
Состав команды                   →  /team
```

## Skills routing — когда оркестратор зовёт скилл

Скиллы дополняют команды и агентов поведенческими паттернами. Когда уместно вызвать:

- **Перед `/plan`, если идея размыта** → `brainstorm` (2-4 distinct approaches с trade-offs).
- **Перед `/implement` в незнакомой области кода** → `zoom-out` (карта модулей через graphify/sentrux/codegraph).
- **План кажется хрупким** → `grill-me` (relentless interview по веткам решений).
- **State/UI sanity check до коммита** → `prototype` (LOGIC для state-machine, UI для веб-вариаций).
- **Перед `/ship` / финальным "готово"** → `verify-done` (architectural sanity: sentrux + codegraph + playwright если веб).
- **При "сделай кратко", "less tokens"** → `caveman` (compression фильтр всей сессии).

## Правила координации

Координатор (Opus) НЕ пишет код сам, если задача делегируется. Роли:
- Opus — читает ТЗ пользователя, планирует стратегию, делегирует, проверяет результат агентов
- Sonnet-агенты — heavy lifting в своих контекстных окнах (developer, tester, manager, debugger)
- Opus-агенты — критические решения (reviewer, teamlead, investigator)

Исключение: если задача тривиальная (<30 строк, один файл) — координатор может сделать сам без делегирования.

## Plans hierarchy

Где хранятся планы — см. `.claude/modes/_stack.md` (section "Plans"). Типовые шаблоны:

- **Single root:** `plans/<slug>.md` (простой проект)
- **By scope:** `apps/{app}/plans/` (per-app in monorepo), `projects/{slug}/plans/` (per-project in multi-zone repo)

Manager при `/plan` выбирает правильное место по контексту задачи и `_stack.md`.
