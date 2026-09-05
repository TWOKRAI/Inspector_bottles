# channel_routing_module — Архитектурные решения

> Ссылки на глобальные решения: [`../../DECISIONS.md`](../../DECISIONS.md)

## ADR-CRM-001 (was ADR-013): Паттерн CRM (ChannelRoutingManager)

**Статус:** принято (2026-03-12)

**Контекст:** LoggerManager, ErrorManager, RouterManager дублировали логику маршрутизации.

**Решение:** Единый базовый класс `ChannelRoutingManager` = `BaseManager` + `ObservableMixin` + `ChannelRegistry` + `Dispatcher` + опционально `IBufferStrategy`.

**Следствие:** Все канальные менеджеры наследуют CRM, добавляя только доменную логику.

## ADR-CRM-002 (was ADR-014): Три стратегии буферизации

**Статус:** частично устарело — стратегий осталось две (см. врезку)

- `DirectBuffer` — без буферизации (тесты, простые случаи).
- `BatchBuffer` — deque + timer (`LoggerManager`: batch flush по size/interval).
- `AsyncSenderBuffer` — PriorityQueue + фоновый поток (`RouterManager`: async send).

> **Ф7.4 (2026-08-05): `BatchBuffer` снят целиком** — см. ADR-LOG-008 в
> [`logger_module/DECISIONS.md`](../logger_module/DECISIONS.md). Батчинг файловой записи не давал
> экономии на границе ОС (`write`/`flush` одинаковы) и портил хвост эмитента (p99 1348 против
> 75 мкс); запись синхронна на всех уровнях. Решение оставлено в реестре как запись о том, что
> было, а не как описание живого кода: у плоскости логов и ошибок буфера сегодня нет вовсе, у
> статистики — `AggregationWindow` (ADR-SM-006).

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

## ADR-CRM-017: форма персистируемого числа живёт у владельца персистентности; колонка `metric` и ОДНО слово в `severity` (Task 3.1)

**Статус:** принято (2026-09-05). **Отменяет** решение `OBSERVATION_LEVEL_SEVERITY = "level"` из
[`statistics_module/DECISIONS.md`](../statistics_module/DECISIONS.md) (ADR задачи 3.2, «Ремонт») — см. § «Что отменено».

**Контекст.** Одно и то же число жило в трёх несовместимых диалектах, и каждый читатель знал все три:
агрегат окна `MetricRecord.aggregate()` (`{name, type, tags, count|value|min/max/avg/p95/…}`), hub-запись
сырой метрики (`{metric, value, metric_type, tags}`) и запись порта наблюдений (`{writer, metric, value}`).
Имя звалось `name`/`metric`/`metric`, род — `type`/`metric_type`/никак, писателя знал только третий.
Нормализатор `hub_record_to_display` различал их ветками, засыпка колонки `metric` — ещё двумя, GUI — своими.

Task 3.1 завёл ОДНУ форму — `NumberRecord` — и положил её в `statistics_module/core/`, по владельцу
СМЫСЛА метрики (ADR-CRM-009 отдал статистике агрегацию). Ревью вернуло блокер: нормализатор через форму
не проведён, то есть форма существует рядом с ветками, а не вместо них. Провести его оттуда нельзя —
кольцо импортов **воспроизведено**, а не выведено:

```
observability/__init__ → observability_store → record_display → statistics_module/__init__
    → channels/log_stats_channel → observability/store_tap → observability_store (частично загружен)
```

Звено `log_stats_channel → store_tap` реально: `statistics_module/channels/log_stats_channel.py:11`
импортирует `ORIGIN_FIELD`/`ORIGIN_STATS_SNAPSHOT` из `channel_routing_module.observability.store_tap`.

**Решение.** Три части, все три — про одно: у формы числа один владелец, и это владелец персистентности.

**1. Файл переехал в `channel_routing_module/observability/number_record.py`.** ADR-CRM-009 провёл границу
«statistics владеет АГРЕГАЦИЕЙ, hub/store — ТРАНСПОРТОМ И ПЕРСИСТЕНТНОСТЬЮ записей». Форма
персистируемого числа — про то, что ляжет в колонки стора и в display-вид, то есть про вторую половину
границы, а не про первую. Вместе с формой переехало правило идентичности `number_metric_identity`
(«как зовут это число» — вопрос к форме, а не к нормализатору); обратный порядок замкнул бы кольцо уже
внутри пакета: `record_display → number_record → record_display`.

`hub_record_to_display` теперь берёт идентичность у формы: ветки одиночной `stats` и `observation`
свёрнуты в одну, `NumberRecord.from_hub_record` читает оба диалекта, и четвёртый добавляется в неё, а не
третьей веткой в нормализаторе. **Ветка снапшота остаётся отдельной** — агрегат не является одним числом,
единственного имени у него нет (24.8 метрики в среднем на живом файле, максимум 214), и разложить его на
записи по метрике запрещено замером: горизонт стора упал бы с 47.5 ч до ~1.4 ч.

Через форму идёт **идентичность, а не класс записи**: `severity` и `extra` остаются за `kind`. Первая
редакция правки отдала форме и класс записи — и покраснел собственный инвариантный тест
`test_normalizer_and_guard_branch_on_the_same_marker`: снапшот, потерявший маркер, менял бы КЛАСС строки,
а не только имя. Вопрос «к какой плоскости принадлежит строка» не зависит от того, разобралась ли форма.

**Цена замерена, а не оценена** (min из 7 прогонов по 20 000 вызовов, одни входы, один процесс, контроль
на равенство display-вида обеих редакций):

| вход | HEAD `46e970ab` | после | дельта |
|---|---:|---:|---:|
| лог | 1.017 мкс | 0.989 мкс | −0.028 (шум) |
| observation | 0.934 мкс | 3.607 мкс | **+2.67** |
| одиночная stats | 0.655 мкс | 3.416 мкс | **+2.76** |
| снапшот 25 метрик | 4.302 мкс | 4.238 мкс | −0.064 (шум) |

Добавка — стоимость валидации Pydantic при сборке `SchemaBase`. Бюджет Task 3.3 (+5 мкс) написан на
`StoreTapChannel.write` для ЛОГ-записи на потоке эмитента: там ветка не менялась и добавка неотличима от
нуля. Числа едут `hub.drain_all()` пачкой по такту heartbeat при темпе 0.82 записи/с (замер CTO), то есть
+2.7 мкс на запись — это ~2.2 микросекунды процессорного времени в секунду. Для сравнения: ветка снапшота
в том же нормализаторе стоит 4.2–4.3 мкс сама по себе, дороже всей добавки.

**2. Колонка `metric` в сторе, `PRAGMA user_version = 3`, лестница ступеней.** Идентичность числа
(`<writer>.<name>`, либо голое имя, либо `NULL`) вынесена из JSON-мешка `extra` в отдельную колонку с
индексом `(metric, ts)` — иначе ряд по имени метрики строился бы разбором JSON на каждой строке.
Миграция аддитивная и разделена надвое: `ALTER TABLE` (`_migrate_add_metric`) обязан отработать ДО
`CREATE INDEX ... (metric, ts)`, а засыпка (`_migrate_backfill_metric`) — ПОСЛЕ `_init_fts`.

Версия **не поднимается через ступень: 3 берётся только со 2**. `_init_fts` может вернуться раньше времени
(в сборке SQLite нет FTS5) и свою версию 2 не выставить; скакни засыпка `metric` сразу на 3, при следующем
открытии уже НА ДРУГОЙ сборке backfill полнотекстового индекса увидел бы `3 >= 2` и пропустил себя,
оставив индекс пустым для всех прежних строк. Гейт самой засыпки при этом держится на состоянии ДАННЫХ,
а не на «колонку только что добавили»: sqlite3 в legacy-режиме коммитит DDL сразу, а `UPDATE` едет в
транзакции — падение в этом окне оставило бы файл в состоянии «колонка есть, значения NULL» навсегда.

**3. `NUMBER_SEVERITY = "number"` — одно слово всем трём числовым формам.** До Task 3.1 в колонке
`severity` числовых строк жили ТРИ разных словаря: `gauge`/`counter` (тип метрики у одиночной stats),
`"snapshot"` (агрегат окна) и `"level"` (запись порта). Читателю приходилось знать все три и помнить, что
ни одно из них не является уровнем тревожности — при том, что колонка называется `severity`.

Колонка называет **КЛАСС записи**, а не важность. Различие «агрегат или одно число» несут ДВА носителя и
ровно два: колонка `metric` (`NULL` у агрегата) и `extra.aggregate`; третьим носителем оно не возвращается.
Род метрики переехал в `extra.metric_type` — это разные вопросы, и теперь у них разные места. Слово
`info` сюда не поставлено сознательно: оно дало бы либо `severity_number = 9` (и числа затопили бы всякий
запрос «от INFO и выше»), либо `severity='info'` при `severity_number = 0` — две колонки одной строки,
противоречащие друг другу.

**Что отменено.** ADR задачи 3.2 в `statistics_module/DECISIONS.md` (§ «Ремонт») записал
`severity = OBSERVATION_LEVEL_SEVERITY = "level"` с доводом «осознанное имя класса, симметрично
`STATS_SNAPSHOT_SEVERITY`». Симметрия была верна, а вывод из неё — нет: симметричными были ТРИ разных
значения в одной колонке, то есть три смысла на одном месте. Класс записи у всех трёх форм один — «это
число», — и симметрия достигается одним словом, а не тремя. Константы `OBSERVATION_LEVEL_SEVERITY` и
`STATS_SNAPSHOT_SEVERITY` сняты (`hasattr` = False); ссылка на первую оставалась в докстринге
`severity_number_for` и вычищена этим же добором.

**Отклонённые альтернативы.**

- **Оставить форму в `statistics_module`, а кольцо развязать ленивым импортом внутри
  `hub_record_to_display`** — отклонено: импорт внутри функции на пути КАЖДОЙ записи (поиск в
  `sys.modules` на вызов), и кольцо никуда не девается — оно просто перестаёт падать. Владелец формы от
  этого не меняется, а следующий читатель наступит на то же место.
- **Реэкспорт `NumberRecord` из `statistics_module`** — отклонено: единственный вызывающий вне базы —
  файл тестов, и починить один импорт дешевле, чем завести второе имя одной вещи. Реэкспорт вернул бы и
  зависимость `statistics → observability` в eager-импорт `__init__`.
- **Разложить снапшот окна на записи по метрике и убрать отдельную ветку** — отклонено замером: горизонт
  стора 47.5 ч → ~1.4 ч.
- **Свернуть `extra` одиночной stats к общему правилу конверта** (как у observation) — отклонено: правило
  добавило бы в `extra` ключ `metric`, дублирующий колонку, то есть сменило бы форму уже уехавшей в стор
  истории. Форма `{value, tags, metric_type}` запинена литералом в `test_stats_aggregate_delivery.py` и
  `test_record_forward.py`.
- **Оставить `severity = metric_type` у одиночной stats** — отклонено: тогда «от INFO и выше» и
  «все gauge» — один и тот же запрос по одной колонке, и первый молча возвращает второе.

**Следствие.** Известная смена поведения, названная вслух: `kind=stats` с НЕЧИТАЕМЫМ родом (`metric_type`
вне четырёх литералов) теперь теряет имя в колонке `metric` и в `message` — форма такую запись не
собирает. Через эмиттеры хаба она не производится: `ObservabilityHub._emit_stat` приватен, его четыре
вызова передают только `METRIC_COUNTER`/`METRIC_TIMING`/`METRIC_GAUGE`, а у записи порта род всегда
`gauge`. Ручная сборка такого dict'а — единственный вход, и он остаётся открытым риском, а не
гарантией.

**Refs:** `plans/observability-closure/phase-3-store-and-signal.md` (Task 3.1, К3–К8), ADR-CRM-009
(граница агрегация ↔ персистентность), ADR-CRM-015 (маркер агрегата), зеркало —
[`statistics_module/DECISIONS.md`](../statistics_module/DECISIONS.md).

## ADR-CRM-010: `reconfigure` — validate-then-swap, откат к последнему принятому конфигу (R9)

**Статус:** принято (2026-07-27)

**Контекст:** резидуал R9 плана `observability-unified-routing`, рождённый вердиктом по задаче
Ф0.3. `reconfigure` выполнял `_close_all_channels()` **до** разбора нового конфига — разбор жил
у наследника внутри `_rebuild_from_config`. Любой отвергнутый reload оставлял менеджер с пустым
реестром. Воспроизведено на боевой раскладке `LoggerManager`: `reconfigure({**валидный,
"batch_overflow_policy": "drop_middle"})` → 12 каналов → 0, `system.log` 0 байт, логгер онемел.
Санкционированный операторский путь спасала только валидация на фасаде
(`apply_observability_layers` раскладывает слои до касания менеджеров), но она ничем не
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

---

## ADR-CRM-012: Key-based диспетчер снят из базы; владелец — тот единственный, кто им пользуется (Ф4.6)

**Статус:** принято (2026-08-05)

**Контекст:** база владела **вторым** механизмом маршрутизации — слотом `_dispatcher`
(`Dispatcher` из `dispatch_module`) и построенным на нём API `register_route` /
`register_broadcast` / `route`. Каждый зарегистрированный канал дополнительно
регистрировался в нём обработчиком под ключом = имя канала. Постановка задачи Ф4.6
считала слот мёртвым у `LoggerManager` и `ErrorManager`; проверка кодом дала более
резкую картину:

- продовых вызовов `route()` / `register_broadcast()` во всём репозитории — **ноль**,
  единственными вызывающими были тесты самой базы;
- `RouterManager` **перекрывает** `register_route`, и его версия означает другое
  (возвращает имя канала, а не пишет в него), — но при этом присваивал
  `self.channel_dispatcher = self._dispatcher`, то есть **пользовался объектом базы
  через алиас**;
- `LoggerCore`, `ErrorManager`, `StatsManager` получали объект и не обращались к нему
  никогда: у логгера доставка идёт резолвом scope → каналы, у роутера — kind-каналами;
- побочно: `get_stats()` базы публиковал `routed`, который мог вырасти только внутри
  мёртвого `route()`, — то есть структурный ноль в наблюдаемой поверхности.

Комментарии при этом утверждали обратное («_setup_level_routes … регистрирует маршруты
в self._dispatcher напрямую», «инстанс остаётся в базе — его использует ErrorManager»).
Ни то, ни другое не было правдой ни одного дня; именно эти строки и держали слот живым
на бумаге.

**Решение:** базовый слот снят целиком; владение отдано единственному реальному
потребителю.

- `ChannelRoutingManager` больше не создаёт `Dispatcher`, не инициализирует и не
  останавливает его, не регистрирует в нём каналы и не несёт `register_route` /
  `register_broadcast` / `route`; `route()` убран и из `IChannelRoutingManager`.
- `RouterManager` **создаёт свой** `channel_dispatcher` (имя объекта сохранено —
  `{manager_name}_dispatcher`, чтобы записи и статистика не уехали под другой адрес)
  и сам ведёт его жизненный цикл.
- Из `get_stats()` базы ушли `routed` и `key_field`; из allow-list стража счётчиков —
  соответствующие имена, чтобы список не копил мёртвые записи.

**Почему снос, а не «оживить»:** Ф4 вводит **цепочку процессоров**. Оставить рядом
второй, никем не используемый механизм маршрутизации значило бы построить ровно ту
двусмысленность, которую фаза убирает: цепочка процессоров ≠ key-based Dispatcher.
Абстрактный метод, который наследуют все и не использует никто, — не контракт, а
приглашение построить третий путь.

**Цена и риск:** снос обнулил живой `channel_dispatcher` роутера (он был алиасом) —
поймано прогоном, 204 красных теста, исправлено передачей владения. Это же и урок:
«мёртвый» определялся по grep имён методов, а объект переиспользовался через
присваивание. Отсутствие слота теперь стережёт `TestBaseOwnsNoDispatcher` —
у отсутствия нет своего вызова, поэтому иначе оно не стережётся ничем.

**Проверка:** фреймворк 6858 passed / 6 skipped (−9 тестов снесённого API, буферные
переписаны на живой шов «буфер ↔ `flush()`»), дефолтный гейт 958 passed;
слом-инъекция «вернуть слот в базу» убила ровно два предсказанных теста.

**Refs:** `plans/observability-unified-routing.md` (Ф4.6), ADR-CRM-011, ADR-EM-007.

---

## ADR-CRM-013: Долговечность гейтится severity, а документ — не severity (Ф8.3)

**Статус:** принято (2026-08-07)

**Контекст:** резидуалы T2 (Ф5.8, «запись о возврате TTL идёт в журнал процесса, но не в
`ObservabilityStore`») и A2 (Ф5.9, «когда это включили после рестарта отвечается grep'ом, а не
командой») были припаркованы на Ф8.3 с посылкой: расширить пилот `ObservabilityHub` за пределы
`worker_module` — и аудит станет долговечным. Посылка воспроизведена на текущем HEAD и **не
подтвердилась**.

В `ObservabilityStore` (SQLite, `observability_store.py:95`) ведут ДВЕ дороги, и обе закрыты для
аудита:

- **дренаж hub'а** — `records = drained[KIND_LOG] + drained[KIND_STATS]`
  (`observability_wiring.py:352`). После 2.2 `KIND_LOG` у пилота пуст по построению: logger-слот
  write-through в реальный менеджер (`observability_wiring.py:117-131`). Едет только статистика;
- **tap на менеджерах** — `add_tap(..., min_level="ERROR")` (`observability_wiring.py:295`),
  то есть только error/critical.

Аудит смен наблюдаемости пишет на INFO (успех) и WARNING (провал) —
`observability_audit.py:328-329`. Живой репро (реальный `LoggerManager` с `initialize()`,
реальный `wire_observability_store`, SQLite во временном каталоге):

```
lm.log('SYSTEM', ERROR,   'boom control',           module='router_module')       → в сторе 1
lm.log('SYSTEM', INFO,    'audit: session_set …',   module='observability_audit') → в сторе 1
lm.log('SYSTEM', WARNING, 'audit: session_set …',   module='observability_audit') → в сторе 1
```

Все три записи эмитированы (видны в выводе логгера), в сторе — одна, `severity=error`.
Контрольная запись **положительна**, поэтому молчание на двух остальных — вердикт, а не немой
детектор. Фейк из `test_observability_store_wiring.py` этого доказать не мог: его
`FakeLoggerCore.add_tap` игнорирует `min_level` и эмитит всем tap'ам подряд.

**Расширение охвата hub'а этого не лечит:** hub — bounded-буфер, умирающий вместе с процессом
(`observability_hub.py:68`); долговечность даёт стор ЗА ним, а попасть в стор мешает не охват,
а порог.

**Решение — две части:**

1. **Охват hub'а не расширяется.** Решение 2026-07-08 («один hub на процесс с module-тегом»),
   подтверждённое владельцем 2026-07-26, остаётся в силе — и оно уже реализовано в коде:
   `ObservabilityHub(process_name)` (`observability_wiring.py:117`), тег = имя процесса.
   Идентичность источника даёт штамповка имени (Ф2.1), а не менеджер на модуль.
2. **Названо настоящее ограничение:** правило допуска в долговечное хранилище — severity, а
   документ (запись аудита, вердикт о детали) severity не является. Второе правило допуска —
   **по роду записи, а не по уровню** — заводится в Ф8.5, и аудит с вердиктами становятся двумя
   первыми клиентами ОДНОГО механизма. Отдельная дорога каждому означала бы второй такой же
   слой через месяц.

**Следствие:** T2 (Ф5.8) и A2 (Ф5.9) переадресованы с Ф8.3 на Ф8.5 — туда, где уже стоял долг
«ретеншен аудита ≠ ретеншен логов» (ревью 2026-08-03). Три записи об одном и том же вопросе
сведены в одну задачу.

**Что этот ADR НЕ решает:** сам механизм второго правила допуска, срок хранения документов и их
отделение от ротации логов — это Ф8.5.

**Refs:** `plans/observability-unified-routing.md` (Ф8.3, резидуалы T2/A2), ADR-CRM-007
(hub — фасад модуля), ADR-CRM-009 (граница hub ↔ statistics), ADR-LOG-010.

## ADR-CRM-014: миграция `auto_vacuum` унаследованных БД + rollback-гипотеза снята (D3)

**Статус:** принято (2026-08-10)

**Контекст:** major-9 отчёта наблюдаемости + minor про rollback. Фикс Ф5.2/`083b8527`
(2026-08-09) исправил ПОРЯДОК pragma (`auto_vacuum` теперь ставится ДО `journal_mode=WAL`), но
файлы, рождённые ДО этого фикса, уже содержат таблицы — а `PRAGMA auto_vacuum=...` на непустой БД
не применяется вовсе, только `VACUUM` реально переключает режим страниц. Живой пример:
`logs/live_2026_07_28/observability.db` (родился 2026-07-28) — `PRAGMA auto_vacuum` = 0 на
незатронутом файле, подтверждено чтением копии до правки.

**Решение — миграция (`observability_store.py::_migrate_auto_vacuum`):**

- Гейт — `PRAGMA user_version` (не отдельная таблица метаданных): миграция бьёт по файлу РОВНО
  один раз за его жизнь. Проверено slam-инъекцией: удаление гейта `mode == 0` **и** отдельно гейта
  `user_version` дают разные, предсказанные наборы красных тестов (см. отчёт задачи D3,
  `plans/observability-review-remediation.md`, приложен к коммиту) — `user_version`-гейт реально
  экономит повторное чтение `PRAGMA auto_vacuum` на каждом открытии, а не дублирует `mode == 0`.
- Выполняется в `_init_schema()` — на СТАРТЕ процесса-владельца (конструктор `ObservabilityStore`),
  никогда в `append_records` (горячий путь).
- **Цена замерена, не предположена:** синтетическая унаследованная БД, 200 000 строк / 118.3 МиБ
  (тот же порядок, что потолок стора по замеру Ф5.2 — ~110 МБ на том же числе строк) —
  `VACUUM` занял 1.06 с (2026-08-10, холодный диск, один писатель). Число и скрипт синтеза —
  в отчёте задачи D3.
- `VACUUM` транзакционен (либо применяется целиком, либо файл остаётся прежним) и требует
  свободного места ≈ размера БД — отдельная защита копированием избыточна, сбой питания
  посреди него не портит исходные данные.

**Гипотеза «rollback» (`append_records` без `rollback()` при `OperationalError` завышает
`dropped`) — ВОСПРОИЗВЕДЕНИЕ ДАЛО ОТРИЦАТЕЛЬНЫЙ РЕЗУЛЬТАТ, правка не внесена.**

Прямая репродукция настоящей блокировки драйвера (вторая коннекция держит `BEGIN IMMEDIATE`,
`busy_timeout` стора укорочен до 150 мс — НЕ `raise` внутри теста) двумя размерами батча (3 и
2000 строк): после отказа `total_changes` на коннекции стора = 0, `dropped` равен РОВНО размеру
батча, и последующий успешный `append_records` не находит «утёкших» строк
(`count()` == только успешно записанное). См.
`tests/test_store_auto_vacuum_migration.py::TestRollbackHypothesisNotReproduced`.

**Почему не воспроизводится — структурный довод, не везение.** Под WAL один писатель, и
писательский лок берётся АТОМАРНО на всю транзакцию: либо коннекция получает его перед первой
строкой пачки (и тогда пишет её ВСЮ — блокировка от другого писателя не может вклиниться
посередине уже начатой транзакции), либо не получает вовсе (и тогда не пишет ни строки). У
`append_records` ровно одна транзакция на пачку (`executemany` + один `commit()`) — именно эта
атомарность и делает отсутствующий `rollback()` безвредным: экспериментально подтверждено, что
ИМЕННО non-atomic реализация (`commit()` на каждую строку батча) была бы уязвима — но текущий код
не такой.

**Что это не отменяет:** `rollback()` после `except sqlite3.OperationalError` остаётся общей
гигиеной SQLite (не оставлять коннекцию в открытой транзакции без причины) — но это не «дефект
D3», отдельная задача заводить незачем: наблюдаемого расхождения между `dropped` и реальной
потерей нет, а исправление без наблюдаемого следствия — правка без пользы.

**Refs:** `plans/observability-review-remediation.md` (Task D3), ADR-CRM-011 (учёт потерь — общее
хозяйство), commit `083b852729e0` (порядок pragma, `incremental_vacuum` дошагивание).

---

## ADR-CRM-016: `_emit_to_taps` отдаёт число принявших; `has_tap()` — читающий вопрос о подписке (Ф5-добор)

**Статус:** принято (2026-08-26, `plans/observation-port/plan.md`, Ф5-добор по ревью, блокер Б1
и блокер З3; полная картина находки — `statistics_module/DECISIONS.md`, ADR-SM-015)

**Контекст.** Раздача в tap'ы (`_emit_to_taps`) и подписка на неё (`add_tap`/`has_tap`) —
общее хозяйство БАЗОВОГО класса, наследуют его все четыре плоскости (logger/error/stats/
observation). Ревью Ф5-добора нашло, что и раздача, и подписка отвечали на вопрос «состоялось
ли?» по ФОРМЕ вызова, а не по факту, и обе дыры воспроизведены на плоскости чисел порта
наблюдений (`ObservationManager`, потребитель этого контракта):

* `_emit_to_taps` возвращал `None`. Раздача с нулём tap'ов и раздача с живым приёмником были
  снаружи неразличимы — вызывающий не мог спросить у самого метода, дошла ли запись хоть до
  кого-то, и был вынужден выводить это из побочных счётчиков, что и привело к отдельному
  дефекту в `statistics_module` (см. ADR-SM-015);
* факт живой подписки нечем было спросить НЕ разрушая её — `remove_tap()` — единственный
  читающий (в кавычках) метод, и он удаляет то, о чём спрашивает.

**Решение — два независимых, но родственных API-приращения БАЗЫ.**

1. **`_emit_to_taps(record, level=None) -> int`** (было `-> None`). Возврат — число tap'ов, чей
   `write()` вызван и НЕ бросил. Три случая дают ноль: приёмников нет, все пороги выше уровня
   записи, вызов подавлен реентерабельностью (D1) — они и раньше не различались снаружи, теперь
   не различаются ЯВНО, одним и тем же нулём, а не отсутствием ответа. Отдельно от «принял» —
   «принял без ошибки, но вернул `False`»: возврат `write()` на плоскости tap'ов не судится (в
   отличие от `_write_to_channels`, где есть `channel_accepted`) — приёмник, отдавший `False`,
   всё равно засчитан. Приёмник, бросивший исключение, — НЕ засчитан, но учтён отдельно
   (`tap_write_errors`, ADR-CRM-011).

   Отклонено: оставить `-> None` и завести отдельный публичный метод «сколько приняли в
   последний раз» — второй источник истины о том же вызове, расходящийся при любой гонке между
   «спросить» и «раздать» (ровно тот класс дефектов, ради которого ADR-CRM-011 уже собрал учёт
   потерь в одном месте). Возврат из самого вызова этой гонки не заводит.

2. **`has_tap(name: str) -> bool`** — новый публичный метод. Отвечает `True`/`False` по текущему
   составу `self._tap_sinks`, без побочных эффектов.

   Отклонено: судить о подписке по стороннему флагу, который выставляет и снимает вызывающий
   (`StatsManager`) сам, синхронно с `add_tap`/`remove_tap`. Два хранилища одного факта —
   `_tap_sinks` внутри CRM и флаг снаружи — расходятся молча в ту же секунду, когда подписку
   снимают ЛЮБЫМ путём, минующим этот конкретный флаг (второй вызывающий, отладочный `remove_tap`
   напрямую, повторная сборка). `has_tap` читает ЕДИНСТВЕННОЕ хранилище, которое уже есть.

**Следствие.** Оба метода — контракт базового класса, наследуют все четыре плоскости, но
меняют поведение видимо только там, где возврат читают: `ObservationManager` — единственный
текущий потребитель `_emit_to_taps() -> int`, `StatsManager.attach_observation_port` —
единственный текущий потребитель `has_tap`. Прежние вызывающие (`LoggerCore.write`,
`StatsManager._do_flush`) звали `_emit_to_taps` как statement и продолжают — возврат для них не
существует, изменение контракта им не стоило ни строки.

**Известный потолок.** `has_tap` и `_emit_to_taps` читают/используют одно и то же
`self._tap_sinks` БЕЗ лока (тот же режим, что у самой раздачи) — под конкуренцией `has_tap`
может ответить о состоянии, которое уже поменялось к моменту, когда вызывающий получит ответ
(TOCTOU в общем смысле). Это не новый риск: `add_tap`/`remove_tap` и раньше не были атомарны
относительно друг друга на плоскости `_tap_sinks`, `has_tap` лишь сделал существующее состояние
читаемым, не изменив дисциплину доступа к нему.

## ADR-CRM-015: запись-АГРЕГАТ в stats-слоте hub'а — один маркер на трёх потребителей

**Статус:** принято (2026-08-13, `plans/telemetry-stage6.md` Task 2.1, развилка владельца РТ-1(а))

**Контекст.** Плоскость stats была живой дорогой без груза: `drain_hub_into_observability`
уже клал сумму `KIND_LOG + KIND_STATS` в стор и раздавал форвардерам, но слот stats
наполнял единственный владелец — `WorkerManager`, а метрик он не эмитит. В сторе
`kind=stats` стоял на нуле, вкладка «Статистика» была структурно пуста при работающей
плоскости. Решение D6 («ветку `KIND_STATS` не трогать») ждало ровно этой задачи.

Дорога выбрана владельцем: `StatsManager` остаётся ЕДИНСТВЕННЫМ агрегатором, а его
снапшот окна кладётся в hub одной готовой записью. Отклонены (названы, чтобы не
воскресли): сырые эмиссии прямо в hub — метрика на кадр при 30 fps даёт строку на
эмиссию и теряет агрегацию; store-tap прямо на `StatsManager` — tap отдаёт сырую запись
немедленно, тот же шторм другим входом.

**Решение — три правки этого модуля, и все три ветвятся ОДНИМ признаком**
`STATS_AGGREGATE_KEY = "aggregate"`:

1. **`ObservabilityHub.emit_stats_record(payload)`** — «положить готовую запись».
   Прежний единственный писатель слота (`_emit_stat`) навязывал форму «одна запись на
   метрику»; снапшот в неё не ложится. Метод проставляет только конверт
   (`kind`/`module`/`ts`) и копирует входной dict — конверт hub'а не должен появляться
   в чужом объекте задним числом. **Маркер hub НЕ ставит:** поставь он его сам,
   «положить готовую запись» стало бы синонимом «положить агрегат», а hub — примитив
   уровня 0 с законно многими писателями.
2. **Ветка агрегата в `hub_record_to_display`.** Правило «четыре ключа» (`metric`/
   `value`/`metric_type`/`tags`) уничтожало снапшот: ни `metric`, ни `value` у него нет,
   и в БД уехала бы строка `message="" extra={"value": null}` **при зелёном «kind=stats
   > 0»**. Найдено ревью №2 спеки чтением кода — живой прогон это не поймал бы, строка-то
   есть. Агрегат нормализуется правилом конверта, как лог: всё, что не конверт, — в
   `extra`; `severity="snapshot"`.
3. **Предохранитель петли в `ObservabilityDrainAdapter.apply_stat`.** Адаптер доносит до
   `StatsManager` сырые числа ЧУЖИХ владельцев; снапшот пришёл с другой стороны — его
   построил сам менеджер. Стор и форвардеры берут пачку целиком: они не эмитенты, петли
   у них нет.

   **Вред замерен прогоном со снятой проверкой (5 окон), и он НЕ тот, что предсказывала
   спека.** §2-П4 обещал, что снапшот «воскресал бы каждое окно»; фактически у агрегата
   нет ни `metric`, ни `value`, ни `metric_type`, и инвариант адаптера «неизвестный тип не
   теряем» сворачивает весь снапшот в ОДНУ безымянную метрику `record_metric("", 1)`.
   Замер:

   | окно | строк в сторе | серий в записи | серии |
   |---|---|---|---|
   | 1 | 1 | 1 | `('real.metric', 5.0)` |
   | 2 | 2 | **2** | `('', 1.0)`, `('real.metric', 5.0)` |
   | 3…5 | 3…5 | 2 | то же |

   То есть **число строк остаётся линейным** и счёт строк петлю не ловит вовсе; красным её
   делает счёт СЕРИЙ внутри записи. Предохранитель нужен по-прежнему — фантомная безымянная
   серия отравляет каждый снапшот каждого процесса до конца смены и врёт про «сколько метрик
   было в окне», — но обосновывать его «геометрическим ростом» нельзя: такого роста на этом
   пути не бывает. Найдено слом-инъекцией против тестов независимого тестировщика: два его
   теста, названных сторожами петли, остались зелёными именно потому, что судили строки.

**Почему признак ровно один.** Второй независимый признак того же класса (скажем, «нет
ключа `metric`» у нормализатора против маркера у адаптера) разошёлся бы молча: нашлась бы
запись, которая для нормализатора агрегат, а для адаптера сырая метрика — она уехала бы в
БД правильно и при этом провернула бы петлю. Требование внесено в спеку ревью №3 (M2) и
проверяется параметризованным тестом «оба потребителя решают судьбу записи одним
признаком».

**Имена метрик едут в `message`, значения — в `extra`.** Полнотекстовый индекс стора
(задача 1.6) построен по `message`/`module`/`process` и НЕ смотрит в JSON-мешок: положи
имена только структурно — снапшот находился бы фильтром по виду записи и никогда по имени
метрики. Числа в текст не дублируются (урок 3.2/3.4: `repr` читается глазами и ничем
больше).

**Имена в тексте — без повторов, число серий — без свёртки.** Единица окна это СЕРИЯ
(имя × теги), и одно имя даёт столько серий, сколько у него сочетаний тегов. Живой замер
стенда `webcam_sketch` 2026-08-13: у процесса `devices` — **384 серии на 4 разных имени**,
и текст записи весил **16 924 Б**, семнадцать килобайт четырёх слов. После свёртки — 212 Б.
Заголовок при этом называет ОБА числа (`count=384, имён 4`), иначе «count=384» рядом со
списком из четырёх слов читалось бы как «380 имён потерялись». Число опущенных считается
по сериям (`total_count − len(metrics)`), а не по именам: свернувшееся имя никуда не
делось, оно в `extra`. В 2.1 разность всегда ноль — потолок кардинальности вводит 2.2.

**Цена, замеренная на стенде `webcam_sketch` (2026-08-13, 8 процессов, окно 10 с):**

| Что | Число |
|---|---|
| `kind=stats` в сторе | было структурно **0**, стало **63** записи за 142 с |
| установившийся темп stats | **753 строк/ч**, **1.18 МиБ/ч**, средняя запись 1647 Б |
| темп всех видов после старта | 2144 строк/ч → горизонт стора **~93 ч** при потолке 200 000 строк |
| он же без stats | 1391 строк/ч → ~143 ч |
| запись `camera_0` (2 метрики) | 363 Б |
| стартовый всплеск `devices` | 49 285 Б, 384 серии — одноразовый, вход для потолка 2.2 |

Горизонт **93 ч ≥ 24 ч**, поэтому прореживание доставки в стор (каждый K-й снапшот) НЕ
заводится: решение по факту замера, а не заранее.

**Учёт намеренной не-доставки.** `apply_stat` возвращает `False` и на «стока нет», и на
«это агрегат» — одно число снаружи означало бы две разные вещи. Пропущенные агрегаты
считаются отдельно (`skipped_aggregates`), как `empty_suppressed` у окна агрегации.

**Проверено слом-инъекциями (10 шт., предсказание записано ДО прогона, 9 из 10 совпали
сразу).** Расхождение дало настоящую находку — см. ADR-SM-010.
