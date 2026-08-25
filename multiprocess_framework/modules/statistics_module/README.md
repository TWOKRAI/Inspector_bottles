# statistics_module

Менеджер статистики и метрик — **третья плоскость наблюдаемости**. Наследует
`ChannelRoutingManager` напрямую (не логгер), параметризуется через `data_schema_module`,
интегрируется с `logger_module`, `command_module`, `router_module` через `ObservableMixin` и
`StatsAdapter`.

> Сверено **2026-08-10**, коммит `b04a0c12`. Плоскость целиком описана в
> [`docs/observability/`](../../docs/observability/CONNECTORS.md): `CONNECTORS.md` (разъёмы),
> `SINKS_MAP.md` (маршруты и хранилища), `CONTROL_PANEL.md` (ручки и вердикт).

---

## Архитектура и наследование

```
BaseManager + ObservableMixin
        │
        ▼
ChannelRoutingManager  ← базовый класс (реестр каналов, буфер, sink-control, учёт потерь)
        │
        ▼
StatsManager
  ├── AggregationWindow  (IBufferStrategy — агрегация метрик)
  ├── LogStatsChannel    (IChannel → LoggerManager.performance())
  └── FileStatsChannel   (IChannel → JSON/CSV файл)
```

**Что получает StatsManager от ChannelRoutingManager:**
- `_channel_registry` — thread-safe реестр каналов (`IChannel`)
- sink-control (`set_sink_enabled`) и tap-механику — те же, что у логгера и ошибок
- учёт потерь: пять классов `LOSS_COUNTER_KEYS` + счётчик доставки. До подъёма в базу (P5) у
  статистики потеря считалась безымянным `_errors` — инвариант «дроп допустим, невидимый дроп —
  нет» работал для двух плоскостей из трёх
- `flush()` / `shutdown()` — корректное завершение с финальным flush
- `normalize_config()` — Dict at Boundary (принимает None / dict / SchemaBase)

Key-based `_dispatcher` из базы **снят в Ф4.6** (ADR-CRM-012): через него не проходило ни одной
продовой записи ни у одного из четырёх наследников.

Имя источника модуль **объявляет активно** — `LOG_SOURCE = declare_log_source(...)` в
`interfaces.py`, поэтому оно попадает в `declared_sources()` ещё до первой записи.

**Специфика StatsManager:**
- Типы метрик: `counter`, `gauge`, `timing`, `histogram`. **`timing` и `histogram` — одна
  механика (2.2, ADR-SM-011):** `count`/`sum`/`min`/`max` + фиксированные бакеты
  длительностей в СЕКУНДАХ (`DEFAULT_DURATION_BUCKETS_SEC`). Списков наблюдений больше нет
  ни у одной из двух дорог — память O(1), перцентиль сливается между окнами и процессами
- Двойное хранение: `self._metrics` (live-state для `get_metric()`) +
  `AggregationWindow` (буфер для flush в каналы). **Обе позиции накопительные, у обеих
  потолок серий** `observability.stats.max_series` (дефолт 1000, `0` — без предела) — один
  страж `core/cardinality_guard.py`, два экземпляра, стражи независимы: отказ живого слоя
  не останавливает доставку
- Sentinel-паттерн: `_enqueue_to_buffer` ставит данные в буфер ОДИН раз,
  `_do_flush` транслирует снапшот во ВСЕ зарегистрированные каналы —
  это предотвращает N-кратный счёт при N каналах
- Теги: user tags приоритетнее `default_tags` (`{**defaults, **user}`)
- Каналы: `log_stats` (строка снапшота в `performance.log`, предел по байтам —
  ADR-SM-009), `file_stats` (файловый приёмник и fallback), **`hub_stats`**
  (снапшот окна в stats-слот `ObservabilityHub` → стор и живой хвост, ADR-SM-010).
  `hub_stats` поднимается только если процесс подключил hub
  (`attach_observability_hub`); снимается той же дверью, что остальные —
  `channels.hub_stats.enabled = false` или `observability.sink.disable`

---

## Быстрый старт

### Минимальный пример

```python
from statistics_module import StatsManager

stats = StatsManager(manager_name="my_stats", config={"enable_logging": False})
stats.initialize()

stats.increment("requests.total")
stats.record_timing("request.duration", 0.15)
stats.gauge("memory.used_mb", 256.0)
stats.histogram("response.size_kb", 12.4)

print(stats.get_all_metrics())
stats.flush()   # принудительный сброс в каналы
stats.shutdown()
```

### С конфигом через data_schema_module

```python
from statistics_module import StatsManager, StatsManagerConfig

cfg = StatsManagerConfig(
    manager_name="app_stats",
    aggregation_interval=5.0,
    flush_interval=10.0,
    enable_logging=True,
    log_level="INFO",
    default_tags={"env": "production", "service": "inspector"},
    channels={
        "metrics_file": {
            "type": "file",
            "file_path": "logs/metrics.jsonl",
            "format": "json",
            "enabled": True,
        }
    },
)

stats = StatsManager(config=cfg, managers={"logger": logger_manager})
stats.initialize()
```

### Межпроцессная отправка снапшотов (capability-to-build)

Remote-stats (отправка снапшотов в другой процесс через RouterManager) пока не
реализована — это задел, а не текущая возможность. StatsManager не принимает и не
держит ссылку на router (см. `plans/comm-system-target-architecture.md` §9.7).

---

## Интеграция через ObservableMixin (автоматическая)

После регистрации `StatsManager` как `"stats"` все менеджеры автоматически
направляют метрики в него:

```python
# В ProcessManagers.initialize():
process.register_manager("stats", stats_manager, enabled=True)

# Любой менеджер (CommandManager, RouterManager, WorkerManager, ...) вызывает:
self._record_metric("commands.executed", 1, tags={"command": "ping"})
self._record_timing("dispatch.duration", 0.003)
# → автоматически попадает в StatsManager
```

| Метод ObservableMixin | Маршрутизируется в |
|---|---|
| `self._record_metric(name, value, tags)` | `StatsManager.record_metric()` |
| `self._record_timing(name, duration, tags)` | `StatsManager.record_timing()` |
| `self.record_metric(...)` (auto_proxy=True) | `StatsManager.record_metric()` |
| `self.increment(...)` (auto_proxy=True) | `StatsManager.increment()` |
| `self.gauge(...)` (auto_proxy=True) | `StatsManager.gauge()` |

---

## API

### Жизненный цикл

```python
stats.initialize() -> bool   # создаёт каналы, стартует flush-таймер
stats.flush()                # принудительный flush накопленных метрик
stats.shutdown() -> bool     # flush + stop + close channels
```

### Запись метрик

```python
stats.record_metric(name, value=1, tags=None)   # counter: суммирует значения
stats.increment(name, tags=None)                 # counter: +1
stats.record_timing(name, duration, tags=None)   # timing: СЕКУНДЫ; count/min/max/avg + бакеты
stats.gauge(name, value, tags=None)              # gauge: последнее значение
stats.histogram(name, value, tags=None)          # histogram: та же механика бакетов
```

### Чтение метрик

```python
stats.get_metric(name) -> Optional[Dict]   # одна метрика по имени
stats.get_all_metrics() -> Dict            # все метрики
stats.reset_metrics()                      # сбросить live-метрики
stats.get_stats() -> Dict                  # диагностика (каналы, буфер, метрики)
```

### Управление каналами (наследованы от CRM)

```python
stats.register_channel(channel)            # добавить канал
stats.unregister_channel(name)             # убрать канал
stats.get_channel(name) -> IChannel        # получить канал по имени
stats.get_all_channels() -> List[IChannel] # все каналы
```

---

## Конфигурация

### Параметры StatsManagerConfig

| Поле | Тип | По умолчанию | Описание |
|---|---|---|---|
| `manager_name` | str | `"StatsManager"` | Имя менеджера |
| `channels` | Dict | `{}` | Каналы вывода |
| `aggregation_interval` | float | `5.0` | Интервал агрегации, сек — действует `max` с `flush_interval` |
| `flush_interval` | float | `10.0` | **ПОЛ** интервала записи в каналы, сек — темп ниже него недостижим |
| `enable_logging` | bool | `True` | Логировать через LoggerManager |
| `log_level` | str | `"INFO"` | Уровень логирования метрик |
| `default_tags` | Dict | `{}` | Теги по умолчанию (appended к каждой метрике) |
| `retention_seconds` | float | `3600.0` | Время хранения live-метрик в памяти |

**Темп записи = `max(flush_interval, aggregation_interval)`** (B1, решение Р-3б). Формула живёт в
ОДНОЙ позиции (`resolve_tempo`), дефолты берутся из схемы, а не второй копией чисел в коде — пока
`max()` стоял инлайном в `__init__`, пересборка конфига его не звала вовсе, и ручка была мёртвой.

Пол оставлен, но **не действует молча**: при `aggregation_interval` ниже пола менеджер пишет
WARNING с обоими числами и адресом ключа, а действующий темп виден в
`introspect.observability → effective.stats.aggregation_interval` — он читается **из живого окна
агрегации**, не из конфига. `config.reload` на значении ниже пола отдаёт `verdict=failed` с
расхождением, а не «успех».

**Смена темпа на лету пересобирает окно, и порядок подмены — суть механизма:** новое окно встаёт
на место ДО остановки старого (эмиссия из чужого потока попадает в живое окно), затем `old.stop()`
гасит таймер старого и делает финальный flush уже в пересобранные каналы. Темп не изменился — окно
не трогаем.

### Конфигурация каналов

```python
channels={
    "ch_name": {
        "type": "file",          # только "file" поддерживается сейчас
        "file_path": "logs/metrics.jsonl",
        "format": "json",        # "json" или "csv"
        "enabled": True,
    }
}
```

Если channels пустой И enable_logging=False, создаётся `file_stats` fallback-канал
в `logs/stats_{manager_name}.json`.

### Dict at Boundary

Конструктор принимает `config` в трёх форматах:

```python
StatsManager(config=None)                       # дефолтный конфиг
StatsManager(config={"flush_interval": 30.0})   # dict
StatsManager(config=StatsManagerConfig(...))    # SchemaBase с build()
```

---

## Команды CommandManager (через StatsAdapter)

`StatsAdapter.setup()` регистрирует команды в `CommandManager`:

```python
process.command_manager.handle_command({"command": "get_metrics"})
process.command_manager.handle_command({"command": "get_metric", "data": {"name": "ops.count"}})
process.command_manager.handle_command({"command": "reset_metrics"})
process.command_manager.handle_command({"command": "stats_snapshot"})
process.command_manager.handle_command({"command": "flush_stats"})
```

| Команда | data | Результат |
|---|---|---|
| `get_metrics` | — | `Dict[str, Dict]` все метрики |
| `get_metric` | `{"name": "..."}` | `Dict` одна метрика |
| `reset_metrics` | — | сброс live-метрик |
| `stats_snapshot` | — | `get_stats()` полная диагностика |
| `flush_stats` | — | принудительный flush |

---

## Формат снапшота

`AggregationWindow` формирует снапшот при каждом flush:

```json
{
    "timestamp": 1710000000.0,
    "total_count": 3,
    "bucket_bounds": [0.0001, 0.00025, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.017, 0.034, 0.05, 0.1, 0.25, 1.0],
    "metrics": [
        {"name": "ops.count", "type": "counter", "tags": {"env": "prod"}, "count": 42.0},
        {"name": "req.duration", "type": "timing", "tags": {}, "count": 5, "min": 0.01, "max": 0.5, "avg": 0.12, "p95": 0.5,
         "sum": 0.6, "buckets": [0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 0, 0, 1, 0]},
        {"name": "mem.used", "type": "gauge", "tags": {}, "value": 1024.0}
    ]
}
```

Что важно знать про эту форму (ADR-SM-011):

- **`total_count` — сколько СЕРИЙ было в окне**, а не сколько доехало. Разность с
  `len(metrics)` — число РАЗЛИЧНЫХ серий, опущенных потолком кардинальности; при ненулевом
  отказе рядом появляются `series_dropped` (различные серии), `observations_dropped`
  (сколько эмиссий при этом отвергнуто — другое число: одну отказанную серию эмитент шлёт
  снова и снова) и `dropped_series` (первые 5 РАЗЛИЧНЫХ имён).
- **`series_dropped_is_lower_bound: true`** появляется, когда множество отказанных ключей
  само упёрлось в `max_series`. Тогда `series_dropped` — оценка СНИЗУ, и это сказано
  признаком, а не подразумевается: заниженное число без пометки читается как точное.
- **`bucket_bounds` едут ОДИН раз на снапшот** и только если в нём есть хоть одна
  timing/histogram-метрика. Границы — семантика `le` (`≤`), единица — СЕКУНДЫ, справа
  неявный `+Inf` (поэтому счётчиков на один больше, чем границ). В каждой записи границы
  стоили бы байт на дороге с пределом строки 2048. Три первые границы —
  под-миллисекундные: все сегодняшние боевые тайминги микросекундные (99.28 % наблюдений
  ложились ниже 1 мс), и сетка, начинавшаяся с 1 мс, вырождала перцентиль в максимум.
- **`count`/`min`/`max`/`avg` точные, `p95` — ОЦЕНКА по бакету** (верхняя граница первого
  бакета, где накоплено `≥ ceil(0.95·count)`, зажатая сверху настоящим `max`). Инвариант
  `min ≤ p95 ≤ max` держится всегда.
- `nan_dropped` появляется только ненулевым: NaN-наблюдения отбрасываются со счётом, иначе
  одно такое значение навсегда отравило бы `sum`/`min`/`max` серии.

---

## Структура модуля

```
statistics_module/
├── __init__.py                  # StatsManager, StatsManagerConfig, IStatsManager, ...
├── interfaces.py                # IStatsManager(IChannelRoutingManager)
├── README.md
├── STATUS.md
├── configs/
│   └── stats_config.py          # StatsManagerConfig(ChannelRoutingConfig) @register_schema
├── core/
│   ├── stats_manager.py         # StatsManager(ChannelRoutingManager, IStatsManager)
│   ├── metric_record.py         # MetricRecord dataclass + DEFAULT_DURATION_BUCKETS_SEC
│   ├── cardinality_guard.py     # CardinalityGuard — потолок серий, ОДИН на две позиции
│   └── aggregation_window.py    # AggregationWindow(IBufferStrategy)
├── channels/
│   ├── log_stats_channel.py     # IChannel → LoggerManager.performance()
│   ├── hub_stats_channel.py     # IChannel → stats-слот ObservabilityHub (2.1)
│   └── file_stats_channel.py    # IChannel → JSON/CSV файл
├── adapters/
│   └── stats_adapter.py         # StatsAdapter(BaseAdapter) → CommandManager
├── observation/
│   └── observation_manager.py   # ObservationManager — порт уровней, слот `observation` (ADR-SM-012)
└── tests/
    ├── test_stats_manager.py    # lifecycle, метрики, теги, N-count, flush
    ├── test_stats_integration.py # каналы, get_metric+tags, thread-safety
    ├── test_stats_adapter.py     # CommandManager registration
    ├── test_aggregation_window.py
    ├── test_observation_port_hazards.py  # hazard'ы порта наблюдений (ADR-SM-012)
    └── test_stats_config.py
```

---

## Второй житель модуля: порт наблюдений (`observation/`, ADR-SM-012)

Модуль держит **две плоскости метрик, а не одну**, и они соседи по оси, а не слои друг друга
(ADR-PM-038):

| | `StatsManager` (агрегат) | `ObservationManager` (уровни) |
|---|---|---|
| Вопрос | «сколько было за окно» | «сколько СЕЙЧАС» |
| Хранение | `AggregationWindow` + live-слой, история в сторе | одно значение на имя, перезапись, без истории |
| Адрес | серия метрики (`name` + теги) | лист дерева `state.plugins.<писатель>.<имя>` |
| Кто публикует | сам менеджер, по своему темпу flush | тик `ProcessHeartbeat`, под publisher-гейтом |
| Фасад плагина | `ctx.gauge` / `record_metric` / `record_timing` | `ctx.publish_metric` / `declare_metric` |

`ObservationManager(ChannelRoutingManager, ObservationPort)` — четвёртый канонический слот
`observation` рядом с logger/stats/error, регистрируется в `ProcessManagers.register_all`
**безусловно**. Хранилище (`PluginLevels`) он **оборачивает**, а не заводит: живёт оно
по-прежнему в `process_module/heartbeat/telemetry.py` и остаётся атрибутом процесса — порт
резолвит его на каждом обращении, поэтому держатель один и разъехаться не с чем.

```python
port = process.get_manager("observation")
port.for_plugin("capture").publish("fps", 30.0)   # identity — у хендла, не в аргументе
port.collect_subtree(allowed_metrics)             # то, что тик кладёт в дерево
port.departed_writers()                           # чьи поддеревья положено снять (Ф2)
```

Читателю, у которого может не быть слота (шаг тика, дубль сервисов), дорога одна —
`observation_port(services)`: слот, а при его отсутствии короткоживущий вид над тем же
хранилищем. Флаг `create` разделяет читателя (`False` — тик не заводит хранилище) и писателя
(`True` — публикация из `configure()` идёт раньше, чем у процесса созданы менеджеры; это
**named-фолбэк**, а не костыль).

Флаг действует до КОНЦА дороги, а не до резолвера: со ступени «слот» возвращается менеджер, и
решение о создании принимает уже он — `ObservationManager.levels(create=…)`. Следствие, за
которое читатель платит: `levels()` может вернуть `None`, и каждая читательская дорога отвечает
пустой проекцией своей формы (`set()` / `{}` / `()` / no-op), а не отказом. Заводит хранилище
РОВНО ОДНА дорога — `publish`; `retract` этого не делает, иначе остановка плагина, ни разу
ничего не опубликовавшего, оставляла бы разный след со слотом и без него.

Границы: в `observation/` нет ни агрегации, ни каналов — записи в хаб наблюдаемости
(`kind=observation`) приносит задача 3.2, а `AggregationWindow` остаётся у `StatsManager` и
никуда не переезжает.

---

## Границы модуля

**Модуль отвечает за агрегацию. Транспорт и персистентность — не его** (ADR-SM-007, ADR-CRM-009).
Три следствия, которые надо знать до того, как искать метрики не там:

1. **Снапшот физически ложится туда, куда ведёт скоуп `PERFORMANCE`.** `LogStatsChannel` зовёт
   `LoggerManager.performance()`, а дефолтная раскладка отправляет `PERFORMANCE` в
   `performance.log` (Ф2.6). Строка снапшота была самым тяжёлым источником в системе: замер
   2026-08-03 — 5.27 МБ из 9.38 МБ `system.log` у ProcessManager до выноса в свой файл, и вынос
   **не уменьшил** суммарную запись на диск ни на байт. С задачи 3.4 объём строки ограничен
   ручкой `log_line_max_bytes` (по умолчанию 2048 байт, `0` — без предела): метрики сверх
   бюджета опускаются, и сколько именно — сказано в самой записи. Потолок фона — 1.24 МиБ/ч
   против прежних 2.6–5.5. Полная детализация вернётся с доставкой `kind=stats` в стор
   (этап 6) — см. **ADR-SM-009** и пункт 2 ниже.
2. **В `ObservabilityStore` статистика ПИШЕТСЯ — с задачи 2.1** (2026-08-13, ADR-SM-010 +
   ADR-CRM-015). Канал `hub_stats` кладёт снапшот окна в stats-слот `ObservabilityHub`, и
   существующий дренаж доносит его до стора и живых хвостов: в сторе `kind=stats` было
   структурно `0`, стало 63 записи за 142 с на живом стенде. Метрики едут в `extra`
   структурно, имена — в `message` (по нему работает поиск). До этого здесь стояло «не
   пишется, открытая задача C1»; решение Р-2 исполнено.
3. **Stats-разъём у плагина ЕСТЬ — с задачи 1.1** (ADR-PM-033): `IProcessServices` /
   `PluginContext` / `SubPluginContext` несут четвёрку `record_metric`/`gauge`/`record_timing`/
   `histogram` с сигнатурами `StatsManager` один-в-один (тайминги — в СЕКУНДАХ). Первый боевой
   эмитент — `CapturePlugin`. Массовая миграция ~30 плагинов идёт по мере касания.

**Порядок останова:** плоскость гасится **раньше логгера** — её канал пишет через него, и обратный
порядок отправил бы финальный снапшот в закрытый приёмник (B3). Факт гашения виден строкой
`observability planes stopped: …`, которая называет фактически погашенное.

**Readback отвечает плоскость, а не её конфиг.** `observability_readback()` отдаёт темп из живого
окна, `enable_logging` — из живого реестра каналов (логгер мог не подняться, канал мог быть снят
оператором — из конфига обе ситуации выглядят одинаково). До B1 ветка readback'а stats
**не исполнялась ни разу**: она сторожилась `getattr(stats, "config")`, а этого атрибута у
`StatsManager` нет — его ставит `LoggerCore`, общий предок логгера и ошибок.

---

## Зависимости

- **Зависит от:** `base_manager`, `channel_routing_module`, `data_schema_module`
- **Использует (опционально):** `logger_module` (LogStatsChannel), `router_module` (межпроцессная отправка)
- **Интегрируется в:** `process_module` (process_managers.py), все менеджеры через `ObservableMixin`

---

## Запуск тестов

```bash
# из каталога modules/
pytest statistics_module/tests/ -v
```
