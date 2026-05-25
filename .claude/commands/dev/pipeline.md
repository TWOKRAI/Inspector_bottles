---
description: Полный цикл разработки одной командой — plan → implement → test → review → ship (с failure-recovery через debugger)
disable-model-invocation: true
---

Автоматический полный цикл. Director управляет каждым этапом. Явные петли failure-recovery через `debugger` и эскалация в `teamlead`.

## Алгоритм

### 1. Планирование
Запусти агента **manager** (Sonnet):
- Передай задачу: $ARGUMENTS
- Получи план с Task X.Y в `plans/` (slug-конвенция: kebab-case, `<домен>-<суть>`, max 40 симв.)
- Убедись что план содержит обязательный frontmatter (Slug, Дата, Статус, Ветка)
- Сделай коммит плана: `docs(plans): создать план <slug>`
- Создай ветку: `git checkout -b <type>/<slug>` (feat/fix/refactor/docs)
- Обнови поле `Ветка:` в плане, amend коммит
- Покажи пользователю краткое резюме плана + имя ветки и спроси подтверждение

### 2. Реализация (Contract-first TDD: interface → red → green → refactor)

Для каждой Task X.Y из плана — **порядок обязателен**. Развилка по полю `Module contract:` из ТЗ:

| Module contract | Этапы 2 |
|---|---|
| `new-full` / `new-lite` | **2-INTERFACE → 2-RED → 2-GREEN → 2-REFACTOR** |
| `public-api-change` | **2-INTERFACE (правка) → 2-RED → 2-GREEN → 2-REFACTOR** |
| `impl-only` / `n/a` | **2-RED → 2-GREEN → 2-REFACTOR** (interface не трогается) |

**Почему такой порядок** (не бюрократия): без формального контракта-в-коде тест опирается на пересказ ТЗ — реализация и тест расходятся, потому что каждый интерпретирует ТЗ по-своему. С interface.py в коде у tester и developer **общая ground truth** (Protocol + Pre/Post). Без RED-первого агент-implementer подгоняет тесты под сломанный код — Pocock: «модель пишет код с ошибкой → пишет тест, подтверждающий это неверное поведение → подгоняет тест под свой сломанный код. Это **алгоритмическая оптимизация**, не злой умысел». Контракт-в-коде + RED-первым = двойная структурная защита.

**2-INTERFACE — формальный контракт ПЕРВЫМ** (только для `new-*` / `public-api-change`).
Запусти **developer** (Sonnet) или **teamlead** (Opus, если Senior+) с активным skill `module-contract`:
- Создаёт `interface.py` (full) или module docstring (lite) с `Protocol`/`ABC` + DbC: `Pre:`/`Post:`/`Invariants:` для каждой публичной функции
- README модуля: Purpose / Public API / Boundaries / Stability — **без** Usage examples на этом шаге (примеры = contract tests из 2-RED, не дублируем)
- Имплементации ещё нет — `_impl/` пустой или содержит только `raise NotImplementedError`
- Коммит: `feat(<scope>): interface for Task X.Y` + `Refs: plans/<slug>.md`. Layer: `interface` (если в commit-layers.txt).

**2-RED — tester пишет failing-тест от контракта.**
Запусти агента **tester** (Sonnet) в режиме `MODE: red` (передай через header первых строк промпта — см. `agents/company/tester.md` → "How the orchestrator passes parameters"):
- Передай: путь к `interface.py` (или module docstring) из 2-INTERFACE + acceptance criteria из Task
- Tester читает **только** `interface.py` + Pre/Post в docstring, **не читает** `_impl/`. Если impl-only Task (нет 2-INTERFACE) — читает существующий контракт + спек.
- Tester пишет минимальный тест на одну Pre/Post строку (один тест = одна assertion)
- Tester запускает тест и **демонстрирует**, что он fails:
  - Для `new-*`: `NotImplementedError` (из заглушки в `_impl/`) или `AttributeError` (если impl ещё нет)
  - Для `public-api-change`/`impl-only`: `AssertionError` показывающий wrong output
  - Не годится: `ImportError` / `SyntaxError` (setup сломан, фикси test setup)
- Если тест passes → STOP. Тест неверен (тестирует текущее поведение, не желаемое). Переписать.
- Коммит: `test(<scope>): failing test for Task X.Y` + `Refs: plans/<slug>.md`

**2-GREEN — developer/teamlead пишет минимальную реализацию.**
- Если уровень Senior/Senior+ → запусти **teamlead** (Opus)
- Если уровень Middle/Middle+ → запусти **developer** (Sonnet)
- Передай: путь к `interface.py` + путь к failing-тесту (агент **читает оба**, не угадывает контракт)
- Цель — **минимальный код в `_impl/`, чтобы failing-тест прошёл и Pre/Post из interface соблюдены**. Никакой over-engineering под будущие сценарии.
- Агент **не правит** `interface.py` и failing-тест. Если контракт оказался неверен — это сигнал переделать ТЗ в плане + вернуться к 2-INTERFACE, **не** подогнать тест/импл.
- Коммит: `feat(<scope>): impl for Task X.Y` + `Refs: plans/<slug>.md`. Обнови статус `[PENDING]` → `[DONE]`.

**2-REFACTOR (опц.) — если 2-GREEN оставил очевидный долг.**
- Если реализация уродлива но проходит тест → `developer` чистит в том же контексте, тесты остаются зелёными после каждой правки.
- Контракт (`interface.py`) **не трогается** — это меняет публичный API, должно идти через `public-api-change` Task.
- Skip если код и так чистый.

### 3. Regression — tester прогоняет полный suite

Запусти агента **tester** (Sonnet) в режиме `MODE: regression` (передай через header первых строк промпта):
- Цель: проверить, что 2b/2c **не сломали соседний код** (не Task-acceptance — те уже зелёные из 2a).
- Прогон: `pytest` весь модуль/слой + relevant integration tests.
- Если PASS → шаг 4 (ревью)
- Если FAIL:
  - **Итерация 1 (FAIL)**: запусти **debugger** (Sonnet) с failing-тестом и стеком → либо debugger фиксит в scope, либо выдаёт диагноз → `developer`/`teamlead` применяет фикс → tester retry regression
  - **Итерация 2 (повторный FAIL)**: снова debugger + developer → tester retry
  - **Итерация 3 (всё ещё FAIL)**: **СТОП**, эскалируй в **teamlead** (Opus) — либо ТЗ неадекватно, либо нужен пересмотр архитектуры

### 4. Ревью
Запусти агента **reviewer** (Opus):
- Передай: `git diff main...HEAD` + план + acceptance criteria
- Если APPROVED → шаг 5 (ship)
- Если CHANGES REQUESTED:
  - **Итерация 1**: `developer`/`teamlead` применяет правки → reviewer повторный review
  - **Итерация 2** (последняя): `developer`/`teamlead` финальный шанс → reviewer
  - **Итерация 3**: **СТОП**, эскалация в **teamlead** (Opus) для пересмотра ТЗ или архитектуры

### 5. Документация (опционально)
Если задача затрагивает архитектуру:
- Обычная документация (docstrings, README) → **docs-writer** (Haiku)
- ADR / ARCHITECTURE.md / migration guide → **tech-writer** (Sonnet)

### 6. Ship
Выполни `/ship`:
- validate → тесты → линтер
- Покажи итоговый diff
- Предложи commit message в формате Conventional Commits + trailers
  (`Why:`, `Layer:`, `Refs:` — **обязательно** если есть файл плана для текущей ветки, + опц. `Risk:` / `Reversible:` / `Tested:` / `Rejected:`).
  Полный гайд: `.claude/COMMIT_GUIDE.md`. Валидация: `scripts/validate_commit/validate_commit.py`.
- Если все Task в плане = [DONE] → предложи закрыть план (Status: DONE, отдельный коммит `docs(plans): закрыть <slug>`)
- Спроси разрешение на push

## Failure-recovery граф

```
                  ┌─ new-* / public-api-change ─→ INTERFACE (Protocol+DbC) ─┐
plan → (developer)│                                                          │
                  └─ impl-only / n/a ───────────────────────────────────────→┴→ tester(RED) → impl(GREEN) → [refactor] → tester(regression)
                                                                                                                       ↓ PASS  ↓ FAIL
                                                                                                                       review  debugger → impl [fix] → tester (retry)
                                                                                                                                       ↓ FAIL (итерация 2)
                                                                                                                                       debugger → impl → tester
                                                                                                                                           ↓ FAIL (итерация 3)
                                                                                                                                           ESCALATE → teamlead (пересмотр)

review → [APPROVED] → docs? → ship
review → [CHANGES] → impl → tester(regression) → review (итерация 2)
                ↓ CHANGES (итерация 3)
                ESCALATE → teamlead (пересмотр ТЗ/архитектуры)
```

## Правила

- Между этапами показывай пользователю краткий статус
- **Максимум 2 итерации** на каждой петле (test-fix-test, review-fix-review) — на 3-й эскалация в **teamlead**
- debugger вызывается автоматически на первом FAIL от tester (не ждать ручного /debug)
- Если задача явно Senior+ → сразу teamlead на implementation (не developer)
- Если архитектурное изменение — reviewer проверяет, что есть запись в `DECISIONS.md` (или вызван tech-writer)

Задача: $ARGUMENTS
