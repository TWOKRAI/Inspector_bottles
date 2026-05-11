# registry/ — Статус

**Статус:** STABLE.

## Компоненты

| Компонент | Файл | Тесты | Статус |
|-----------|------|-------|--------|
| `SchemaRegistry` (no Singleton) | schema_registry.py | ✅ test_schema_registry.py | Готов |
| `SchemaManager` (legacy alias) | schema_registry.py | ✅ test_schema_manager.py | Готов |
| `register_schema` декоратор | schema_registry.py | ✅ | Готов |
| `get_default_registry` | schema_registry.py | ✅ | Готов |
| `RegistersScanner` | discovery.py | ✅ test_registers_scanner.py | Готов |
| `discover_registers_from_package` | discovery.py | ✅ test_discovery.py | Готов |
| `register_package_schemas` / `register_package_registers` | discovery.py | ✅ | Готов |
| `ProcessRegistersRegistry` (Singleton) | process_registry.py | ✅ test_process_registry.py | Готов |
| `RegistersMeta` | process_registry.py | ✅ | Готов |
| Interfaces (`ISchemaRegistry`, `ISchemaManager`) | interfaces.py | ✅ | Готов (ADR-DS-005) |

## Внешние зависимости

| Зависимость | Тип | Назначение |
|-------------|-----|------------|
| `core/` | внутренний | `SchemaBase`, `FieldMeta` — то, что регистрируется |
| `Pydantic v2` | runtime | через `core/` |

## Потребители

- 74 импорта `register_schema` (вторая по популярности фасадная функция модуля)
- 4 импорта `SchemaRegistry` (низкий — большинство ходит через декоратор)
- 2 импорта `get_default_registry`
- `ProcessRegistersRegistry` — используется в `multiprocess_prototype/registers/` для глобального бутстрапа

## Известные TODO

- [ ] Версионированный реестр (`SchemaRegistry` с версионированием схем) — обсуждалось, не реализовано.
- [ ] Кэш на уровне discovery (currently rglob каждый раз).
