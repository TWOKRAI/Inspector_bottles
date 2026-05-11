# container/ — Статус

**Статус:** STABLE.

## Компоненты

| Компонент | Файл | Тесты | Статус |
|-----------|------|-------|--------|
| `RegistersContainer` | registers_container.py | ✅ test_container.py (35+ тестов) | Готов |
| `config_to_dict` | config_converters.py | ✅ test_config_converters.py (20+) | Готов |
| `configs_to_dicts` | config_converters.py | ✅ | Готов |
| `build_process_with_workers` | config_converters.py | ✅ (15+) | Готов |
| `process` (alias) | config_converters.py | ✅ | Готов |

## Внешние зависимости

| Зависимость | Тип | Назначение |
|-------------|-----|------------|
| `core/` | внутренний | `SchemaBase`, `HasBuild` Protocol |

## Потребители

- 10 импортов `process` (главный потребитель в прототипе для add_process)
- 2 импорта `RegistersContainer`
- 2 импорта `build_process_with_workers`
- 1 импорт `config_to_dict`
