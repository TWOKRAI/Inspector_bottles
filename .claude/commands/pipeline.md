---
description: Полный цикл разработки одной командой — plan → implement → test → review → ship (с failure-recovery через debugger)
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

### 2. Реализация
Для каждой Task X.Y из плана (по порядку, с учётом зависимостей):
- Если уровень Senior/Senior+ → запусти **teamlead** (Opus)
- Если уровень Middle/Middle+ → запусти **developer** (Sonnet)
- Передай полное ТЗ задачи, пути файлов, acceptance criteria
- Передай путь к файлу плана: агент **обязан** указать `Refs: plans/<slug>.md` (или phase-файл) в коммите
- Убедись что агент сделал коммит с `Refs:` trailer
- Обнови статус задачи в плане: `[PENDING]` → `[DONE]` (допустимо в том же коммите)

### 3. Тестирование
Запусти агента **tester** (Sonnet):
- Передай: какие модули/файлы были изменены + acceptance criteria из плана
- Если тесты PASS → шаг 4 (ревью)
- Если тесты FAIL:
  - **Итерация 1 (FAIL)**: запусти **debugger** (Sonnet) с failing-тестом и стеком → либо debugger фиксит в scope, либо выдаёт диагноз → `developer`/`teamlead` применяет фикс → tester retry
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
  Полный гайд: `docs/claude/COMMIT_GUIDE.md`. Валидация: `scripts/validate_commit/validate_commit.py`.
- Если все Task в плане = [DONE] → предложи закрыть план (Status: DONE, отдельный коммит `docs(plans): закрыть <slug>`)
- Спроси разрешение на push

## Failure-recovery граф

```
plan → implement → test → [PASS] → review → [APPROVED] → docs? → ship
                        ↓ FAIL
                        debugger → implement [fix] → test (retry)
                            ↓ FAIL (итерация 2)
                            debugger → implement → test
                                ↓ FAIL (итерация 3)
                                ESCALATE → teamlead (пересмотр)

                  review → [CHANGES] → implement → test → review (итерация 2)
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
