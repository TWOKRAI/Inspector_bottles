# telemetry_sink — сток истории телеметрии

Side-effect плагин: подписывается на дерево StateStore (`processes.**`) через тот же
IPC-механизм `state.subscribe`, что и GUI, по таймеру семплит снимок кэша подписки и
батчево пишет историю метрик в SQLite через `Services/sql` (`SQLManager`).

I/O изолирован в собственном процессе (`GenericProcessApp`) — не подвешивает
`ProcessMonitor`, framework не трогается.

## Поток данных

```
StateStoreManager --state.changed--> ctx.state_proxy.subscribe callback
    --> self._cache[path] = value          (только запись в кэш, без I/O)
loop-worker (sample_interval_sec)
    --> снимок _cache --> TelemetrySnapshot[] --> repo.insert_many (sync)
```

- Callback подписки **только** кладёт листья в `self._cache: dict[path, value]`.
- Запись в БД — на таймере (loop-worker), а не на каждую дельту.

## Параметры (registers.py)

| Поле | Default | Назначение |
|------|---------|-----------|
| `db_path` | `data/telemetry.db` | Путь к SQLite-файлу истории |
| `sample_interval_sec` | `5.0` | Период снятия снимка кэша (мин. 0.5) |

## Схема (schemas.py)

`TelemetrySnapshot` (wide-таблица, `telemetry_snapshots`) — минимальный slice
(Task 1.1): `id` (autoincrement PK), `ts`, `process_name`, `fps`.
Индексы: `(ts)`, `(process_name, ts)`.

Расширение до полного набора (`latency_ms`, `uptime_s`, `status`, `extra`) и
system-сводка — Task 1.2; команды (`flush`/`get_stats`/`purge_old`) и
retention — Task 1.3.

## Fork-safety (КРИТИЧНО)

`SQLManager` создаётся и `initialize()`/`create_tables()` вызываются **внутри**
`start()` — после `fork` дочернего процесса, НЕ в `configure()`. Конфиг:
`fork_safe=True` (NullPool) + `connect_args={"check_same_thread": False}`
(subscribe-callback и sample-worker — разные потоки одного процесса). Запись — SYNC.

## Слои

`Plugins → Services` (разрешён). Плагин знает только `PluginContext`, НЕ импортирует
`multiprocess_prototype.*`. Импорт SQL — только `from Services.sql import SQLManager,
SQLManagerConfig`.

## Запуск

Объявлен в `multiprocess_prototype/backend/topology/telemetry_sink.yaml` как процесс
`telemetry_sink` (демо: камера-симулятор → сток, запускается headless). Обнаруживается
`PluginRegistry.discover` (путь `Plugins` в `discovery.plugin_paths`).
