# extensions/ — Статус

**Статус:** STABLE (изолятор зависимостей, ADR-DS-004).

Не содержит собственной логики — только re-export.

## Содержимое

| Файл | Re-export для | Тесты |
|------|------------|-------|
| `__init__.py` | docstring + usage examples | — |
| `factory/__init__.py` | `factory.ModelFactory` | ✅ через `factory/tests/` |
| `models/__init__.py` | `models.{BaseComponentModel, ComponentDNA, …}` | ✅ через `tests/extensions/test_models.py` |
| `tools/__init__.py` | `tools.{SchemaVisualizer, SchemaDocumentationGenerator, форматеры}` | ✅ через `tools/tests/` |
| `versioning.py` | `versioning.VersionManager` | ✅ через `tests/extensions/test_versioning.py` |
| `simple_api.py` | `api.simple_api.{create_config, get_config, …}` | ✅ через `api/tests/` |
| `manager_adapter.py` | `api.manager_adapter.ManagerDataAdapter` | ✅ |
| `metrics.py` | `core.metrics.MetricsCollector` | ✅ через `core/tests/test_metrics.py` |

## Внешние зависимости

Сам `extensions/` ничего не импортирует, кроме своих re-export'ов. Реальные зависимости — у конкретных подмодулей.

## Принципы (ADR-DS-004)

1. Импорт `extensions/X` не вызывает auto-load других подмодулей (lazy).
2. Реализация всегда в `<subpkg>/`, не в `extensions/`.
3. Канонический путь импорта — `data_schema_module.<subpkg>.X`. `extensions/` — для совместимости.

## Известные TODO

- [ ] Постепенная миграция потребителей с `extensions.*` на канонические пути (`subpkg.*`).
- [ ] Опционально: ADR о deprecation extensions/ через 2-3 версии — если все потребители мигрируют.
