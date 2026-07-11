# channel_routing_module — Архитектурные решения

> Ссылки на глобальные решения: [`../../DECISIONS.md`](../../DECISIONS.md)

## ADR-CRM-001 (was ADR-013): Паттерн CRM (ChannelRoutingManager)

**Статус:** принято (2026-03-12)

**Контекст:** LoggerManager, ErrorManager, RouterManager дублировали логику маршрутизации.

**Решение:** Единый базовый класс `ChannelRoutingManager` = `BaseManager` + `ObservableMixin` + `ChannelRegistry` + `Dispatcher` + опционально `IBufferStrategy`.

**Следствие:** Все канальные менеджеры наследуют CRM, добавляя только доменную логику.

## ADR-CRM-002 (was ADR-014): Три стратегии буферизации

**Статус:** принято

- `DirectBuffer` — без буферизации (тесты, простые случаи).
- `BatchBuffer` — deque + timer (`LoggerManager`: batch flush по size/interval).
- `AsyncSenderBuffer` — PriorityQueue + фоновый поток (`RouterManager`: async send).

## ADR-CRM-003 (was ADR-015): RouterManager не использует IBufferStrategy из CRM

**Статус:** принято

**Контекст:** RouterManager имеет собственный async sender buffer, интегрированный с channel dispatcher.

**Решение:** RouterManager передаёт `buffer_strategy=None` в CRM и управляет буфером самостоятельно (см. также глобальный ADR-015 в [`../../DECISIONS.md`](../../DECISIONS.md)).

## ADR-CRM-004 (was ADR-016): register_broadcast() для мультиканальной доставки

**Статус:** принято

**Решение:** `register_broadcast(key, [ch1, ch2])` регистрирует обёртку, которая вызывает `write()` на всех указанных каналах.

## ADR-CRM-005 (was ADR-108): Две роли конфигов (ChannelRoutingConfig vs ChannelRoutingManagerConfig)

**Статус:** принято (2026-03-31)

- `core/config.py` — `ChannelRoutingConfig(SchemaBase)` — базовый runtime-конфиг; от него наследуют `LoggerManagerConfig`, `RouterManagerConfig` и др.
- `configs/channel_routing_manager_config.py` — `ChannelRoutingManagerConfig(SchemaBase)` — плоская схема для реестра схем / UI.

**Причина:** унифицированный `build()` у наследников `ChannelRoutingConfig` давал разные структуры; отдельная flat-схема решает задачу регистрации без цепочки `core`.

## ADR-CRM-006: Observability Control Plane — точки расширения (design-for-extension)

**Статус:** принято (2026-06-05)

**Контекст:** план `observability-control-plane` построил контур: `reconfigure(config: dict)` на
CRM (Phase 1, через хук `_rebuild_from_config`), реестр sink-фабрик `register_sink_factory`
(Phase 2), единая секция `observability` + hot-reload watcher в оркестраторе (Phase 3). Документ
фиксирует, КАК будущие фичи подключаются к этому контуру **без переделки ядра** — следующий
разработчик дописывает по якорям, а не изобретает.

**Якоря (существующие контракты — НЕ менять):**
- `IChannel.write(record: dict) -> dict` — контракт любого sink (`channel_routing_module/interfaces.py`).
- `register_sink_factory(sink_type: str, factory: type) -> None` — реестр фабрик (`logger_module/channels/log_channel.py`).
- `ChannelRoutingManager.reconfigure(config: dict) -> bool` → хук `_rebuild_from_config(dict)` (full-rebuild).
- `expand_observability(dict) -> {"logger","error","stats"}` (`process_module/configs/observability_config.py`).
- `start_observability_watcher(*, config_path, logger, error, stats, ...)` (`process_module/managers/observability_reload.py`).
- Control plane: `BackendDriver` + `RouterManager.request/reply` + `introspect.*` (см. `backend-control-mcp`).

**Точки расширения:**

1. **SQLChannel** — (а) контракт `IChannel`/`LogChannel`; (б) якорь `class SqlChannel(LogChannel): def write(self, record: dict) -> dict`; (в) дописать класс + `register_sink_factory("sql", SqlChannel)` + секция `channels: {audit_sql: {type: sql, dsn: ...}}`; (г) НЕ требует правок менеджеров/`create_channel`/`reconfigure`. Refs: comm-system §12 P2/P3 (audit-log).
2. **SocketChannel-push** — (а) `IChannel`; (б) якорь `class SocketChannel(IChannel): write()` шлёт через `RouterManager` (Dict at Boundary, БЕЗ прямого SHM — `feedback_no_shm_hacks`); (в) дописать класс + `register_sink_factory("socket", ...)`; (г) ядро не трогается. Путь к cross-process remote-stats.
3. **IPC-команды → `reconfigure`** — (а) живой control plane (`BackendDriver`/`introspect.handlers`); (б) якоря команд: `config.reload` → `manager.reconfigure(new_dict)`; `logger.sink.enable` → `ObservableMixin.enable` / `register_channel`+`unregister_channel`; `stats.subscribe` → `register_sink_factory`+`register_channel` SocketChannel; (в) дописать handler'ы команд в PM (watcher уже в PM — Phase 4 добавляет IPC fan-out на детей); (г) `reconfigure`/реестр НЕ меняются. Refs: `backend-control-mcp`.
4. **GUI-вкладка** — (а) `get_stats()` / `get_registered_sink_types()` на чтение, IPC-команды (п.3) на запись; (б) якорь `LoggerManager.get_stats() -> dict`; (в) дописать вкладку; (г) НИКАКОГО прямого доступа к менеджерам из GUI (Dict at Boundary).
5. **cross-process remote-stats** — StatsManager получает router-ссылку + SocketChannel-sink. В Итерации 1 router намеренно НЕ держится (ADR comm-system §9.7) — это осознанный задел, не недоделка.

**Следствие:** все пять направлений — аддитивные (новый класс канала ИЛИ новый command-handler), ядро
(`reconfigure`, реестр, watcher) остаётся неизменным. Cross-process hot-reload = Phase 4 IPC поверх
watcher'а в PM (forward-compatible, без выбрасываемого кода).

**Refs:** `plans/2026-06-03_observability-control-plane/`, `plans/2026-05-31_comm-system-target-architecture` §12, `plans/.../backend-control-mcp`.

## ADR-CRM-007: ObservabilityHub — фасад наблюдаемости модуля (Ф5.15)

**Статус:** принято (2026-07-09)

**Контекст:** цель владельца — модуль как «электронное устройство»: у фасада три выхода-сигнала
(log / error / stats), все подмодули и классы эмитят в них, а мониторинг снаружи работает
**только через фасад**, не залезая внутрь модуля. `ObservableMixin` уже развязал эмиссию от
доставки (слоты `{'logger','stats','error'}`), `channel_routing_module` даёт примитив канала.
Не хватало слоя-перехватчика между модулем и менеджерами.

**Решение:** `observability/ObservabilityHub(module_name)` — держит три `BoundedChannel`
(log/error/stats), реализует duck-type `LoggerLike`/`StatsLike`/`ErrorLike` (`protocols.py`) и
потому является drop-in заменой для слотов `ObservableMixin` без правок внутри модулей. Вместо
доставки кладёт pickle-safe dict-записи с тегом модуля; владелец забирает их через `drain_*()`.

**Ключевые под-решения:**
1. **Pull-drain, НЕ IBufferStrategy.** `BoundedChannel` реализует `IChannel`, но НЕ
   `IBufferStrategy`: доставка — на дренаже владельцем (по такту heartbeat), не push-flush
   фоновым потоком (идея, pitfall #2). Меньше потоков на hot-path, владелец сам решает when/where.
2. **drop_oldest + счётчик потерь** на каждый канал (идея pitfall #1, урок Ф3.3: «терять можно,
   молчать — нельзя»). Переполнение не блокирует эмиттера.
3. **`track_error`/`record_error` возвращают non-None.** `ObservableMixin._track_error` при
   `None` делает fallback `track_error → record_error` на том же слоте; так как hub реализует
   оба метода, `None` дал бы двойную запись. Truthy-возврат (запись) гасит fallback.
4. **Две плоскости фасада.** data-plane (`drain_*` — разрушающий, для владельца) и monitor-plane
   (`get_info`/`dropped` — **не** разрушающий, для монитора). Мониторинг читает фасад, не
   опустошая каналы и не касаясь внутренностей модуля.
5. **Hub НЕ обязан быть pickle-safe.** Через границу процесса гоняются только dict-записи;
   сам hub переинъектит владелец в слоты после unpickle (как и прочие менеджеры в `ObservableMixin`).
6. **Операционное здоровье hub ≠ `ctx.health`.** Глубина буфера / потери — это здоровье «трубы»,
   доменное здоровье модуля живёт в `ctx.health` отдельно (идея pitfall #4; разделение — задача Ф5.17).

**Следствие:** ноль правок внутри модулей (только конструктор-инъекция hub в слоты). Уровень 1
(сведение фасадов процессов в глобальные менеджеры оркестратора через `RouterManager` + контракты
каналов `log/error/stats` + merge-батч) — wiring задачи Ф5.16, не входит в 5.15.

**Refs:** `plans/2026-07-06_constructor-master/plan.md` (Ф5.15), `.../observability-hub-idea.md`.

## ADR-CRM-008: resolve_build_result — единый примитив разбора build() (D1)

**Статус:** принято (2026-07-11)

**Контекст:** аудит дублирования (`docs/audits/2026-07-10_module-responsibility-duplication-map.md`,
D1) нашёл нормализатор config-shape (`None | dict | Schema | build()`) продублированным ×3:
`ChannelRoutingManager` (`normalize_config`), `LoggerCore._resolve_log_config`,
`ErrorManager._normalize_error_config`. Все три копии заново реализовывали один и тот же разбор
конвенции `RegisterBase.build() -> (name, config_dict)` (и её вариант `build() -> config_dict`),
расходясь в мелочах случайно, а не по архитектурной причине.

**Решение:** выделен общий примитив `resolve_build_result(config) -> Optional[Tuple[Optional[str], dict]]`
в `core/config_normalizer.py`, экспортирован в публичный API модуля. `normalize_config()` (CRM)
переписан поверх него (обёртка с `try/except`, глушит исключения `build()` → fallback на `default`).
`LoggerCore._resolve_log_config` и `ErrorManager._normalize_error_config` тоже вызывают
`resolve_build_result` напрямую (БЕЗ try/except — исключения `build()` по-прежнему пробрасываются,
как и раньше) и надстраивают свою типизированную обвязку (Pydantic `model_validate`, извлечение
`manager_name`/`include_stacktrace`, `expand_error_manager_config`). Наследники **не переопределяют**
разбор tuple/dict-конвенции — только типизацию результата.

**Что осталось нетронутым (не часть дубля D1):**
- `LoggerCore` / `ErrorManager` isinstance-шорткаты для уже готового `LoggerManagerConfig` /
  `ErrorManagerConfig` (identity passthrough, минуя `build()`/`model_validate` — оптимизация и
  защита от лишнего round-trip при передаче конфига между братьями через `LoggerCore.__init__`).
- `ErrorManager` — явный `TypeError` для неподдерживаемых типов config (валидационная политика
  наследника, а не общая форма).
- `expand_error_manager_config` — доменное расширение severity-каналов, не форма конфига.

**Побочный эффект (не покрыт тестами, документируется намеренно):** в `ErrorManager` для
вырожденных build()-объектов (`build()` возвращает tuple с не-dict payload, или голый dict без
имени) `manager_name` теперь падает на `"ErrorManager"` вместо непредсказуемого поведения при
голом `name, config_dict = config.build()` unpack. Ужесточение поведения к общей семантике CRM —
не регрессия для существующих вызывающих (все реальные `RegisterBase.build()` возвращают
`(name, dict)`).

**Следствие:** logger/error/stats конфиг-нормализация проходит через одну функцию-примитив;
106+ существующих тестов трёх менеджеров зелёные без правки ожиданий (характеризационные тесты —
`tests/test_config_normalizer.py` (CRM), `logger_module/tests/test_config_normalization.py`,
`error_module/tests/test_config_normalization.py`).

**Refs:** `docs/audits/2026-07-10_module-responsibility-duplication-map.md` (D1),
`plans/2026-07-06_constructor-master/plan.md` (Ф5-добор, задача C4).
