# storage/ — Статус

**Статус:** STABLE.

## Компоненты

| Компонент | Файл | Тесты | Статус |
|-----------|------|-------|--------|
| `StorageManager` | storage_manager.py | ✅ tests/extensions/test_storage_manager.py (15+) | Готов |
| `FileStorage` (re-export из serialization/) | — | ✅ | Готов |
| `ProcessDataContainer` | process_data_container.py | ✅ | Готов (опц.) |
| `IStorageManager` Protocol | interfaces.py | ✅ | Готов (ADR-DS-005) |

## Внешние зависимости

| Зависимость | Тип | Назначение |
|-------------|-----|------------|
| `core/` | внутренний | базовые типы, `IDataValidator` |
| `models/` | внутренний | `BaseManagerModel` |
| `registry/` | внутренний | `SchemaManager` |
| `process_module` | **внешний** | `ProcessData` — главная причина изоляции в `storage/` |

## Потребители

- 2 прямых импорта `from data_schema_module.storage.storage_manager import StorageManager`
- Используется в `config_module/managers/` (зависит от process_module).
- Из корневого фасада НЕ доступен (ADR-DS-004) — это сознательно.

## Известные TODO

- [ ] Async-API для StorageManager (с `IAsyncSchemaStorage`).
- [ ] Lock-free операции для read-heavy workload'ов.
