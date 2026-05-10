# sql_module — Статус рефакторинга

## Текущий этап: 9 / 9

## Оценки (0-10)

| Критерий | Оценка | Комментарий |
|----------|--------|--------------|
| Код | 8 | Clean Architecture, Protocol + Generic, адаптеры |
| Тесты | 8 | 20 unit-тестов, pytest |
| Документация | 8 | README, interfaces, docstrings |
| Связанность | 8 | Зависит от base_manager, data_schema_module |
| Работоспособность | 9 | Все тесты проходят, sync/async |

**2026-04-03:** В **`sql_module.__init__`** реэкспорт **`SchemaBaseMapper`** (публичный контур вместе с **`ExportFormat`** / **`TableExporter`**, **ADR-115**).

## Чеклист рефакторинга

- [x] Этап 1: interfaces.py, sql_manager_config.py, db_commands.py
- [x] Этап 2: engine_factory (fork-safe), SyncAdapter (PostgreSQL, SQLite)
- [x] Этап 3: SQLManager core, GenericRepository, ISchemaMapper
- [x] Этап 4: Unit of Work (SQLAlchemyUnitOfWork)
- [x] Этап 5: AsyncAdapter (PostgreSQL, SQLite), dual mode
- [x] Этап 6: Typed Commands, execute_command
- [x] Этап 7: Observability (emit_event)
- [x] Этап 8: MySQL адаптеры, unit-тесты, README, STATUS.md
- [x] Этап 9: Auto DDL (create_tables), QuerySet builder, SQLMeta descriptor, Enhanced Repository, Legacy cleanup

## Новые features (этап 9)

- [x] Auto DDL (create_tables) — автоматическое создание таблиц из SchemaBase
- [x] QuerySet builder (Django-style) — filter, exclude, order_by, limit, all, first, count, values, update, delete, lookups
- [x] SQLMeta descriptor (sql_meta.py) — декларативные метаданные таблицы
- [x] Enhanced SchemaBaseMapper (FieldMeta → CHECK, VARCHAR, readonly) — FieldMeta с constraints
- [x] Enhanced Repository (find_by, insert_many, readonly protection) — защита readonly полей
- [x] Legacy cleanup (removed metrics/, fixed async dispose, fixed SQL injection)

## Интеграция с модулями фреймворка

| Модуль | Интеграция |
|--------|------------|
| **logger_module** | `_log_info`, `_log_error` через ObservableMixin |
| **error_module** | `_track_error` при исключениях (execute, query, execute_command, initialize) |
| **statistics_module** | `_record_timing` для db.query.duration, db.execute.duration |
| **data_schema_module** | SchemaBaseMapper поддерживает SchemaBase и Pydantic BaseModel |

## Известные ограничения

| Ограничение | Статус | Примечание |
|-------------|--------|------------|
| **get_repository — только sync** | Зафиксировано | Async UoW реализован (uow_async). get_repository — sync, async-репозиторий — отдельная задача. |
| **AsyncAdapter.dispose()** | Низкий приоритет | При running event loop может потребоваться доработка. |
