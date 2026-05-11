# api/ — Статус

**Статус:** STABLE.

## Компоненты

| Компонент | Файл | Тесты | Статус |
|-----------|------|-------|--------|
| `create_config` | simple_api.py | ✅ | Готов |
| `create_manager_config` | simple_api.py | ✅ | Готов |
| `get_config` | simple_api.py | ✅ | Готов |
| `config_from_dict` | simple_api.py | ✅ | Готов |
| `auto_config` | simple_api.py | ✅ | Готов |
| `ManagerDataAdapter` | manager_adapter.py | ✅ test_manager_adapter.py | Готов |

## Внешние зависимости

| Зависимость | Тип | Назначение |
|-------------|-----|------------|
| `core/` | внутренний | базовые типы |
| `models/` | внутренний | BaseManagerModel |
| `storage/` | внутренний | StorageManager (используется внутри функций) |
| `registry/` | внутренний | SchemaRegistry |

## Потребители

- Через `extensions/simple_api`: 5 импортов (create_*, get_*, auto_*)
- `ManagerDataAdapter` — 2 потребителя в config_module.

## Известные TODO

- [ ] Тесты на `auto_config` — corner cases с приоритетами регистрации.
- [ ] Async-варианты `*_config()` функций.
