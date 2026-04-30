# Тесты data_schema_module

## Список тестов и покрытые сценарии

| Файл | Компонент | Покрытые сценарии |
|------|-----------|-------------------|
| test_schema_registry.py | SchemaManager | register/get/has/list/unregister, create_instance (дефолты, частичные данные), validate (успех/ошибка), get_defaults, потокобезопасность, **декоратор register_schema**, **validate_recipe** |
| test_field_schema.py | FieldSchema | init+call (overrides), deep_merge (вложенные dict), поле в модели |
| test_registers_io.py | registers_io | to_dict/from_dict, to_json/from_json, **to_yaml/from_yaml**, to_flat_dict/from_flat_dict (prefix) |
| test_register_discovery.py | register_discovery | discover по суффиксу Registers/Data, _class_name_to_key, register_package_registers/register_package_schemas (в т.ч. suffix="Data"), пустой пакет → False |
| test_converters.py | DataConverter | Round-trip dict/json/yaml, convert(), save_to_file/load_from_file |
| test_validators.py | DataValidator | validate, is_valid, get_validation_errors, validate_partial, validate_nested |
| test_utils.py | helpers, reference | get_nested_value, set_nested_value, merge_with_defaults, extract_fields; DataReference, convert_all_references |
| test_factory.py | ModelFactory | create_manager, create, from_dict, дефолты, auto_register (мок), SchemaNotFoundError, SchemaValidationError |
| test_version_manager.py | VersionManager | create_version, get_current_version, get_version, get_version_history, rollback, compare_versions |
| test_schema_visualizer.py | SchemaVisualizer | Форматы text/json/html/mermaid, опции, отсутствующая схема, неподдерживаемый формат |
| test_schema_documentation_generator.py | SchemaDocumentationGenerator | markdown/rst/html, с примерами/без, все схемы, API reference, ошибки |

Подробная матрица и оценка модуля — в [docs/EVALUATION.md](../docs/EVALUATION.md).

## Комментарии в тестах

- В начале каждого файла — **модульный docstring**: какие сценарии покрыты.
- У каждой тест-функции — **docstring**: что проверяет тест (одной фразой).
- Крупные блоки можно выделять секциями (`# === Тестовые модели ===` и т.п.).

## Запуск

**Рекомендуемый способ** — из каталога `refactored/modules`:

```bash
cd multiprocess_framework/modules
pytest data_schema_module/tests/ -v
```

**Альтернативный способ** — с явным PYTHONPATH из корня проекта:

```bash

$env:PYTHONPATH = "multiprocess_framework/modules"
python -m pytest multiprocess_framework/modules/data_schema_module/tests/ -v
```

### Запуск отдельных тестов

```bash
# Из refactored/modules
pytest data_schema_module/tests/test_field_schema.py data_schema_module/tests/test_registers_io.py -v

# С подробным выводом ошибок
pytest data_schema_module/tests/ -v --tb=short

# Только быстрые тесты (без version_manager, tools)
pytest data_schema_module/tests/test_field_schema.py data_schema_module/tests/test_registers_io.py data_schema_module/tests/test_register_discovery.py data_schema_module/tests/test_schema_registry.py -v
```

### Примечание

Для корректной работы тестов `multiprocess_framework/__init__.py` должен иметь опциональные импорты (обёрнутые в `try/except ImportError`), чтобы избежать ошибок при отсутствии модулей из старой структуры. Это уже исправлено в текущей версии.

## Фикстуры

- **tests/fixtures/** — пакет с классами `TestRegisters(BaseModel)` и `TestData(BaseModel)` для тестов register_discovery (discover по суффиксам Registers и Data).
