# factory/ — Статус

**Статус:** STABLE.

## Компоненты

| Компонент | Файл | Тесты | Статус |
|-----------|------|-------|--------|
| `ModelFactory` | model_factory.py | ✅ tests/test_model_factory.py (10+) | Готов |
| `DNAFactory` | dna_factory.py | ✅ (если доступен) | Готов (опц.) |

## Внешние зависимости

| Зависимость | Тип | Назначение |
|-------------|-----|------------|
| `core/` | внутренний | SchemaBase, FieldMeta |
| Pydantic v2 | runtime | `create_model` (динамика) |

## Потребители

- 2 импорта `ModelFactory` (через `extensions/factory`)
- Используется для генерации схем из конфигов (config-driven flow в прототипе).
