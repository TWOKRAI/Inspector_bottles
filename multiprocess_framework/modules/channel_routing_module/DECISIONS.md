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

## ADR-CRM-009: Граница observability-hub (транспорт+персистентность) ↔ statistics_module (агрегация) — D8

**Статус:** принято (2026-07-11)

**Контекст:** аудит дублирования 2026-07-10 (`docs/audits/2026-07-10_module-responsibility-duplication-map.md`,
D8) отметил пересечение по оси «наблюдаемость метрик»: `channel_routing_module/observability/`
(`ObservabilityHub` — ADR-CRM-007, `ObservabilityStore` — `observability_store.py`) и
`statistics_module` (`StatsManager`/`AggregationWindow`, ADR-SM-002/006) оба «трогают метрики».
`ObservabilityStore` (Ф5.20a) персистит dict-записи трёх kind — log/error/**stats** —
одной SQLite-таблицей `records` (WAL, конкурентная запись из N процессов, читает GUI пагинацией).
Каждая запись — это **сырой снапшот** `{kind:'stats', module, ts, metric, value, metric_type, tags}`
из `ObservabilityHub.drain_stats()`, НЕ агрегат: hub не считает `counter sum`/`gauge last`/`timing p95`
— это делает исключительно `AggregationWindow` в `statistics_module` (ADR-SM-002/006) на своей
стороне, до попадания в hub.

**Решение владельца (2026-07-10, decision-log Ф5-добора):** «статистика уже на месте, hub —
персистентность записей, не агрегация — в statistics не тащить». Граница:

- **`statistics_module`** владеет **агрегацией**: `counter`/`gauge`/`timing`, rollup через
  `AggregationWindow` (dual-layer storage — `_metrics` live-запрос + окно на flush, ADR-SM-002).
  Он НЕ владеет тем, как снапшот доставляется наружу процесса и хранится между рестартами —
  это происходит уже ПОСЛЕ flush, в чужом модуле.
- **`channel_routing_module/observability/`** (hub + store) владеет **транспортом и
  персистентностью записей**: `ObservabilityHub.drain_stats()` вычитывает то, что уже
  агрегировал `StatsManager`, кладёт в `BoundedChannel` (эфемерно, ADR-CRM-007) и — через
  drain-петлю `process_module` (Ф5.16) — в `ObservabilityStore` (переживает рестарт,
  `observability_store.py:1-24`). Hub/store НЕ пересчитывают counter/gauge/timing и не хранят
  скользящие агрегаты — только последовательность уже готовых снапшотов.
- Не сливать счётчики: рост числа записей `kind='stats'` в `ObservabilityStore` — это история
  снапшотов агрегации, а не альтернативный источник агрегации. Любая будущая фича «посчитать
  метрику по истории» строится ПОВЕРХ `ObservabilityStore.list_records()` как read-side query,
  не как новый counter-движок внутри hub.

**Причина:** разделение по фазам конвейера — статистика решает *что* агрегировать и *как*
(семантика метрики), hub/store решают *куда это уйдёт и как долго проживёт* (доставка +
персистентность). Смешение (например, перенос `AggregationWindow` в hub) сделало бы hub
метрико-осведомлённым (нарушение generic-first — hub одинаково обслуживает log/error/stats),
а перенос персистентности в `statistics_module` задублировал бы SQLite-стор для одного из трёх
kind, которые уже одинаково обрабатывает `ObservabilityStore`.

**Отклонённые альтернативы:**
- **Слить `AggregationWindow` в `ObservabilityHub`** — отклонено: hub обслуживает 3 разнородных
  kind (log/error/stats) одним контуром; протаскивание метрико-специфичной агрегации в generic
  hub нарушает симметрию с log/error (у них нет аналога агрегации).
- **Дать `statistics_module` собственную персистентность** (второй SQLite-стор) — отклонено:
  дублирует `ObservabilityStore` (WAL, конкурентная запись, схема `records`), которая уже
  обслуживает kind=stats наравне с log/error.

**Следствие:** правки только в docs — код не меняется этим ADR. `MODULES_RESPONSIBILITY_MAP.md`
(§1) обновлён: `channel_routing_module` явно владеет observability-стором (транспорт+персистентность
трёх kind), `statistics_module` явно НЕ владеет транспортом/хранением записей.

**Refs:** `docs/audits/2026-07-10_module-responsibility-duplication-map.md` (D8),
`plans/2026-07-06_constructor-master/plan.md` (decision-log Ф5-добора, задача C7),
ADR-CRM-007 (ObservabilityHub), зеркало — [`statistics_module/DECISIONS.md`](../statistics_module/DECISIONS.md) ADR-SM-007.

## ADR-CRM-010: `reconfigure` — validate-then-swap, откат к последнему принятому конфигу (R9)

**Статус:** принято (2026-07-27)

**Контекст:** резидуал R9 плана `observability-unified-routing`, рождённый вердиктом по задаче
Ф0.3. `reconfigure` выполнял `_close_all_channels()` **до** разбора нового конфига — разбор жил
у наследника внутри `_rebuild_from_config`. Любой отвергнутый reload оставлял менеджер с пустым
реестром. Воспроизведено на боевой раскладке `LoggerManager`: `reconfigure({**валидный,
"batch_overflow_policy": "drop_middle"})` → 12 каналов → 0, `system.log` 0 байт, логгер онемел.
Санкционированный операторский путь спасала только валидация на фасаде
(`apply_observability_reconfigure` раскладывает секцию до касания менеджеров), но она ничем не
была зафиксирована и держалась на порядке вызовов.

**Решение:** два независимых рубежа в базе.

1. **`_validate_config(config)`** — новый хук наследника, зовётся ДО `flush()`/`_close_all_channels()`.
   Контракт: бросить исключение, если конфиг не годится. Возврат игнорируется — результат разбора
   намеренно НЕ переиспользуется в `_rebuild_from_config`: два разбора стоят микросекунды на редком
   пути, а протаскивание готового объекта через сигнатуру сделало бы её третьим контрактом между
   базой и тремя наследниками. Переопределяют `LoggerCore` (`_resolve_log_config`) и `ErrorManager`
   (`_normalize_error_config`); у `StatsManager` конфиг — свободный dict, у `RouterManager` своего
   формата каналов нет, оба остаются на no-op базы.
2. **Откат** — `_rollback_to(previous)` при сбое ВНУТРИ пересборки (конфиг валиден, но применение
   упало: отказ ОС при открытии файла, битый путь). Источник — `_last_applied_config`, последний
   **принятый** ввод в исходной форме.

Рубежи защищают от разного и не заменяют друг друга; по `names()` их исходы неразличимы (набор имён
одинаков), различает тождество объектов канала — на нём стоят тесты.

**Почему слепок хранится сырым вводом, а не нормализованным dict:** `ErrorManager` теряет
`include_stacktrace` на dict-форме `LoggerManagerConfig` (это флаг менеджера ошибок, а не логгера),
и откат тихо включил бы трейсбеки тому, кто их выключил.

**Почему наследник обязан выставлять слепок сам:** `LoggerCore` передаёт в базу `config=None` —
свой конфиг он резолвит до `super().__init__`. Без строки в `LoggerCore.__init__` слепок пуст, и
второй рубеж мёртв ровно у логгера и ошибок. Найдено слом-инъекцией, не чтением кода: по базе всё
выглядело исправно.

**Попутно закрыта мёртвая проверка:** `if not isinstance(normalized, dict)` не срабатывала никогда —
`normalize_config` на любом отказе возвращает копию `default`, то есть dict. Следствие:
`reconfigure(42)` нормализовался в `{}` и **применялся как валидный пустой конфиг** — тихо сносил
все каналы и рапортовал успех. Отличить «не разобрался» от «разобрался в пустой dict» можно только
маркером в `default` (`_UNNORMALIZABLE`).

**Отклонённые альтернативы:**
- **Строить новый набор каналов в теневой реестр и менять местами (build-then-swap)** — отклонено:
  честнее по атомарности, но требует второго `ChannelRegistry`, второго набора открытых файловых
  дескрипторов и правил слияния tap'ов. Плата за случай, который валидация уже отсекает.
- **Только откат, без валидации** — отклонено: откат пересоздаёт каналы, то есть переоткрывает
  файлы и пересоздаёт буфер там, где не должно было произойти ничего. Опечатка оператора не имеет
  права стоить переоткрытия всех логов.
- **Только валидация, без отката** — отклонено: конфиг может быть корректным, а применение падать
  (права, гонка за путь, занятый файл). Это не гипотеза — сбой пересборки воспроизводится тестом.

**Следствие:** прямой `manager.reconfigure(сырой_dict)` больше не разрушает реестр — защита
перестала зависеть от порядка вызовов на фасаде. Тест
`process_module/tests/test_reconfigure_registry_survives.py`, фиксировавший дефект как известный,
развёрнут в положительный (он был написан так, чтобы покраснеть в день починки, — и покраснел).
Восстанавливается конфиг, а не рантайм-надстройки: канал, добавленный через
`enable_module_logging`, на откате теряется — записано тестом, а не подразумевается.

**Refs:** `plans/observability-unified-routing.md` (резидуал R9), ADR-CRM-006 (control plane),
Ф0.3 (потолок буфера и видимость потерь).

## ADR-CRM-011: Учёт потерь — общее хозяйство трёх плоскостей (P5)

**Статус:** принято (2026-07-27)

**Контекст:** резидуал P5 ревью фазы Ф0. Учёт потерь на стыке «менеджер → канал» (Ф0.4) остался
в `LoggerCore`, а не в базе. Следствие: у логов и ошибок потеря названа, посчитана поимённо и
видна через `introspect.observability`, а у статистики `StatsManager._do_flush` ловил только
исключение и увеличивал безымянный `_errors` («где-то что-то упало»). Отказ канала **статусом**
(`{"status": "error"}`) не считался вовсе — снапшот метрик исчезал молча. Инвариант плана
«дроп допустим, невидимый дроп — нет» работал для двух плоскостей из трёх.

**Решение:** четыре класса потери и общий писатель живут в `ChannelRoutingManager`.

- `LOSS_COUNTER_KEYS` — именованный перечень классов: «канала нет», «канал бросил», «канал не
  принял», «приёмников нет вовсе». Классы не сливаются, потому что **лечатся разным**: опечатка
  в конфиге, дефект канала, отказывающий сток, пустой реестр.
- `self.stats` заводится в базе; наследник **дополняет** его своими ключами (`update`, не
  присваивание — присваивание стёрло бы общие).
- `_write_record_to_channels` поднят в базу; резолв имени в объект вынесен в хук
  `_resolve_channel`, потому что у логгера каналы лежат в двух местах (реестр +
  `_module_channels`), и база о втором знать не должна.
- `_loss_counters_snapshot()` — один снимок под одним lock-ом, из него публикуются и
  `CRM.get_stats`, и `LoggerCore.get_stats`. Своя копия перечня у логгера уже была источником
  расхождения (Ф0.4).
- `AggregationWindow` начинает уважать контракт `flush_fn → int` (Ф0.3): в её книге появляются
  `total_flushed` (принято) и `flush_failed`. До этого окно вообще не смотрело на результат —
  сток мог не принять ни одной записи, а по книгам всё выглядело сброшенным.

**Что НЕ поднято и почему:** `errors_to_floor` / `errors_floor_write_failures` и сам
`ErrorFloor` — у статистики нет записи, которую нельзя потерять: метрики агрегаты, живое
состояние в `_metrics` переживает потерю flush. В базе они стали бы мёртвым кодом (то же
решение, что в Ф0.6). Продуктовый аналог «нельзя потерять» — вердикты о детали, и у них своя
плоскость (Ф8.5).

**Побочный эффект, названный явно:** `RouterManager` — транспортный наследник базы — тоже
получает четыре счётчика. Они у него нулевые (своего пути записи через
`_write_record_to_channels` он не имеет), но присутствуют в `get_stats`. Это цена общей базы, и
она принята: альтернатива — промежуточный класс между CRM и тремя плоскостями, то есть новый
слой в MRO, запрещённый инвариантом 5 плана и уже отклонённый в Ф0.6.

**Следствие:** страж `test_every_manager_counter_is_published_or_declared_unpublished`
параметризован по ЧЕТЫРЁМ наследникам — счётчик, невидимый наружу хотя бы у одного, красит
сборку. Плюс `test_loss_counter_registry_matches_the_base` сверяет `LOSS_COUNTER_KEYS` с
`PLANE_COUNTER_KEYS`: два списка в двух модулях — классическая точка расхождения.

Живая проверка: сток статистики отвечает отказом → `channel_refused_records=1`,
`channel_refused_by_channel={'metrics_file': 1}`, `buffer.flush_failed=1`, `total_flushed=0`.
До правки все четыре числа были недоступны в принципе.

**Refs:** `plans/observability-unified-routing.md` (резидуал P5), ADR-CRM-010, ADR-EM-007,
Ф0.4 (три класса потери), ADR-SM-002 (агрегация — у статистики).
