# statistics_module

Менеджер статистики и метрик. Наследует `ChannelRoutingManager`, параметризуется через
`data_schema_module`, интегрируется с `logger_module`, `command_module`, `router_module`
через `ObservableMixin` и `StatsAdapter`.

---

## Архитектура и наследование

```
BaseManager + ObservableMixin
        │
        ▼
ChannelRoutingManager  ← базовый класс (каналы, буфер, диспетчер)
        │
        ▼
StatsManager
  ├── AggregationWindow  (IBufferStrategy — агрегация метрик)
  ├── LogStatsChannel    (IChannel → LoggerManager.performance())
  └── FileStatsChannel   (IChannel → JSON/CSV файл)
```

**Что получает StatsManager от ChannelRoutingManager:**
- `_channel_registry` — thread-safe реестр каналов (`IChannel`)
- `_dispatcher` — маршрутизация данных
- `flush()` / `shutdown()` — корректное завершение с финальным flush
- `normalize_config()` — Dict at Boundary (принимает None / dict / SchemaBase)

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

### С router_manager для межпроцессной отправки

```python
stats = StatsManager(
    manager_name="worker_stats",
    config=cfg,
    process=self,
    router_manager=self.router_manager,
    managers={"logger": self.logger_manager},
)
```

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
| `aggregation_interval` | float | `5.0` | Интервал агрегации, сек |
| `flush_interval` | float | `10.0` | Интервал flush в каналы, сек |
| `enable_logging` | bool | `True` | Логировать через LoggerManager |
| `log_level` | str | `"INFO"` | Уровень логирования метрик |
| `default_tags` | Dict | `{}` | Теги по умолчанию (appended к каждой метрике) |
| `retention_seconds` | float | `3600.0` | Время хранения live-метрик в памяти |

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
