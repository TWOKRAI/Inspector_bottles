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
| `retention_days` | `0` | Хранить N дней (0 = без ретенции; чистка по команде `purge_old`) |

## Схема (schemas.py)

`TelemetrySnapshot` (wide-таблица, `telemetry_snapshots`), индексы `(ts)`,
`(process_name, ts)`. Одна строка = снимок одного процесса в момент `ts`:

| Колонка | Источник дерева | Примечание |
|---------|-----------------|-----------|
| `id` | — | autoincrement PK |
| `ts` | `time.time()` | момент снимка |
| `process_name` | `processes.<P>` / `'system'` | строка-сводка имеет `process_name='system'` |
| `fps` | `processes.<P>.state.fps` / `system.health.avg_fps` | |
| `latency_ms` | `processes.<P>.state.latency_ms` | |
| `uptime_s` | `processes.<P>.state.uptime` | |
| `status` | `processes.<P>.state.status` | |
| `extra` | `workers.*`, нестандартный `state.*`, `system.health.*` кроме avg_fps | JSON-хвост |

`config.*` и статика `system.*` (stop_timeout/shm_budget_mb/log_dir) фильтруются.

## Команды

| Команда | Действие |
|---------|----------|
| `flush` | принудительный семпл+запись вне таймера |
| `get_stats` | `total_written`, `pending_leaves`, `db_path`, `last_ts` |
| `purge_old` | при `retention_days>0` — `DELETE WHERE ts < cutoff`; иначе no-op. Scheduled-ротация — вне scope (отдельный /plan) |

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
