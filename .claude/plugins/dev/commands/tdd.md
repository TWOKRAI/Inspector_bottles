---
description: Focused contract-first RED → GREEN → [REFACTOR] loop for one unit (TDD) — standalone extract of /dev:pipeline §2
---

Узкий **TDD-цикл для одного юнита/поведения**: **RED → GREEN → [REFACTOR]**. Это самый
тонкий из трёх режимов реализации — без планирования (manager), без обязательной
INTERFACE-ступени, без полного regression-прогона и review-петли.

**Где он в ряду команд:**
- `/dev:pipeline` — полный цикл (plan → implement → test → review → ship).
- `/dev:implement` — одна Task X.Y из плана по contract-ветке (`new-*` → INTERFACE→RED→GREEN),
  с Refs-трассировкой.
- `/dev:tdd` (эта) — одна функция/поведение, test-first, когда контракт уже есть
  (`impl-only`) или нужен быстрый красный→зелёный без церемоний плана.

Входные данные: $ARGUMENTS — что покрыть (функция/метод + желаемое поведение / acceptance).
Если $ARGUMENTS пуст:
> Укажи юнит и поведение: `/dev:tdd <функция> должна <поведение>` или
> `/dev:tdd tests/unit/test_x.py::test_y — <ожидаемое>`

## Цикл

**RED** — запусти **tester** (Sonnet) в `MODE: red`. Параметры передаются заголовком первых
строк промпта (см. `agents/tester.md` → "How the orchestrator passes parameters"): минимум
`MODE: red`, `TASK:`, и `INTERFACE:`/`MODULE_CONTRACT:` если контракт-в-коде есть.
- Один failing-тест на **одну** Pre/Post-строку (или один acceptance-критерий, если формального
  контракта нет — tester это пометит в отчёте).
- Tester читает **только** контракт/спек, **не** `_impl/`, и **демонстрирует** падение с нужным
  типом ошибки (`AssertionError` для `impl-only`; `NotImplementedError`/`AttributeError`, если
  символа ещё нет). `ImportError`/`SyntaxError` = сломан setup, чини его, не засчитывай как RED.
- Если тест **проходит** → тест неверен (тестирует текущее поведение, не желаемое), переписать.
- Коммит: `test(<scope>): failing test for <unit>` (+ `Refs:`, если для slug есть план).

**GREEN** — запусти **developer** (Sonnet) или **teamlead** (Opus, если Senior+):
- Передай путь к RED-тесту (и к `interface.py`, если есть) — агент **читает**, не угадывает контракт.
- **Минимальная** реализация в `_impl/`, чтобы RED-тест прошёл и Pre/Post соблюдены. Без
  over-engineering под будущее.
- Агент **не правит** RED-тест и контракт под сломанный код (анти-cheat). Неверный контракт →
  назад к `manager`/INTERFACE, не подгонка.
- Коммит: `feat(<scope>): impl for <unit>` (+ `Refs:`).

**REFACTOR** (опц.) — если GREEN оставил очевидный долг: чистка в том же контексте, тесты
зелёные после каждой правки; публичный контракт не трогается.

**Канонический алгоритм каждого этапа** (anti-cheat-обоснование Pocock, точные коммит-сообщения,
типы RED-ошибок по ветке контракта, failure-recovery) — `/dev:pipeline` §2 (single source of
truth). Не дублируем здесь — при сомнении читай его.

## Когда вызывать

- Нужна test-first дисциплина на **одном** юните прямо сейчас, без полного плана/пайплайна.
- Багфикс по схеме «сначала тест, воспроизводящий баг → потом фикс» (`impl-only`).
- Контракт (`interface.py` / docstring) уже существует — нужен только красный→зелёный.

## Когда НЕ вызывать

- Новый публичный модуль (нужна INTERFACE-ступень) → `/dev:implement` (ветка `new-*`).
- Несколько связанных Task / нужен review и regression → `/dev:pipeline`.
- Конфиг / docs / dep-bump (`n/a` — TDD неприменим) → правь напрямую.
- Диагностика падающего теста с неочевидной причиной → `/dev:debug` (skill `systematic-debugging`),
  а не «писать новый тест».

## Refs-трассировка

Если для текущего slug есть план (`plans/YYYY-MM-DD_<slug>.md` или `.../phase-N.md`) — каждый
этапный коммит несёт trailer `Refs: <точный путь к плану>` (как в `/dev:implement` §3). Нет плана
(быстрый юнит вне плановой работы) — не блокируй, но предупреди пользователя.

Юнит: $ARGUMENTS
