# database — output-плагин записи результатов в SQLite

Output-плагин: `process(items) -> items` (pass-through с side-effect batch-записи в БД).
Хранилище — **Services/sql** (`SQLManager`), таблица `detections` (auto-DDL из `DetectionSchema`).

## Контракт

- **inputs:** `result` (dict) — результат обработки кадра.
- **outputs:** — (pass-through, плагин-сток).
- **register** (`DatabaseRegisters`): `db_path`, `batch_size`, `flush_interval_sec`.
- **commands:** `flush`, `get_stats`, `set_batch_size`, `reset_stats`.

## Поток данных

```
process(items) --> _add_to_buffer (буфер list[dict], lock)
    --> при len >= batch_size: _do_flush(batch)
db_flush_worker (LOOP, flush_interval_sec) --> _flush_buffer --> _do_flush
_do_flush --> repo.insert_many([DetectionSchema(...)])  (fallback one-by-one при ошибке)
```

## Хранилище (Services/sql)

- `SQLManager` создаётся **внутри `start()`** (после fork), `fork_safe=True` (NullPool),
  `connect_args={"check_same_thread": False}` — flush-worker и `process()` в разных потоках.
- Таблица создаётся через `create_tables([DetectionSchema])` (auto-DDL), не ручным SQL.
- `created_at` проставляется в коде (`time.time()` при flush) — SQL-default `unixepoch`
  не переносится в DDLBuilder.

Тот же fork-safe паттерн, что у `telemetry_sink`.

## Тесты

`tests/test_database_plugin.py` — in-memory `SQLManager` (StaticPool): configure, schema/DDL,
process/буфер, flush, fallback one-by-one, команды.
