---
description: Implement one Task per spec with contract-first TDD by default (interface → red → green)
---

Реализуй **одну** Task X.Y из плана (или из $ARGUMENTS) по дисциплине **contract-first TDD**.
Это standalone-вариант шага реализации `/dev:pipeline` §2 — без планирования (manager), полного
regression-прогона и review-петли. Для полного цикла используй `/dev:pipeline`.

Передавай агентам ТОЛЬКО конкретную Task (не весь план), точные пути файлов и acceptance criteria.
Если задача зависит от предыдущей — убедись, что та выполнена.

## 1. Определи контракт задачи (развилка этапов)

Прочитай поле **`Module contract:`** из ТЗ Task (его проставляет `manager` — см.
`agents/manager.md` → "Module contract"). Оно задаёт развилку:

| Module contract | Этапы реализации |
|---|---|
| `new-full` / `new-lite` | **INTERFACE → RED → GREEN → [REFACTOR]** |
| `public-api-change` | **INTERFACE (правка) → RED → GREEN → [REFACTOR]** |
| `impl-only` | **RED → GREEN → [REFACTOR]** (interface не трогается) |
| `n/a` | прямая реализация (config / docs / dep-bump — TDD неприменим) |

Если поле отсутствует (legacy-план, ручной $ARGUMENTS) — **определи ветку сам** по характеру задачи
(новый публичный модуль → `new-*`; правка `interface.py` / `__init__.py` → `public-api-change`;
внутренний фикс без смены API → `impl-only`; не-модульное изменение → `n/a`) и **сообщи выбранную
ветку пользователю** перед началом.

**Канонический алгоритм каждого этапа** (Pre/Post, anti-cheat-обоснование, точные коммит-сообщения,
failure-recovery) — `/dev:pipeline` §2 (single source of truth). Это та же contract→stage таблица;
ниже — оркестрация под standalone-режим.

## 2. Этапы (по выбранной ветке)

**INTERFACE** (только `new-*` / `public-api-change`) — запусти **developer** (Sonnet) или
**teamlead** (Opus, если уровень Senior+) с активным skill `module-contract`: формальный
контракт-в-коде ПЕРВЫМ (`interface.py` для full / module docstring для lite — `Protocol`/`ABC`
+ `Pre:`/`Post:`/`Invariants:` на каждую публичную функцию), README модуля **без** Usage-примеров
(примеры = contract-тесты из RED). Имплементации ещё нет (`_impl/` пуст или `raise NotImplementedError`).
Коммит: `feat(<scope>): interface for Task X.Y` + `Refs:`.

**RED** — запусти **tester** (Sonnet) в `MODE: red`. Параметры передаются заголовком первых строк
промпта (см. `agents/tester.md` → "How the orchestrator passes parameters"): `MODE: red`,
`INTERFACE:`, `MODULE_CONTRACT:`, `TASK:`, `PLAN:`. Tester читает **только** контракт (не `_impl/`),
пишет один failing-тест на одну Pre/Post строку и **демонстрирует** падение с нужным типом ошибки
(`NotImplementedError`/`AttributeError` для `new-*`; `AssertionError` для `public-api-change`/`impl-only`).
Если тест проходит → тест неверен, переписать. Коммит: `test(<scope>): failing test for Task X.Y` + `Refs:`.

**GREEN** — запусти **developer** (Sonnet) или **teamlead** (Opus, если Senior+):
- Передай путь к `interface.py` (если был INTERFACE) **и** путь к RED-тесту — агент **читает оба**, не угадывает контракт.
- Цель — **минимальная** реализация в `_impl/`, чтобы RED-тест прошёл и Pre/Post из interface соблюдены. Без over-engineering под будущее.
- Агент **не правит** `interface.py` и RED-тест. Неверный контракт → назад к INTERFACE / в `manager` на пересмотр ТЗ, **не** подгонка теста под код.
- Коммит: `feat(<scope>): impl for Task X.Y` + `Refs:`. Обнови статус Task `[PENDING]` → `[DONE]`.

**REFACTOR** (опц.) — если GREEN оставил очевидный долг: `developer` чистит в том же контексте, тесты остаются зелёными после каждой правки, `interface.py` не трогается (смена API идёт через отдельный `public-api-change` Task).

Для ветки `n/a` — этапы выше неприменимы: реализуй напрямую (developer/teamlead по уровню), один коммит с `Refs:`.

## 3. Refs-трассировка (plan-driven workflow)

- Определи путь к файлу плана: из $ARGUMENTS или по текущей ветке (`git branch --show-current` → извлеки slug → найди в `plans/`):
  - Single plan: `plans/YYYY-MM-DD_<slug>.md` (ищи через `ls plans/*_<slug>.md`)
  - Multi-phase: `plans/YYYY-MM-DD_<slug>/plan.md` + `phase-N.md` (ищи через `ls -d plans/*_<slug>`)
- Каждый коммит этапа — с trailer `Refs: <путь-к-файлу-плана>` (точный путь, с датой).
  Примеры: `Refs: plans/2026-05-22_auth-rbac.md` или `Refs: plans/2026-05-22_auth-rbac/phase-2.md`.
- Для multi-phase планов: ссылка на конкретный phase-файл (не на `plan.md` метаплан, не на папку).
- Если план не найден (legacy ветка, hotfix, плановый файл без даты) — предупреди пользователя, но не блокируй работу.

## 4. После выполнения

- Проверь, что **каждый** коммит этапа несёт `Refs:` trailer и статус Task в плане обновлён `[PENDING]` → `[DONE]`.
- Напомни про regression-прогон (`/dev:test` в `MODE: regression`) и ревью (`/dev:review`) — в standalone они не запускаются автоматически (это делает `/dev:pipeline`).

Задача: $ARGUMENTS
