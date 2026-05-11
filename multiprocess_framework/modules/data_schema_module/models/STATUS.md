# models/ — Статус

**Статус:** STABLE.

## Компоненты

| Компонент | Файл | Тесты | Статус |
|-----------|------|-------|--------|
| `BaseComponentModel` | base.py | ✅ tests/extensions/test_models.py | Готов |
| `BaseManagerModel` | base.py | ✅ | Готов |
| `ComponentType` enum | types.py | ✅ | Готов |
| `ComponentDNA` | dna.py | ✅ test_dna.py (20+) | Готов (опц.) |
| `ComponentLocation` | dna.py | ✅ | Готов |
| `ResourceReference` / `ResourceType` | dna.py | ✅ | Готов |
| `ComponentHierarchy` | dna.py | ✅ | Готов |

## Внешние зависимости

| Зависимость | Тип | Назначение |
|-------------|-----|------------|
| `core/` | внутренний | `SchemaBase`, `FieldMeta` |
| Pydantic v2 | runtime | модели |

## Потребители

- 3 импорта `ComponentDNA` (через `extensions/models`)
- Используется в прототипе для описания UI-компонентов и менеджеров.
