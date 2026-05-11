# core/ — Статус

**Статус:** STABLE (рефакторинг v2.0, 2026-04-09). Zero dependencies layer.

## Компоненты

| Компонент | Файл | Тесты | Статус |
|-----------|------|-------|--------|
| `SchemaBase` / `RegisterBase` | schema_base.py | ✅ test_schema_base.py | Готов |
| `SchemaMixin` / `RegisterMixin` | schema_mixin.py | ✅ | Готов |
| `FieldMeta` | field_meta.py | ✅ test_field_meta.py (40+ тестов) | Готов |
| `FieldRouting` | field_routing.py | ✅ (15+ тестов в test_field_meta) | Готов |
| `RegisterDispatchMeta` | register_dispatch.py | ✅ | Готов |
| Field types (Percent/Scale/…) | field_types.py | ✅ test_field_types.py | Готов |
| `DataValidator` | validators.py | ✅ test_validators.py | Готов |
| Helpers | helpers.py | ✅ test_utils.py | Готов |
| References | reference.py | ✅ test_data_reference.py | Готов |
| Exceptions | exceptions.py | ✅ | Готов |
| `MetricsCollector` | metrics.py | ✅ test_metrics.py | Готов |
| Interfaces (`ISchema`, `ISchemaAdapter`, `HasBuild`, `IDataValidator`) | interfaces.py | ✅ | Готов (ADR-DS-005) |

## Внешние зависимости

| Зависимость | Тип | Назначение |
|-------------|-----|------------|
| Pydantic v2 | runtime | Базовые модели + валидация |
| typing | stdlib | Protocol, ABC, type hints |

Других зависимостей нет. `core/` импортируем из любого модуля без opt-in (в отличие от `storage/`, `versioning/`).

## Потребители (по grep на 2026-05-11)

- 113 внешних импортов `SchemaBase` (главный потребитель)
- 84 импорта `FieldMeta`
- 13 импортов `FieldRouting`
- 10 импортов `RegisterDispatchMeta`

Все импорты идут через корневой фасад `from data_schema_module import …` (ADR-DS-006). Прямой импорт `from data_schema_module.core.X import Y` запрещён для public API.

## Известные TODO

- [ ] Очистка модульных кэшей для динамических классов (потенциальная утечка для `register_field_type`).
- [ ] Кастомные валидаторы через декоратор `@validator` (концепция).
