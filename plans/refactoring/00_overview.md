# 00 — Обзор рефакторинга `multiprocess_framework`

> **Контекст:** Фаза 0 мета-плана v4.1 (`plans/floating-leaping-ritchie.md` в `~/.claude/plans/`).
> **Цель документа:** зафиксировать стартовую точку — порядок модулей, метрики «до», милестоны. Дальше каждый модуль получает свой per-module план `plans/refactoring/NN_<module>.md`.

---

## 1. Роли папок в репозитории

| Папка | Роль |
|-------|------|
| `Inspector_prototype/multiprocess_framework/` | **Рефакторим на месте.** Единственный фреймворк. Никаких форков. |
| `Inspector_prototype/multiprocess_prototype/` | **Референс v1.** Не трогаем. Источник регистров, domain-классов, рабочих рецептов. |
| `Inspector_prototype/multiprocess_prototype_v2/` | **Референс v2** (лучше v1, но не доделанный). Не трогаем. Источник свежих идей. |
| `Inspector_prototype/multiprocess_prototype_inspector/` | **Новый прототип.** Создаётся с нуля на milestone M1 (после модуля #13). Код портируется из v1/v2 через понимание, не копипастом. |

---

## 2. Граф зависимостей

См. §3 в [`Inspector_prototype/multiprocess_framework/ARCHITECTURE.md`](../../Inspector_prototype/multiprocess_framework/ARCHITECTURE.md#3-граф-зависимостей) — единый источник истины. Граф отражает порядок рефакторинга «от листьев к корням».

---

## 3. Порядок модулей и фокус рефакторинга

Порядок — из §4.3 мета-плана. Внутри каждого слоя модули отранжированы так, чтобы быстрее дойти до первого работающего приложения (milestone M1).

| #  | Модуль                     | Зависит от         | Фокус рефакторинга |
|----|----------------------------|--------------------|--------------------|
| 1  | `base_manager`             | —                  | Свернуть `ObservableMixin` (4 способа → 2). Удалить `PluginRegistry`, `ObservableDecorators`, `simple_mode`, `MethodCache` (если не даёт измеримого выигрыша). |
| 2  | `data_schema_module`       | —                  | **Сердце фреймворка.** Вычистить `_compat.py` целиком. Вырезать неиспользуемое из `extensions/`. Закрепить `SchemaBase` + `FieldMeta` + `FieldRouting` + `register_dispatch` + `SchemaRegistry` как единственный публичный API. |
| 3  | `dispatch_module`          | #1                 | Расслоить `dispatcher.py` (736 LOC): тонкий фасад + `strategies/exact.py`, `pattern.py`, `fallback.py`, `chain.py` + `scenarios.py`. Удалить старый API (`logger_manager=`, `error_manager=`). |
| 4  | `channel_routing_module`   | #1, #2, #3         | Закрепить паттерн «manager = CRM + buffer + dispatcher + channels». Подготовить базу для Logger/Error/Stats. |
| 5  | `logger_module`            | #4                 | Сжать `logger_manager.py` (582 LOC). Удалить `LogDispatcher` (backward compat). Первый реальный CRM-потомок. |
| 6  | `config_module`            | #1, #2             | `ConfigStore`: dict на границе, Pydantic внутри. Удалить устаревшую документацию. |
| 7  | `message_module`           | #2                 | Сжать `message.py` (508 LOC). Один `Message` + `MessageType` enum + опц. Pydantic-схема. Удалить backward compat «create без схемы». |
| 8  | `shared_resources_module`  | #1                 | Аудит pickle-safe гарантий. Тест spawn на Windows. |
| 9  | `router_module`            | #4, #7, #3         | Разнести `router_manager.py` (624 LOC): фасад + `sender.py` + `receiver.py` + `middleware.py`. Чётко отделить `targets` (имя процесса) от `FieldRouting.channel`. |
| 10 | `worker_module`            | #1, #3             | Проверить, что `WorkerManager` и `Dispatcher` строятся из одних примитивов. Унифицировать жизненный цикл. |
| 11 | `process_module`           | #10, #9, #5, #8, #2 | Сжать `process_module.py` (585 LOC): 6 субкомпонентов → 3–4 (`lifecycle` + `state` + `communication`). |
| 12 | `command_module`           | #3                 | Оставить как самостоятельный. README объясняет разницу с `dispatch_module`. |
| **13** | **`process_manager_module`** | #11, #12       | Аудит `launcher` / `spawner` / `runner`. Один линейный пайплайн запуска. **→ Milestone M1.** |
| 14 | `error_module`             | #5, #4             | Формализовать как «режим `LoggerManager` со severity-based channel routing». Не сливать. |
| 15 | `statistics_module`        | #4                 | Привести к виду CRM-потомка (как Logger/Error). Каналы: memory / file / prometheus. Проверить дублирование `_metrics` vs `AggregationWindow`. |
| 16 | `sql_module`               | #1, #2             | README + dict-at-boundary для SQL-запросов. |
| 17 | `registers_module`         | #2                 | Пересмотреть роль: «инфраструктура для регистров» (process_registry, discovery, RegistersMeta). |
| **18** | **`console_module`**   | #1, #2, #5         | Кросс-платформенность (Linux headless). Интерактивный режим для регистров. **→ Milestone M2 (главный тест миссии).** |
| **19** | **`frontend_module` → `frontend_framework`** | #2, #6, #17 | **Фаза 2.** Вынести из `multiprocess_framework/` в отдельный пакет. Связь только через `ProcessModule`/`RouterManager`/`FieldRouting`. **→ Milestone M3.** |

---

## 3.1 Архитектурные решения (ADR) — структура документации

**Правило: локальные ADR + глобальные ADR.**

Каждый модуль может иметь свой `modules/<module>/DECISIONS.md` для решений, которые касаются только его архитектуры. Главный `multiprocess_framework/DECISIONS.md` содержит **стык-решения** и **глобальные правила**.

| Файл | Содержит | Примеры |
|---|---|---|
| `modules/X/DECISIONS.md` | Архитектура внутри модуля, паттерны, удаления, внутренний API | `modules/base_manager/DECISIONS.md`: ADR-114…117 (удаление плагинов, декораторов, __getattr__, on_event/emit_event) |
| `multiprocess_framework/DECISIONS.md` (главный) | Взаимодействие модулей, стык-решения, правила фреймворка | ADR-008 (Dict at Boundary), ADR-043+ (взаимодействие процессов), M1/M2/M3 (милестоны) |

**Индекс в главном DECISIONS.md:**
- Раздел «Модульные решения» со ссылками на локальные `modules/X/DECISIONS.md` (по слоям из §2 ARCHITECTURE.md).
- Прямые ссылки в per-module плане (e.g., `plans/refactoring/01_base_manager.md`) — на локальные ADR модуля, а не в главный.

**Взаимоссылки:**
- Локальные ADR ссылаются на главный DECISIONS.md только при зависимости от глобальных решений (e.g., `base_manager/DECISIONS.md` → ссылка на ADR-008 Dict at Boundary).

---

## 4. Метрики «до» (baseline)

Собрано на `clean_v3` перед стартом рефакторинга.

- `files` — количество `.py` в модуле без `tests/` и `__pycache__/`.
- `loc` — суммарное число строк `.py` (включая пустые и комментарии) без `tests/`.
- `tests` — количество файлов `test_*.py` в `modules/<module>/tests/`.
- `public` — TODO, заполняется в Шаге 1 per-module плана (grep по `from <module> import`).
- `coverage` — TODO, заполняется после первого прогона `scripts/run_framework_tests.py --cov`.
- `files_after` / `loc_after` / `tests_after` — метрики после рефакторинга модуля (`—` пока не сделано). Для `tests_after` при необходимости указывают число прогонов pytest в скобках.

| #  | Модуль                       | files | loc    | tests | public | cov | files_after | loc_after | tests_after |
|----|------------------------------|-------|--------|-------|--------|-----|-------------|-----------|-------------|
| 1  | `base_manager`               |  29   |  2425  |   4   |  TODO  | TODO | 17 | 1474 | 3 (52 passed, 2 skipped) |
| 2  | `data_schema_module`         |  97   | 13888  |  24   |  TODO  | TODO | 60 | 8872 | 24 (532 passed) |
| 3  | `dispatch_module`            |  17   |  2243  |   4   |  TODO  | TODO | 18 | 2310 | 5 (66 passed) |
| 4  | `channel_routing_module`     |  14   |  1348  |   3   |  TODO  | TODO | 13 | 1334 | 3 (58 passed) |
| 5  | `logger_module`              |  16   |  1909  |   1   |  TODO  | TODO | 14 | 1526 | 1 (11 passed) |
| 6  | `config_module`              |  11   |  1074  |   3   |  TODO  | TODO | 11 | 1074 | 3 (49 passed) |
| 7  | `message_module`             |  21   |  2088  |   3   |  TODO  | TODO | 21 | 1636 | 3 (103 passed) |
| 8  | `shared_resources_module`    |  41   |  3217  |   8   |  TODO  | TODO | — | — | — |
| 9  | `router_module`              |  16   |  1995  |   2   |  TODO  | TODO | — | — | — |
| 10 | `worker_module`              |  17   |  1591  |   6   |  TODO  | TODO | — | — | — |
| 11 | `process_module`             |  27   |  2720  |   6   |  TODO  | TODO | — | — | — |
| 12 | `command_module`             |   9   |   778  |   3   |  TODO  | TODO | — | — | — |
| 13 | `process_manager_module`     |  21   |  2486  |  10   |  TODO  | TODO | — | — | — |
| 14 | `error_module`               |   7   |   580  |   2   |  TODO  | TODO | — | — | — |
| 15 | `statistics_module`          |  13   |   981  |   3   |  TODO  | TODO | — | — | — |
| 16 | `sql_module`                 |  22   |  1546  |   4   |  TODO  | TODO | — | — | — |
| 17 | `registers_module`           |   6   |   556  |   1   |  TODO  | TODO | — | — | — |
| 18 | `console_module`             |  17   |   974  |   5   |  TODO  | TODO | — | — | — |
| 19 | `frontend_module`            | 147   | 10302  |  12   |  TODO  | TODO | — | — | — |
|    | **Итого (фреймворк + фронт)**| **548** | **50701** | **104** |      |      | | | |

**Ключевые наблюдения:**

- `data_schema_module`: после cleanup shim-слоя — **60** файлов (без `tests/`), **~8872** LOC, **24** test-файла, **532** pytest в `data_schema_module/tests` (2026-04-09). Ранее: 97 / 13 888 LOC — см. план `plans/refactoring/02_data_schema_module.md`.
- `dispatch_module`: **18** файлов `.py` (без `tests/`), **~2310** LOC, **5** test-файлов, **66** pytest; `core/scenarios.py` + делегаты на `Dispatcher`, удалены legacy kwargs и alias `AdvancedDispatcher` (2026-04-09). Ранее: 17 / 2243 LOC — см. план `plans/refactoring/03_dispatch_module.md`.
- `channel_routing_module`: **13** файлов `.py` (без `tests/`), **~1334** LOC, **3** test-файла, **58** pytest; добавлен `DECISIONS.md`, заполнен §6.4 в `ARCHITECTURE.md`, удалён shim `buffers/base_buffer.py` (2026-04-09). Ранее: 14 / 1348 LOC — см. план `plans/refactoring/04_channel_routing_module.md`.
- `logger_module`: **14** файлов `.py` (без `tests/`), **~1526** LOC, **1** test-файл, **11** pytest; удалены `LogDispatcher`, пакет `batcher/`, `LogRecord` → `core/log_types.py`, убраны свойства `channels`/`batcher`/`self.dispatcher`; `error_module` переведён на `_channel_registry.get()` и импорт `LogRecord` из `log_types` (2026-04-09). Ранее: 16 / 1909 LOC — см. план `plans/refactoring/05_logger_module.md`.
- `config_module`: **11** файлов `.py` (без `tests/`), **1074** LOC, **3** test-файла, **49** pytest; код без изменений — добавлены `DECISIONS.md` (локальные **ADR-143…146**, глобальный **ADR-023** без дублирования номеров с ADR-024…027), раздел **Dict at Boundary** в README, §**6.6** в `ARCHITECTURE.md`, индекс в главном `DECISIONS.md`; проверено: `sync_config` / `load_config_from_storage` работают только с **dict** на границе ConfigStore (2026-04-09). См. план `plans/refactoring/06_config_module.md`.
- `message_module`: **21** файлов `.py` (без `tests/`), **~1636** LOC, **3** test-файла, **103** pytest; сжат `core/message.py` (**343** строки, без ленивого `_data`), `MESSAGE_FIELD_DEFAULTS` в `types/message_types.py`, `MessageConverter` и dict-интерфейс на `getattr`; добавлены `DECISIONS.md` (**ADR-147…151**), §**6.7** в `ARCHITECTURE.md`, строка в главном `DECISIONS.md`, тесты `TestClone` / `TestValidateWithoutSchema` / `TestParseMessage` (2026-04-09). См. план `plans/refactoring/07_message_module.md`.
- `frontend_module` (147 файлов / 10 302 LOC) — четверть всего кода. Выделение в `frontend_framework` уберёт существенный объём из ядра.
- Самые «толстые» файлы из §1.1 мета-плана (`dispatcher.py` 736, `router_manager.py` 624, `process_module.py` 585, `logger_manager.py` 582, `message.py` 508) — все целевые на расслоение в per-module шагах.
- `logger_module` имеет только **1** test-файл — риск низкого покрытия. В per-module плане модуля #5 (Шаг 1) явно проверить и при необходимости добить тесты **до** рефакторинга.

---

## 5. Milestones в `multiprocess_prototype_inspector`

Три сознательно. Это не отдельный workflow — это расширенная работа внутри Шагов 4–5 per-module плана для модулей #13, #18, #19.

### M1 — Multiprocess минимум (после модуля #13 `process_manager_module`)

**Файлы:**
- `multiprocess_prototype_inspector/main_m1.py`
- минимум `processes/producer.py`, `processes/consumer.py`
- `multiprocess_prototype_inspector/README.md` (первая глава)

**Что делает:** `SystemLauncher` → `ProcessManagerProcess` → 2 процесса (producer / consumer) → обмен через `RouterManager` → логи в файл → команды `start/stop/restart/status` → graceful shutdown на Ctrl+C.

**Цель проверки:** первое доказательство, что фреймворк делает то, ради чего задумывался. Multi-process, IPC, оркестрация, логирование — всё вместе.

### M2 — Register-driven app (после модуля #18 `console_module`)

**Файлы:**
- `multiprocess_prototype_inspector/main_m2.py`
- `multiprocess_prototype_inspector/registers/` (реальные регистры camera/processing/system как `SchemaBase` с `FieldRouting`)
- `multiprocess_prototype_inspector/README.md` (вторая глава)

**Что делает:** интерактивный console меняет поля регистров в runtime; изменения через `Router` летят между процессами; `ErrorManager` + `StatisticsManager` активны.

**Цель проверки:** **главный тест миссии фреймворка**. Если `main_m2.py` короткий и чистый — рефакторинг достиг цели. Если раздувается boilerplate — возвращаемся к одному из модулей #2 / #9 / #17 / #18 и уточняем его. Это единственная причина отката назад в плане.

### M3 — PyQt GUI (Фаза 2, после модуля #19 `frontend_framework`)

**Файлы:**
- `multiprocess_prototype_inspector/main_m3.py`
- тонкая PyQt-обвязка, импортирующая регистры из `multiprocess_prototype_inspector/registers/`
- `multiprocess_prototype_inspector/README.md` (третья глава)

**Что делает:** то же приложение, что M2, но с PyQt-интерфейсом как **отдельным процессом** (`frontend_framework`). Регистры те же. Изменения из UI → Router → backend.

**Цель проверки:** фронтенд как надстройка через стандартный IPC, а не встроенная деталь фреймворка.

---

## 6. Что не входит в Фазу 0

Осознанно **не делаем** наперёд:

- **Скелет `multiprocess_prototype_inspector/`** — создаётся только на M1, когда реально есть что туда положить.
- **Шаблоны** `per_module_plan_template.md` / `readme_template.md` / `milestone_template.md` — первый per-module план (`01_base_manager.md`) пишется как реальный документ. Если после 2–3 модулей появится повторяющаяся форма — тогда вытащим шаблон.
- **`plans/refactoring/milestones/`** — не нужна. Milestones живут внутри per-module планов модулей #13, #18, #19.

---

## 7. Definition of Done Фазы 0

- [x] `Inspector_prototype/multiprocess_framework/ARCHITECTURE.md` — каркас (§1–§4 заполнены, §5–§8 заголовки-заглушки).
- [x] `plans/refactoring/00_overview.md` — этот документ.
- [ ] Approve пользователя → старт Фазы 1, модуль #1 `base_manager`.
