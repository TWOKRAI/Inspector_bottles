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
- Типы метрик: `counter`, `gauge`, `timing`, `histogram`
- Двойное хранение: `self._metrics` (live-state для `get_metric()`) +
  `AggregationWindow` (буфер для flush в каналы)
- Sentinel-паттерн: `_enqueue_to_buffer` ставит данные в буфер ОДИН раз,
  `_do_flush` транслирует снапшот во ВСЕ зарегистрированные каналы —
  это предотвращает N-кратный счёт при N каналах
- Теги: user tags приоритетнее `default_tags` (`{**defaults, **user}`)

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
stats.record_timing(name, duration, tags=None)   # timing: min/max/avg/p95
stats.gauge(name, value, tags=None)              # gauge: последнее значение
stats.histogram(name, value, tags=None)          # histogram: распределение
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
    "metrics": [
        {"name": "ops.count", "type": "counter", "tags": {"env": "prod"}, "count": 42.0},
        {"name": "req.duration", "type": "timing", "tags": {}, "count": 5, "min": 0.01, "max": 0.5, "avg": 0.1, "p95": 0.45},
        {"name": "mem.used", "type": "gauge", "tags": {}, "value": 1024.0}
    ]
}
```

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
│   ├── metric_record.py         # MetricRecord dataclass (counter, gauge, timing, histogram)
│   └── aggregation_window.py    # AggregationWindow(IBufferStrategy)
├── channels/
│   ├── log_stats_channel.py     # IChannel → LoggerManager.performance()
│   └── file_stats_channel.py    # IChannel → JSON/CSV файл
├── adapters/
│   └── stats_adapter.py         # StatsAdapter(BaseAdapter) → CommandManager
└── tests/
    ├── test_stats_manager.py    # lifecycle, метрики, теги, N-count, flush
    ├── test_stats_integration.py # каналы, get_metric+tags, thread-safety
    ├── test_stats_adapter.py     # CommandManager registration
    ├── test_aggregation_window.py
    └── test_stats_config.py
```

---

## Границы модуля

**Модуль отвечает за агрегацию. Транспорт и персистентность — не его** (ADR-SM-007, ADR-CRM-009).
Три следствия, которые надо знать до того, как искать метрики не там:

1. **Снапшот физически ложится туда, куда ведёт скоуп `PERFORMANCE`.** `LogStatsChannel` зовёт
   `LoggerManager.performance()`, а дефолтная раскладка отправляет `PERFORMANCE` в
   `performance.log` (Ф2.6). Одна строка снапшота весит ~7 КБ, и это самый тяжёлый источник в
   системе: замер 2026-08-03 — 5.27 МБ из 9.38 МБ `system.log` у ProcessManager до выноса в свой
   файл. Вынос **не уменьшил** суммарную запись на диск ни на байт.
2. **В `ObservabilityStore` статистика сегодня не пишется.** `kind=stats` до стора не доезжает
   (в живом сторе `stats=0` при `log=3901`), и это не дефект стора, а **открытая задача C1**:
   развилка Р-2 решена владельцем как «внутрь плана телеметрии первой фазой». Ветку `KIND_STATS`
   в drain трогать нельзя — на ней стоит это решение.
3. **У плагина stats-разъёма нет** — `IProcessServices` не объявляет stats-методов, 0
   использований на ~30 плагинов. Бизнес-числа плагин отдаёт телеметрией (self-publish в дерево
   состояния), а не сюда. Это та же C1.

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
