# STATUS — database

- **Состояние:** Phase 2 (Task 2.1–2.2) — DONE. Миграция `sqlite3` → `SQLManager` завершена.
- **Контракт:** impl-only (рефактор хранилища, публичный контракт плагина сохранён).
- **План:** `plans/2026-06-04_telemetry-db-sink.md` (Phase 2).

## Реализовано (Task 2.1 — DetectionSchema + SQLManager)

- [x] `DetectionSchema(SchemaBase + SQLMeta)` (`schemas.py`) — повторяет колонки `detections`
      (id/timestamp/frame_id/camera_id/event_type/data/created_at), `indexes=[(timestamp,),(event_type,)]`.
- [x] `plugin.py`: убран `import sqlite3` и ручной `CREATE TABLE`; `SQLManager` в `start()`
      (fork-safe, NullPool, `check_same_thread=False`), `create_tables([DetectionSchema])` (auto-DDL).
- [x] `_do_flush` → `repo.insert_many([DetectionSchema(...)])`; fallback one-by-one сохранён.
- [x] `created_at` проставляется в коде (`time.time()`), не SQL-default.
- [x] `shutdown()` → `self._sql.shutdown()`.
- [x] Контракт не изменён: `process(items)` pass-through, register-поля и команды те же.

## Реализовано (Task 2.2 — тесты под SQLManager)

- [x] `tests/test_database_plugin.py` переведён на in-memory `SQLManager` (StaticPool),
      raw sqlite3-mock убран.
- [x] Покрыто: configure (defaults/custom, `_sql is None` после configure), schema/DDL,
      process/буфер, batch-flush на threshold, flush в БД, пустой буфер, `created_at` в коде,
      fallback one-by-one, подсчёт ошибок строки, команды (flush/get_stats/set_batch_size/reset_stats).

## Проверки

- [x] `pytest Plugins/io/database/tests` — 17 passed.
- [x] `ruff check` + `pyright` — чисто (0/0).
- [x] sentrux `check_rules` — нет нарушения слоёв (Plugins→Services OK, нет Plugins→prototype).
      Единственное предупреждение `min_depth` — пред­существующая глобальная метрика, не связана с правкой.
- [x] On-disk smoke: `start()`→`process()`→`flush` пишет строку (id autoincrement, created_at set), `shutdown()` закрывает SQLManager.

## Отложено (Phase 3)

- Task 3.1 — формальные pytest sink+плагин (плагин уже покрыт здесь).
- Task 3.2 — headless/qt-mcp приёмка реальной записи `detections` на живой сборке
      (unit-тесты не доказывают реальную сборку процесса — `feedback_qt_mcp_smoke_verification`).
