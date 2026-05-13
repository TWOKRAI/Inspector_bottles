# Архитектурный Review: модули после рефакторинга

> **Ревьюер:** Team Lead · **Дата старта:** 2026-04-09 · **Ветка:** `clean_v3`
> **Обновляется** по мере рефакторинга следующих модулей.
>
> **Метафора:** каждый модуль = аппаратный компонент с разъёмами (interfaces), входами (inputs), выходами (outputs) и панелью управления (config/lifecycle). Вместе они собираются в компьютер — фреймворк многопроцессных приложений.

---

## Слой 0 — Foundation (материнская плата)

### #1 `base_manager` — Чипсет

| | |
|---|---|
| **Ответственность** | Базовые примитивы для всех менеджеров: lifecycle (init/shutdown), адаптеры, наблюдаемость |
| **Входы** | `managers={}` dict при инициализации ObservableMixin |
| **Выходы** | Lifecycle-хуки; proxy-вызовы `_log_info()`, `_emit_stats()`, `_handle_error()` |
| **Разъёмы** | `IBaseManager`, `IObservableMixin`, `IBaseAdapter` — Protocol-based |
| **Панель управления** | Два режима observability: private methods (всегда) + optional proxy |
| **Метрики** | 29→17 файлов (−41%), 2425→1474 LOC (−39%), 52 теста |

**Вердикт: 9/10.** Удалены 4 лишних механизма (PluginRegistry, ObservableDecorators, `__getattr__` magic, on_event/emit_event). Чипсет стал лёгким и pickle-safe. Единственный вопрос — два способа observability вместо одного, но это осознанный trade-off для удобства прикладного кода.

---

### #2 `data_schema_module` — Процессор (CPU)

| | |
|---|---|
| **Ответственность** | ДНК всех данных: SchemaBase, FieldMeta, FieldRouting, валидация, сериализация, реестр схем |
| **Входы** | Декларации классов-наследников SchemaBase с аннотациями FieldMeta |
| **Выходы** | `model_dump()` → dict (Dict at Boundary); `model_validate()` ← dict; SchemaRegistry lookup |
| **Разъёмы** | Core (zero deps) → Registry → Serialization → Container → Extensions (explicit import) |
| **Панель управления** | `FieldRouting(channel=..., process_targets=...)` — единая декларация маршрута + UI + валидации |
| **Метрики** | 97→60 файлов (−38%), 13888→8872 LOC (−36%), 532 теста |

**Вердикт: 9/10.** Сердце фреймворка вычищено агрессивно: удалены `_compat.py`, shim-слой, `tests_backup/`. 5000 LOC мёртвого кода — уничтожены. Четыре слоя (core → registry → serialization → extensions) — правильная стратификация. Единственный минус — caches без reset-механизма, что может мешать при тестировании.

---

## Слой 1 — Routing Primitives (шина данных)

### #3 `dispatch_module` — Контроллер прерываний

| | |
|---|---|
| **Ответственность** | In-process маршрутизация ключ→handler по 4 стратегиям |
| **Входы** | Message dict с полем `command`/`type`; регистрация handler + strategy |
| **Выходы** | Результат handler или `{"status": "error", ...}` |
| **Разъёмы** | `Dispatcher(BaseManager)`, `ScenarioManager`, 4 стратегии: EXACT, PATTERN, FALLBACK, CHAIN |
| **Панель управления** | `ScenarioBuilder` — DSL для цепочек обработчиков |
| **Метрики** | 17→18 файлов, 2243→2310 LOC, 66 тестов |

**Вердикт: 9/10.** Расслоение 736-строчного монолита на фасад + стратегии + ScenarioManager — учебник Strategy pattern. LOC чуть вырос (за счёт ScenarioManager extraction), но связность (cohesion) резко поднялась. Удалены legacy kwargs и alias `AdvancedDispatcher`.

---

### #4 `channel_routing_module` — Системная шина (PCIe bus)

| | |
|---|---|
| **Ответственность** | Унифицированный базовый класс для всех менеджеров с каналами. Паттерн CRM = registry + dispatcher + buffer |
| **Входы** | `ChannelRoutingConfig(SchemaBase)` или dict; каналы (IChannel impl) |
| **Выходы** | Маршрутизированный dict в нужный канал |
| **Разъёмы** | `ChannelRoutingManager`, `IChannel`, `IBufferStrategy`, `ChannelRegistry` (thread-safe RLock) |
| **Панель управления** | 3 буферные стратегии: Direct, Batch, AsyncSender |
| **Метрики** | 14→13 файлов, 1348→1334 LOC, 58 тестов |

**Вердикт: 10/10.** Ключевой архитектурный паттерн фреймворка. CRM — это тот самый «стандарт разъёма», в который вставляются Logger, Error, Stats, Router. Иерархия: `CRM ← LoggerManager`, `CRM ← RouterManager`. Удалён shim `base_buffer.py`. Три буферные стратегии покрывают все сценарии (синхронный / батч / async).

---

## Слой 2 — Messaging (протокол передачи)

### #5 `logger_module` — Системный лог (BIOS POST)

| | |
|---|---|
| **Ответственность** | Централизованное логирование с scope-routing (6 скоупов: SYSTEM, BUSINESS, PERFORMANCE, AUDIT, SECURITY, DEBUG) |
| **Входы** | Log records через ObservableMixin (`_log_info/warning/error/critical`) |
| **Выходы** | Batch-запись в каналы: FileChannel, ConsoleChannel, HttpChannel |
| **Разъёмы** | `LoggerManager(CRM)`, `ILogChannel(IChannel)`, `LoggerManagerConfig(SchemaBase)` |
| **Панель управления** | Scope + Level routing; настраиваемый batch size/interval |
| **Метрики** | 16→14 файлов, 1909→1526 LOC (−20%), 11 тестов |

**Вердикт: 8/10.** Удалены `LogDispatcher`, пакет `batcher/`, упрощён `LogRecord`. Первый реальный CRM-потомок — доказывает, что паттерн работает. **Слабое место: 11 тестов — минимум для production-модуля.** Scope-routing — сильная идея, но покрытие тестами нужно довести до ~30-40.

---

### #6 `config_module` — CMOS/BIOS Settings

| | |
|---|---|
| **Ответственность** | Runtime-управление конфигурациями. Dict at Boundary между процессами, Pydantic внутри |
| **Входы** | Initial dict; env-fallback (`{PREFIX}_{KEY}`) |
| **Выходы** | Dict-снэпшоты для ConfigStore (cross-process); подписки на изменения |
| **Разъёмы** | `Config`, `ConfigManager`, `ConfigSection`; dict ↔ Config ↔ ConfigManager ↔ ConfigStore |
| **Панель управления** | Dot-notation доступ, RLock thread-safety, subscriptions |
| **Метрики** | 11→11 файлов, 1074→1074 LOC, 49 тестов |

**Вердикт: 9/10.** Модуль не менял код — и это правильно. Он уже был чистым. Добавлены `DECISIONS.md`, документация Dict at Boundary в README, секция §6.6 в ARCHITECTURE.md. Пример зрелого подхода: не рефакторить ради рефакторинга.

---

### #7 `message_module` — Сетевой протокол (TCP/IP стек)

| | |
|---|---|
| **Ответственность** | Универсальный транспортный протокол. `Message(SchemaBase)` с 9 типами |
| **Входы** | `MessageAdapter.create(...)` или `Message.create(type, ...)` |
| **Выходы** | `msg.to_dict()` для очередей (Dict at Boundary); `Message.from_dict(raw)` при получении |
| **Разъёмы** | `Message`, `MessageAdapter`, `MessageType` enum; type-specific schemas |
| **Панель управления** | 9 типов: GENERAL, COMMAND, LOG, SYSTEM, BROADCAST, DATA, REQUEST, RESPONSE, EVENT |
| **Метрики** | 21→16 файлов (−24%), 2088→1306 LOC (−37%), 112 тестов |

**Вердикт: 9/10.** Ключевое решение рефакторинга: `Message = SchemaBase`. Удалены `converters/`, `validators/`, `schemas/base.py` — всё дублирующее. 112 тестов включая pickle roundtrip. `validate_assignment=False` для fluent API — осознанный trade-off. Открытый вопрос: correlation_id для REQUEST/RESPONSE (scope router_module).

---

### #8 `shared_resources_module` — Оперативная память (RAM)

| | |
|---|---|
| **Ответственность** | Pickle-safe хранилище межпроцессных ресурсов: очереди, события, shared memory |
| **Входы** | `register_process(name, config)` — dict конфигурации |
| **Выходы** | `srm.for_process(name)` → Handle API; ProcessData с Queue/Event refs |
| **Разъёмы** | `SharedResourcesManager`, `ProcessData`, `ConfigStore`, `MemoryManager` |
| **Панель управления** | Handle API (unified access); `reinitialize_in_child()` после unpickle |
| **Метрики** | ~45 файлов, ~3500 LOC, 50+ тестов |

**Вердикт: 8/10.** Handle API (`srm.for_process(name)`) — хорошая абстракция единой точки входа. Pickle-safe гарантии протестированы. `reinitialize_in_child()` решает проблему Windows spawn. Модуль сложный (~3500 LOC), но это обусловлено реальной сложностью задачи (queues + events + shared memory + config store).

---

## Слой 3 — IPC Hub (сетевая карта)

### #9 `router_module` — Сетевой коммутатор (Network Switch)

| | |
|---|---|
| **Ответственность** | Главный IPC-хаб. Маршрутизация сообщений между процессами через каналы |
| **Входы** | Message dict; channel resolution через exact match или dispatcher |
| **Выходы** | Async/sync send results; received messages через callbacks |
| **Разъёмы** | `RouterManager(CRM)`, `QueueChannel(IMessageChannel)`, `AsyncSender`, `AsyncReceiver`, `MiddlewarePipeline` |
| **Панель управления** | Thread-safe stats, priority queue, middleware chain send/recv |
| **Метрики** | 16→15 файлов, ~1995→~1818 LOC, 101 тест |

**Вердикт: 8/10.** AsyncSender с PriorityQueue + middleware pipeline — серьёзная архитектура. Thread-safe stats исправлены (был `except: pass` — найден и убран). `_channel_registry.py` мёртвый код — удалён. **Открытые задачи:** correlation_id registry, интеграция с ErrorManager/StatsManager. `router_manager.py` всё ещё 600 LOC — мог бы выиграть от дальнейшего расслоения, но это допустимо для центрального компонента.

---

## Слой 4 — Worker & Command (периферия)

### #10 `worker_module` — Контроллер периферии (USB Controller)

| | |
|---|---|
| **Ответственность** | Жизненный цикл потоков внутри процесса. SYSTEM/APPLICATION типы; LOOP/TASK режимы |
| **Входы** | `ThreadConfig(SchemaBase)` dict из конфига процесса |
| **Выходы** | `WorkerStatus` enum; статистика воркеров; stop/restart |
| **Разъёмы** | `WorkerManager`, `WorkerRegistry`, `WorkerLifecycle`, `ThreadConfig` |
| **Панель управления** | 5 приоритетов (SYSTEM 1ms → BACKGROUND 5s); auto-restart; зависимости между воркерами |
| **Метрики** | 17→17 файлов, 1591→~1503 LOC, 62 теста |

**Вердикт: 10/10.** Образцовый модуль. Thread-safe registry, два типа + два режима, 5 уровней приоритета, auto-restart, зависимости — всё покрыто 62 тестами. ADR-159 (удалено ложное ребро worker→dispatch) — точечная хирургия. Документация обновлена. Ничего лишнего.

---

### #11 `process_module` — Процессорное ядро (CPU Core)

| | |
|---|---|
| **Ответственность** | Абстракция дочернего процесса. Агрегирует все менеджеры, управляет lifecycle + state + communication |
| **Входы** | Config dict с секциями name, workers, managers |
| **Выходы** | send/receive/broadcast через RouterManager; lifecycle events |
| **Разъёмы** | `ProcessModule(BaseManager + ObservableMixin)`; Protocol `ISharedResources` |
| **Панель управления** | State machine: CREATED → INITIALIZING → RUNNING → STOPPING → STOPPED |
| **Метрики** | 27→26 файлов, 2720→~2711 LOC, 69 тестов |

**Вердикт: 8/10.** Circular dependency с SRM решена через Protocol (`ISharedResources`) — правильный подход. 5 субкомпонентов (lifecycle, managers, communication, config_handler, state) хорошо разделены. LOC почти не изменились (~2711), но внутренняя структура стала значительно яснее. **Замечание:** `ProcessLaunchConfig` lazy import через `__getattr__` — хак, но документированный.

---

### #12 `command_module` — Клавиатура (Input Device)

| | |
|---|---|
| **Ответственность** | Тонкая обёртка над dispatch_module. Семантика «команда» поверх общего dispatch |
| **Входы** | Message dict с полем `command`; регистрация handler |
| **Выходы** | Результат handler или error dict |
| **Разъёмы** | `CommandManager(BaseManager + ObservableMixin)`, `CommandAdapter`, `BaseCommandManager` |
| **Панель управления** | Все 4 стратегии dispatch; full_message mode; fallback |
| **Метрики** | 9→9 файлов, 778→~746 LOC, 34 теста |

**Вердикт: 9/10.** Осознанно тонкий. README чётко объясняет разницу с dispatch_module (семантика vs механика). `BaseCommandManager` без ObservableMixin — для лёгкого тестирования. `CommandAdapter` — мост к ProcessModule. Удалена дупликация legacy kwargs.

---

## Сводная оценка

### Таблица «Компьютер в сборе»

| Компонент | Модуль | Оценка | Здоровье |
|-----------|--------|--------|----------|
| Чипсет | `base_manager` | 9/10 | Здоров |
| CPU | `data_schema_module` | 9/10 | Здоров |
| Контроллер прерываний | `dispatch_module` | 9/10 | Здоров |
| Системная шина | `channel_routing_module` | 10/10 | Эталон |
| Лог BIOS | `logger_module` | 8/10 | Мало тестов |
| CMOS Settings | `config_module` | 9/10 | Стабилен |
| TCP/IP стек | `message_module` | 9/10 | Здоров |
| RAM | `shared_resources_module` | 8/10 | Сложный, но оправданно |
| Network Switch | `router_module` | 8/10 | Открытые задачи |
| USB Controller | `worker_module` | 10/10 | Эталон |
| CPU Core | `process_module` | 8/10 | Здоров |
| Клавиатура | `command_module` | 9/10 | Здоров |
| **Генеральный директор** | **`process_manager_module`** | **9/10** | **Здоров (после fix P1)** |

**Средняя оценка: 8.8/10 → 8.8/10 (13 модулей)**

---

### Ключевые победы рефакторинга

1. **−8000+ LOC мёртвого кода** — data_schema_module (−5000), message_module (−780), base_manager (−950), logger_module (−380)
2. **1100+ тестов** суммарно по 13 модулям — каждый модуль имеет тесты (1647 passed по всему фреймворку)
3. **CRM-паттерн** (channel_routing_module) — единый «разъём» для Logger/Error/Stats/Router. Архитектурная жемчужина
4. **Message = SchemaBase** — единый источник полей, без дупликации
5. **Dict at Boundary** строго соблюдён во всех 13 модулях
6. **Pickle-safe** — проверено для Windows spawn
7. **Per-process stop events** — каждый процесс управляется индивидуально (stop/restart). Graceful shutdown cascade hardened

---

### Оставшиеся риски

| Риск | Модуль | Влияние |
|------|--------|---------|
| 11 тестов у logger | `logger_module` | ProcessManager активно использует логирование |
| correlation_id не реализован | `router_module` | REQUEST/RESPONSE между процессами неполны |
| `router_manager.py` — 600 LOC | `router_module` | Центральный для ProcessManager, сложность сохраняется |
| Два SRM (main + PM) | `process_manager_module` | Архитектурная черта bootstrap, не баг, но усложняет ментальную модель |
| `_process_configs` статический | `process_manager_module` | restart откатывает к начальному конфигу, не к runtime-изменённому |

---

### Общий вердикт (после 13 модулей)

**13 модулей отрефакторены.** Фреймворк — полноценный конструктор многопроцессных приложений. Оркестратор (`process_manager_module`) управляет отдельными процессами (stop/restart), обнаруживает crashes через heartbeat, завершает систему через graceful cascade. 1647 тестов зелёные. **Готов к Milestone M1** — первое multi-process приложение на фреймворке.

---

## Дополнения после следующих модулей

> Секции ниже заполняются по мере рефакторинга модулей #13+.

### #13 `process_manager_module` — Генеральный директор (оркестратор)

| | |
|---|---|
| **Ответственность** | Запуск, мониторинг, управление lifecycle всех процессов. Верхний слой фреймворка. |
| **Входы** | `add_process(name, dict)` — Dict at Boundary; SIGINT/SIGTERM сигналы; IPC-команды (process.start/stop/restart/status, system.shutdown) |
| **Выходы** | OS-процессы с индивидуальными stop_events; broadcast status changes; get_status()/get_stats() → dict |
| **Разъёмы** | `ISystemLauncher`, `IProcessManagerProcess`, `IProcessRegistry` — Protocol-based |
| **Панель управления** | 7 builtin commands; per-process stop/restart; heartbeat monitoring; graceful shutdown cascade |
| **Метрики** | 21→25 файлов (+4: runner split + bundle_contract), 2486→2490 LOC, 143 теста (11 тест-файлов) |

**Вердикт: 9/10.** Критический баг P1 (shared stop_event) — исправлен: каждый процесс получает индивидуальный `Event()`. Добавлен `restart_process()` с сохранением конфигов. `process_runner.py` расслоен с 447 до 185 LOC (+ 3 focused файла). ProcessSpawner упрощён: убраны лишние ConfigManager/LoggerManager/ErrorManager. Monitor дополнен heartbeat (`process.is_alive()` → crash detection). Bundle формализован через `bundle_contract.py`. **Два осознанных технических долга:** (1) два экземпляра SRM (main + PM) — архитектурная черта bootstrap, не баг; (2) при динамическом изменении конфига `_process_configs` не обновляется автоматически.

### #14 `error_module` — ???

_TODO: после рефакторинга_

### #15 `statistics_module` — ???

_TODO: после рефакторинга_
