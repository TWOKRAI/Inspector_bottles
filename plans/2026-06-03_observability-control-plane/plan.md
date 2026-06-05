# Plan: Observability Control Plane — единая конфигурируемая наблюдаемость с hot-reload

- **Slug:** observability-control-plane
- **Дата:** 2026-06-03 (влито в main 2026-06-05)
- **Статус:** ✅ **ЗАВЕРШЁН** (2026-06-05). Phase 1 (`d63bae62`) + Phase 2 (`6e6cf15f`) + Phase 3 (`6a85dc33`+`a1dbe976`+`675d91e7`) + Phase 4 (`8348d303` ADR-CRM-006) — всё в main. Прод-верификация: qt-smoke FPS 21.0 baseline + стабилен после live hot-reload.
- **Ветка:** feat/observability-control-plane — отребейзена на актуальный main и влита (ff). Phase 1 (`reconfigure(config)` на CRM + `invalidate_decision_cache` LoggerManager) теперь в main; §11 CRM #16/#17/#18 (из P0 comm-system) авто-смержились без конфликта (разные регионы). Остаток: Phase 2 (секция `observability` в конфиге), Phase 3 (`ConfigFileWatcher` → live hot-reload), Phase 4 (IPC `config.reload`/`logger.sink.enable` через командный путь хаба). По execution-order — до движковых S4/S5 (decision #4), Phase 2+ «по аппетиту».

## Контекст

Три менеджера наблюдаемости (LoggerManager / ErrorManager / StatsManager) уже наследуют
`ChannelRoutingManager` (CRM): реестр каналов + Dispatcher + буфер. Понятие «sink» уже
существует = `IChannel.write(data)`, multi-sink работает, фабрика `create_channel`
(logger_module/channels/log_channel.py:227) добавляет тип канала одной строкой.
`ConfigFileWatcher` (config_module/tools/watcher.py) написан на watchdog, но нигде не
подключён. `Config.subscribe(callback, key)` (config_module/core/config.py:106) даёт
реактивные подписки. `ObservableMixin.enable/disable/context` даёт runtime-toggle.

Задача — собрать из этих готовых деталей **единую observability-секцию конфига на процесс**
с **hot-reload без рестарта** и унифицированным контрактом `reconfigure(config: dict)` на
CRM-менеджерах, в который позже подключатся IPC-команды backend_control. Принцип — **reuse-first**:
не изобретать, а связать существующее и закрыть 5 диагностированных пробелов.

## Цели

- **G1.** Единая секция `observability` в per-process конфиге управляет всеми тремя
  менеджерами (вместо трёх разрозненных Pydantic-defaults). Прототип реально передаёт её
  (сейчас всё на defaults, `ErrorManager` при пустом конфиге вообще не создаётся).
- **G2.** Hot-reload: правка файла → `ConfigFileWatcher` → `Config.subscribe` →
  `reconfigure()` менеджеров. **Обязательно** инвалидируется `should_log()._decision_cache`.
- **G3.** Унифицированный контракт `reconfigure(config: dict)` на CRM-менеджерах
  (пересоздание каналов/маршрутов из dict, Dict at Boundary) — единая точка для будущих
  IPC-команд.
- **G4.** Реестр sink-фабрик: добавление нового типа sink без правки кода менеджеров.
- **G5.** Все изменения покрыты тестами (smoke hot-reload через временный файл +
  unit на reconfigure / invalidate-cache / factory-registry).

## Out of scope

- cross-process агрегация / remote-stats (StatsManager не держит router — ADR comm-system §9.7);
- GUI observability-вкладка;
- distributed tracing;
- фикс publish↔bind StateStore (отдельная задача telemetry-HANDOFF,
  `plans/2026-06-03_telemetry-backend-control-HANDOFF.md`);
- **реализация** SQLChannel и SocketChannel-push — только проектируются как точки
  расширения через `IChannel`-контракт (см. Phase 4), не строятся;
- **реализация** IPC-команд `logger.sink.enable` / `config.reload` / `stats.subscribe` —
  только проектируется их подключение к `reconfigure()` (Phase 4), не строится.

## Reuse-first карта (что готово / что дописываем)

| Готовый компонент | Путь | Что дописываем |
|---|---|---|
| `ChannelRoutingManager` (registry+dispatcher+buffer) | channel_routing_module/core/channel_routing_manager.py | метод `reconfigure(config)` + `rebuild_channels_from_config()` |
| `IChannel` + `create_channel` фабрика | logger_module/channels/log_channel.py:227 | вынести в реестр sink-фабрик `register_sink_factory()` |
| `ConfigFileWatcher` (watchdog) | config_module/tools/watcher.py | подключить в проде (никакого нового кода watcher'а) |
| `Config.subscribe(cb, key)` | config_module/core/config.py:106 | подписать `reconfigure` на ключ `observability` |
| `ObservableMixin.enable/disable` | base_manager/mixins/observable_mixin.py | использовать для runtime-toggle sink (не дублировать) |
| `should_log` + `_decision_cache` | logger_module/core/logger_manager.py:94,301 | добавить `invalidate_decision_cache()` |
| `managers`-конфиг процесса | process_module/configs/process_config_handler.py:106 | прокинуть `observability` → managers_config в прототипе |

## Порядок выполнения

### Phase 1: Контракт reconfigure + инвалидация кэша (фундамент)
- Task 1.1: **[VERTICAL SLICE]** `reconfigure(config)` на CRM + invalidate-cache в Logger + smoke-тест [DONE `d63bae62`]
  - **Module contract:** public-api-change
- Task 1.2: `reconfigure` override в StatsManager (пересборка каналов агрегации) [DONE `d63bae62`]
  - **Module contract:** public-api-change
- Task 1.3: `reconfigure` override в ErrorManager (пересборка level-routes) [DONE `d63bae62`]
  - **Module contract:** public-api-change
  > Все три — через хук `_rebuild_from_config` (база CRM оркестрирует flush→close→rebuild),
  > а не override `reconfigure`. Подтверждено сверкой кода 2026-06-05 (чекбоксы были stale).

### Phase 2: Реестр sink-фабрик
- Task 2.1: `register_sink_factory` / `create_sink` — реестр поверх `create_channel` [DONE `6e6cf15f`]
  - **Module contract:** public-api-change

### Phase 3: Единая секция конфига + hot-reload в проде — ✅ DONE
- Task 3.1: Pydantic-схема `ObservabilityConfig` + expand → managers_config (Logger/Error/Stats) [DONE `6a85dc33`]
  - **Module contract:** new-lite
- Task 3.2: Прокидка `observability`-секции из прототипа в `managers`-конфиг процессов [DONE `a1dbe976`]
  - **Module contract:** n/a
- Task 3.3: Подключение `ConfigFileWatcher` → `reconfigure` в проде (оркестратор, Option B) [DONE `675d91e7`]
  - **Module contract:** impl-only
  > Решения по открытым вопросам: (1) watcher живёт в оркестраторе (PM), forward-compatible
  > с Phase 4 IPC — решение владельца; (2) использован `on_reload`-callback вместо
  > `Config.subscribe` → снята неоднозначность `_notify("*")`; (3) full-rebuild (как в decisions log).
  > Премисса «ErrorManager не создаётся» устарела: фреймворк (`managers_from_log_dir`) уже даёт
  > полный набор менеджеров — overlay лишь применяет пользовательские значения. Добавлена
  > зависимость `watchdog>=4.0` (ConfigFileWatcher был под неё написан, но не подключён).

### Phase 4: Design-for-extension (только заделы, без реализации) — ✅ DONE
- Task 4.1: Документ-контракт точек расширения (SQLChannel / SocketChannel / IPC-команды) [DONE `8348d303` — ADR-CRM-006]
  - **Module contract:** n/a

Детали задач — в файлах `phase-1.md` … `phase-4.md`.

## Vertical slice (tracer bullet)

Task 1.1 — обязательный сквозной срез: он добавляет `reconfigure()` на базе CRM,
инвалидирует `_decision_cache` в LoggerManager и доказывает контур одним smoke-тестом:
«создать LoggerManager → залогировать (решение закэшировано) → `reconfigure()` с новым
`default_level`/каналом → старое кэш-решение инвалидировано, новый канал создан».
Это E2E-демонстрация механизма ещё до подключения watcher'а и прокидки конфига.

## Открытые вопросы

- [x] **Источник истины конфига: отдельный `observability.yaml` ИЛИ секция в register-blueprint процесса?**
  → **Решение (обосновано ниже в Decisions log): секция `observability` внутри
  существующего `system.yaml` прототипа (sys_config), которая мержится в blueprint
  через `_merge_defaults` и доходит до `managers_config` процесса. Hot-reload-watcher
  вешается на ЭТОТ файл (`system.yaml`).** Отдельный `observability.yaml` отвергнут как
  ложная простота: он плодит второй источник истины, рассинхронизируется с blueprint и не
  переживёт cross-process будущее (где у каждого процесса своя секция). Watcher на
  `system.yaml` не сложнее — `ConfigFileWatcher` уже принимает любой путь, а `Config.update`
  + `merge_with_defaults` корректно сливают частичное изменение.
- [x] **Гранулярность hot-reload в Итерации 1: full-rebuild каналов или diff?**
  → **full-rebuild** (decisions log, реализовано: CRM.reconfigure flush→close→`_rebuild_from_config`).
- [x] **Где живёт `Config`-объект для watcher'а в backend-процессе?**
  → `start_observability_watcher` создаёт `Config(initial_data=<файл>)` ВНУТРИ себя; вызывается
  из `ProcessManagerProcessApp.initialize()` (оркестратор), путь к файлу — через
  `orchestrator_config["observability_config_path"]`. `on_reload`-callback вместо `Config.subscribe`.

## Решения (decisions log)

- **2026-06-03:** Источник истины — секция `observability` в `system.yaml` (а не отдельный
  `observability.yaml`). Причины: (1) единый источник истины с остальной конфигурацией
  процессов — нет рассинхрона; (2) уже есть конвейер `system.yaml → _merge_defaults →
  blueprint → build_configs → managers_config` (launch.py:234,247); (3) `ConfigFileWatcher`
  путь-агностичен — watcher на `system.yaml` не дороже; (4) масштабируется на cross-process
  (per-process секции в одном манифесте). Trade-off: правка `system.yaml` триггерит reconfigure
  всех подписчиков — приемлемо, т.к. `reconfigure` идемпотентен и full-rebuild дёшев.
- **2026-06-03:** `reconfigure(config: dict)` принимает **dict**, не Pydantic (Dict at Boundary).
  Внутри менеджера dict → Pydantic через существующие `_resolve_log_config` /
  `normalize_config`. Это позволяет IPC-команде слать dict без импорта схем.
- **2026-06-03:** Реестр sink-фабрик строится **поверх** существующего `create_channel`
  (не вместо): `channel_types` становится мутируемым реестром + публичный
  `register_sink_factory(type, cls)`. Минимальная дельта, обратная совместимость.
- **2026-06-03:** Итерация 1 — full-rebuild каналов при reconfigure (close old → build new).
  Diff-апдейт и runtime-toggle отдельных sink без пересборки — задел, не реализуется.

---

> **Хранение:** `plans/2026-06-03_observability-control-plane/` (multi-phase).
> Файлы фаз: `phase-1.md`, `phase-2.md`, `phase-3.md`, `phase-4.md`.
> Refs в коммитах: `Refs: plans/2026-06-03_observability-control-plane/phase-N.md`.
