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

## Fix-forward: контракт входного порта (pre-existing дефект)

Вход `result` был объявлен `dtype="dict", shape="(*,)"` — shape-несовместим с ЕДИНСТВЕННЫМ
`dict`-производителем в кодовой базе (`robot_control.inspection_result` — `dict "1"`). Значит вход
был **неудовлетворим**: плагин нельзя было развести ни в одной валидной топологии (port-валидация
`SystemBlueprint.check()` падала). Это вскрылось при попытке живого запуска (Task 3.2), к миграции
sqlite3→SQLManager отношения не имеет (строка `inputs` была идентична в исходнике).

Правка: `shape="(*,)"` → `"1"` (один dict на сообщение, как и отдаёт `robot_control`). Регрессия
закрыта тестом `TestPortContract.test_result_input_wireable_from_robot_control`.

> Замечание: `inspection_full.yaml` (единственная не-archive топология с `database`) **устаревшая** —
> в ней нет секции `wires:` (только `chain_targets`), поэтому port-валидация её отвергает. Привести
> её к рабочему `wires:`-формату — отдельная задача (вне scope этой миграции).

## Проверки

- [x] `pytest Plugins/io/database/tests` — 18 passed.
- [x] `ruff check` + `pyright` — чисто (0/0).
- [x] sentrux `check_rules` — нет нарушения слоёв (Plugins→Services OK, нет Plugins→prototype).
      Единственное предупреждение `min_depth` — пред­существующая глобальная метрика, не связана с правкой.
- [x] On-disk smoke: `start()`→`process()`→`flush` пишет строку (id autoincrement, created_at set), `shutdown()` закрывает SQLManager.
- [x] **Live headless-proof (Task 3.2):** временная wired-топология
      `camera_service→hsv_mask→contour_finder→robot_control→database`, 15 с работы →
      **318 строк в `detections`** (318 разных `timestamp`, `frame_id` инкрементируется,
      `created_at` проставлен в коде). Плагин реально discover-ится и пишет в живом дочернем
      процессе `GenericProcessApp`. shutdown отработал чисто (без осиротевших процессов).

## Отложено (Phase 3)

- Task 3.1 — формальные pytest sink (плагин database уже покрыт здесь; 18 passed).
- Task 3.2 (sink-ветка) — headless-приёмка `telemetry_snapshots` (ветка database закрыта live-proof выше).
- Привести `inspection_full.yaml` к `wires:`-формату (отдельная задача — устаревшая топология).
