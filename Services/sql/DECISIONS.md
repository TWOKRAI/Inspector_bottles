# sql_module — Архитектурные решения

> Ссылки: [`../../DECISIONS.md`](../../DECISIONS.md)

## ADR-SQL-001: Двойной доступ (sync/async) через адаптеры

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** Фреймворк требует одновременно sync и async доступ к БД для разных типов процессов. Альтернатива: един синхронный интерфейс.
- **Решение:** Отдельные протоколы `ISyncEngineAdapter` / `IAsyncEngineAdapter`. Async-адаптер создаётся лениво при первом вызове `uow_async()`.
- **Последствия:** Нет оверхеда для sync-only процессов. Оба режима используют одну конфигурацию.

## ADR-SQL-002: Fork-safety с NullPool

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** Фреймворк форкирует процессы — пулы соединений deadlock на fork. Альтернатива: использовать QueuePool с опциями.
- **Решение:** Детект `INSPECTOR_MULTIPROCESS` env или `config.fork_safe` → используется SQLAlchemy `NullPool`.
- **Последствия:** Каждая операция создаёт новое соединение (малый оверхед), но нет deadlock'ов при fork.

## ADR-SQL-003: SchemaBaseMapper как заменяемый плагин (ISchemaMapper)

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** Разные проекты могут требовать custom mapping schema → SQL. Альтернатива: вшить `SchemaBaseMapper` в ядро.
- **Решение:** Protocol-based `ISchemaMapper`. Default: `SchemaBaseMapper`. Может быть заменён в конфиге.
- **Последствия:** Расширяемость без изменения ядра модуля.

## ADR-SQL-004: Удаление IMetricsCollector в пользу ObservableMixin

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** `IMetricsCollector` и `SQLMetricsCollector` — мёртвый код, никогда не используются. `ObservableMixin` (`_record_timing`, `_log_info`, `_track_error`) покрывает всю наблюдаемость.
- **Решение:** Удалить пакет `metrics/` и протокол `IMetricsCollector`.
- **Последствия:** Чистая кодовая база, единая path наблюдаемости.

## ADR-SQL-005: SQLMeta как вложенный ClassVar

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** Нужны метаданные таблицы (table_name, indexes, unique_together) без модификации `SchemaBase`. Альтернатива: добавить в `data_schema_module`.
- **Решение:** `SQLMeta` — простой вложенный класс внутри подклассов `SchemaBase`. Живёт в `sql_module`, не в `data_schema_module`. Pydantic игнорирует вложенные классы.
- **Последствия:** `SchemaBase` не тронут, `sql_module` обогащен.

## ADR-SQL-006: SchemaBaseMapper читает FieldMeta

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** `SchemaBaseMapper` раньше игнорировал `FieldMeta` (min/max, readonly). Неиспользуемые метаданные.
- **Решение:** Читать ограничения `FieldMeta`: min/max → `CHECK`, максимум на str → `VARCHAR(N)`, флаг readonly.
- **Последствия:** Более богатая DDL-генерация, защита readonly полей в репозитории.

## ADR-SQL-007: Автоматическая DDL через DDLBuilder

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** Таблицы создавались вручную raw SQL. Альтернатива: Alembic, но он требует схемы.
- **Решение:** `DDLBuilder` читает вывод `schema_to_table_meta()` → генерирует `CREATE TABLE IF NOT EXISTS` с CHECK, DEFAULT, индексами, UNIQUE. Поддерживает SQLite/PostgreSQL/MySQL.
- **Последствия:** One-line создание таблиц: `sql_manager.create_tables([Schema1, Schema2])`.

## ADR-SQL-008: QuerySet builder (Django-style)

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** Все запросы требовали raw SQL строки — ошибкоопасно, без type safety. Альтернатива: использовать SQLAlchemy ORM.
- **Решение:** Immutable `QuerySet` с chained API: `.filter()` / `.exclude()` / `.order_by()` / `.limit()`. Все значения параметризованы. Lookups: eq, ne, gt, gte, lt, lte, in, like, isnull.
- **Последствия:** Безопасные, читаемые запросы. Dict at Boundary через `.values()`.

## ADR-SQL-009: Защита readonly полей в Repository

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** `FieldMeta.readonly` должен предотвращать изменение поля через SQL. Альтернатива: rely на приложение.
- **Решение:** `GenericRepository.update()` молча исключает readonly поля из `SET` clause.
- **Последствия:** Целостность данных — readonly поля не могут быть случайно изменены.

## ADR-SQL-010: Валидация идентификаторов в query_range()

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** `query_range()` использовал f-string для таблицы/order_by — SQL injection risk. Альтернатива: всё параметризовать.
- **Решение:** Regex whitelist `^[a-zA-Z_][a-zA-Z0-9_]*$` + `ValueError` на несовпадение.
- **Последствия:** Защита от SQL injection в legacy методе.

## ADR-SQL-011: UnitOfWork делегирует адаптеру управление транзакцией

- **Дата:** 2026-04-12
- **Статус:** принято
- **Контекст:** Методы `commit()` / `rollback()` в UoW — no-ops, confusing для пользователей. Альтернатива: реализовать полноценное управление.
- **Решение:** Ясно документировать: UoW делегирует управление транзакциями адаптеру через context manager `adapter.connection()`. Stub-методы `commit()` / `rollback()` существуют для совместимости с Protocol.
- **Последствия:** Ясные ожидания, следует SQLAlchemy 2.0 BEGIN pattern.
