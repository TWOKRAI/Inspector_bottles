# versioning/ — Статус

**Статус:** STABLE.

## Компоненты

| Компонент | Файл | Тесты | Статус |
|-----------|------|-------|--------|
| `VersionManager` | version_manager.py | ✅ test_version_manager.py (10+) | Готов |
| `VersionInfo` | version_manager.py | ✅ | Готов |
| `IVersionManager` ABC | interfaces.py | ✅ | Готов (ADR-DS-005) |

## Внешние зависимости

| Зависимость | Тип | Назначение |
|-------------|-----|------------|
| `core/` | внутренний | `SchemaBase` |
| `models/` | внутренний | `BaseManagerModel` |
| `storage/` | внутренний | `IStorageManager` — хранение версий |
| `process_module` | **внешний** | `ProcessData` |
| `config_module` | **внешний** | сравнение конфигов |

## Потребители

- 4 импорта `VersionManager` (через `extensions/versioning`)
- 2 импорта `VersionInfo`

## Известные TODO

- [ ] Интеграция с `SchemaRegistry` — версионированный реестр.
- [ ] Auto-tag по семвер (major/minor/patch detection).
- [ ] Compression для history blob'ов.
