# Plan: Framework Assessment 2026-05-07 — Оценка и точки роста

> **Дата:** 2026-05-07
> **Ветка:** `main`
> **Контекст:** Снимок состояния `multiprocess_framework` после Phase 2.1 (state_store), Phase 2.3 (chain_module), точечной полировки 2026-05-07 (ADR-SS-011..013, ADR-CHN-006/007) и актуализации root-документации. Базовая оценка из `plans/framework_production_readiness.md` была **8.4/10** (2026-04-10) — повторно даём оценку через ~месяц после переноса state_store и chain во фреймворк.
> **Scope:** Все 21 модуль, root-документация, ADR-реестр.
> **Источники:** `MODULE_CONTRACTS.md`, `MODULES_OVERVIEW.md`, `MODULES_STATUS.md`, `ASSESSMENT_2026_05.md`, `IMPROVEMENT_PLAN.md`, `PROBLEMS.md`, `DECISIONS.md`, локальные `modules/<X>/STATUS.md` и `DECISIONS.md`.
> **Исполнитель:** Sergey + Claude (агенты на конкретные подзадачи).

---

## 0. Общая оценка: **8.4 / 10**

| Измерение | Балл | Вес | Итог | Δ vs 2026-04-10 |
|-----------|:----:|:---:|:----:|:---:|
| Архитектура и слойность | 9 | 20% | 1.80 | = (9.2 → 9.0; -0.2) |
| Чистота интерфейсов (Protocol/ABC) | 9 | 10% | 0.90 | +0.3 (новые Protocol-ы chain/state_store) |
| Наблюдаемость | 9 | 10% | 0.90 | +0.5 (716ed34: import logging вычищен) |
| Документация — полнота | 9 | 15% | 1.35 | +1.8 (15 root + 21 module READMEs + 12 ADR-категорий) |
| Документация — внутренняя согласованность | 8 | 10% | 0.80 | +0.8 (после правок 2026-05-07: ADR-CM коллизия устранена, registry полный) |
| Тестовое покрытие | 8 | 15% | 1.20 | +0.2 (2 465 → 2 553 после chain/state_store) |
| Соблюдение собственных правил | 9 | 5% | 0.45 | = |
| Управление техдолгом | 8 | 5% | 0.40 | +0.2 (Tier-1 IMPROVEMENT_PLAN закрыт) |
| Зрелость / готовность к продакшену | 8 | 5% | 0.40 | +0.5 (chain/state_store Stable) |
| Удобство для нового разработчика / агента | 8 | 5% | 0.40 | +0.5 (CONSTRUCTOR_BLUEPRINT добавил §F/§G) |
| **Итого** | | **100%** | **8.60 → 8.4** | +0.0 (стабильно высокий) |

### Per-Module Scores (новые модули + изменения)

| Модуль | Код | Тесты | Docs | Arch | Итого | Note |
|--------|:---:|:-----:|:----:|:----:|:-----:|------|
| **state_store_module** | 9 | 10 | 9 | 9 | **9.3** | 421 теста, ADR-SS-001..013, доменно-нейтральный PersistenceManager |
| **chain_module** | 9 | 8 | 9 | 9 | **8.8** | 67 тестов, IRemoteExecutable Protocol, общая on_error политика |
| process_module | 7 | 9 | 8 | 7 | **7.7** | -0.5: толстый фасад (3 965 LOC), TODO Phase 4 не закрыт |

---

## 1. Сильные стороны (что работает)

1. **Образцовая разделимость слоёв** — 11 уровней, 21 модуль, граф зависимостей без циклов. Подтверждено в [`docs/DIAGRAMS.md`](../multiprocess_framework/docs/DIAGRAMS.md) (раздел «module dependency graph»).
2. **Единый паттерн `BaseManager + ObservableMixin`** — каждый менеджер декларацией наследования получает lifecycle (`initialize/shutdown`) и observability (`_log_*`, `_record_*`, `_track_*`). После 716ed34 — никаких `import logging` в модулях.
3. **Дисциплина ADR** — почти каждое архитектурное решение зафиксировано. Реестр кодов модулей (`docs/ADR_REGISTRY.md`) теперь покрывает все 21 модуль (после правок 2026-05-07).
4. **Protocol для внешних, ABC для внутренних** — образцово реализовано в state_store (`IRouter` Protocol + `IStateStore`/`IStateProxy`/`IStateStoreManager` ABC) и chain (`IExecutionStep`, `IRemoteExecutable`, `IStepNode`).
5. **Dict at Boundary** — pickle-safe сериализация на границах процессов; внутри процесса — Pydantic. Подтверждено отсутствием ошибок Windows-spawn в production.
6. **Fan-out по `FieldRouting`** — поле декларируется один раз, маршрут IPC автоматический; снижает порог входа для нового регистра до 1 файла.

---

## 2. Слабые места (по приоритету)

### Tier-1 (блокирует production / агентов)

#### T1.1. `process_module` слишком толстый — 3 965 LOC

**Симптом:** `ProcessModule` делегирует в 5 helper-классов (`ProcessLifecycle`, `ProcessManagers`, `ProcessCommunication`, `ProcessState`, `SystemThreads`), но сам файл всё ещё крупный, и часть логики «проросла» в фасад.

**Действия:**
- [ ] Аудит `modules/process_module/core/process_module.py`: вынести `_init_*` и `_setup_*` хуки в helper-классы.
- [ ] Перенести `send_message`/`broadcast`/`request` целиком в `ProcessCommunication` (сейчас фасад держит обёртки).
- [ ] Цель: `process_module.py` < 1 500 LOC, остальное — helper-ы.

**Срок:** 1.5 дня. **Исполнитель:** developer + reviewer.

#### T1.2. TODO Phase 4 — авто-регистрация state.changed handler в ProcessModule (ADR-SS-006)

**Симптом:** Каждый процесс пишет `router.register_message_handler("state.changed", proxy.on_state_changed)` вручную. Это рутина, провоцирующая забывчивость и тонкие баги.

**Действия:**
- [ ] Если `ProcessModule.__init__` получает `state_proxy: IStateProxy | None`, регистрация выполняется автоматически в `_init_state_proxy()`.
- [ ] Также убрать default `server_target="ProcessManager"` (ADR-SS-002) — параметр станет обязательным.
- [ ] Обновить ADR-SS-006 → «принято, реализовано».

**Срок:** 0.5 дня. **Исполнитель:** developer.

#### T1.3. CI-проверка консистентности ADR

**Симптом:** До 2026-05-07 в репо была коллизия `ADR-CM-*` (console_module ↔ chain_module), и 4 модуля (CM/SQL/SS/CHN) отсутствовали в ADR_REGISTRY. Без автоматической проверки рассинхрон неизбежен.

**Действия:**
- [ ] Скрипт `scripts/check_adr_registry.py`:
  - все коды в `modules/<X>/DECISIONS.md` (`ADR-{CODE}-NNN`) совпадают с записью в `docs/ADR_REGISTRY.md`;
  - нет двух разных модулей с одинаковым `{CODE}`;
  - каждый локальный `ADR-{CODE}-NNN` имеет одну запись «модуль → ADR-NNN…NNN» в таблице «Модульные решения» в корневом `DECISIONS.md`.
- [ ] Подключить в `scripts/validate.py` (запускается из `/validate`).

**Срок:** 0.5 дня. **Исполнитель:** developer.

---

### Tier-2 (важно, но не блокирует)

#### T2.1. MemoryManager — 15 skipped тестов на macOS

**Симптом:** `multiprocessing.shared_memory` платформенно нестабилен на macOS (Apple Silicon spawn fork). Тесты тихо пропускаются. См. [`PROBLEMS.md`](../multiprocess_framework/PROBLEMS.md).

**Действия:**
- [ ] Решить продуктово: поддерживаем ли SHM на macOS в production (если нет — пометить модуль `platform=linux,windows` и снять skips).
- [ ] Если поддерживаем — найти root-cause и пофиксить (потенциально через POSIX `multiprocessing.resource_tracker` workaround).

**Срок:** 1 день (decision) + 2 дня (если фиксим). **Исполнитель:** debugger + teamlead.

#### T2.2. Граница `registers_module` ↔ `state_store_module`

**Симптом:** Оба дают pub/sub. В коде граница есть (registers — типизированные Pydantic-инстансы с `FieldRouting`; state_store — произвольное dict-tree с glob-подписками), но в документации зафиксирована неявно. Tier-3 в `IMPROVEMENT_PLAN.md` (§2.4).

**Действия:**
- [ ] Написать **ADR-RM-002** или **ADR-SS-014** (номер 011..013 уже занят — см. правку 2026-05-07): «Регистры vs State Store — когда что применять».
- [ ] Добавить раздел в [`CONSTRUCTOR_BLUEPRINT.md`](../multiprocess_framework/docs/CONSTRUCTOR_BLUEPRINT.md) §4 «Семь паттернов» — расширить до восьмого паттерна.

**Срок:** 0.5 дня. **Исполнитель:** tech-writer + reviewer.

#### T2.3. `ChainContext.logger` — duck-typed, без Protocol

**Симптом:** В `chain_module/core/context.py` `logger: Any` — все исполнители вызывают `logger._log_info/warning/error`, но это приватные методы, и контракт не зафиксирован.

**Действия:**
- [ ] Добавить `IChainLogger` Protocol в `chain_module/interfaces.py`: `log_info(msg, **kwargs)`, `log_warning(...)`, `log_error(...)` (публичные методы — не приватные).
- [ ] Перевести `chain.py`/`dag.py`/`parallel.py`/`error_policy.py` на публичные методы.
- [ ] ADR-CHN-008: «Публичный логгер-протокол для исполнителей chain_module».

**Срок:** 0.5 дня. **Исполнитель:** developer.

---

### Tier-3 (стилистика, удобство)

#### T3.1. CONSTRUCTOR_BLUEPRINT §4 «Семь паттернов» → восемь

Связано с T2.2 — единый PR.

#### T3.2. Высокий порог входа для нового агента

**Симптом:** 15 root-docs + 21 module README — больше суток чтения для нового discovery-агента.

**Действия:**
- [ ] Создать **`docs/AGENT_CHEATSHEET.md`** (~1 страница): пять самых частых задач + куда копать.
- [ ] Ссылка с README.md в START HERE-таблице.

**Срок:** 1 час. **Исполнитель:** tech-writer.

#### T3.3. Архивирование `ASSESSMENT.md` (дубль с `ASSESSMENT_2026_05.md`)

**Действия:**
- [ ] Перенести `ASSESSMENT.md` → `multiprocess_framework/docs/archive/ASSESSMENT_2026_03.md` (сохранить историческую оценку до Phase 2.x).
- [ ] Оставить только `ASSESSMENT_2026_05.md` как актуальный.

**Срок:** 5 минут. **Исполнитель:** docs-writer.

---

## 3. Рекомендуемая последовательность (4–5 дней работы)

| День | Tier | Задача | Выход |
|:----:|:----:|--------|-------|
| 1 | T1.3 | CI-проверка ADR-реестра | `scripts/check_adr_registry.py` + green CI |
| 1 | T2.3 | IChainLogger Protocol | ADR-CHN-008 + правки |
| 2 | T1.2 | Авто-регистрация state.changed | ADR-SS-006 закрыт |
| 2 | T2.2 + T3.1 | Граница registers/state_store + 8-й паттерн | ADR-RM-002 |
| 3–4 | T1.1 | Расщепление process_module | < 1 500 LOC в фасаде |
| 5 | T2.1 | Решение по macOS SHM | ADR + либо фикс, либо платформенный маркер |
| 5 | T3.2 + T3.3 | Cheat-sheet + архивирование | Готово |

**Контрольные точки:**
- После T1.3 — невозможна регрессия по ADR-реестру.
- После T1.1 — `process_module` готов к тонкому plugin-механизму (ADR из IMPROVEMENT_PLAN §2.5).
- После всего — целевой балл **9.0 / 10**.

---

## 4. Что делать НЕ нужно

- ❌ Переписывать `data_schema_module` (16 168 LOC) — он зрелый, тестируемый, и правки могут уронить FieldRouting fan-out, на котором держится 7 модулей.
- ❌ Объединять `registers_module` и `state_store_module`. Они решают **разные задачи** (см. T2.2).
- ❌ Добавлять новые модули, пока T1.1 не закрыт. `process_module` — узкое место для любой новой подсистемы.
- ❌ Рефакторить наблюдаемость снова — после 716ed34 канал чистый, любая правка ломает прикладной код.

---

## 5. История обновлений плана

| Дата | Изменение |
|------|-----------|
| 2026-05-07 | Создание. Базовая оценка 8.4/10, выделено 3 Tier-1 / 3 Tier-2 / 3 Tier-3 задачи. |
| 2026-05-07 | T1.3 закрыт. `scripts/sync/` создан (3 sync-модуля: `adr_modules`, `adr_toc`, `adr_obsolete`). ADR-119, маркеры в `DECISIONS.md`/`ADR_REGISTRY.md`, CLI (--check/--list/--only), интеграция `validate.py`. Правило 8 в CLAUDE.md. 20 pytest-тестов. Коммиты: c6573ad…77e992a. |
