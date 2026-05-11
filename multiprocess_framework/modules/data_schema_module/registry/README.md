# registry/ — Реестр схем

Регистрирует, хранит и находит классы схем по строковому имени. Используется для discovery, auto-wire, маршрутизации.

`registry/` — **application layer** модуля. Зависит только от `core/`.

## Публичный API

```python
from multiprocess_framework.modules.data_schema_module import (
    SchemaRegistry,                  # реестр (без Singleton)
    SchemaManager,                   # legacy alias
    register_schema,                 # @-декоратор регистрации
    get_default_registry,            # глобальный экземпляр-singleton accessor

    # Discovery: автообнаружение SchemaBase-наследников
    RegistersScanner,
    discover_registers_from_package,
    register_package_schemas,
    register_package_registers,
)

# Реализованный контракт
from multiprocess_framework.modules.data_schema_module.interfaces import (
    ISchemaRegistry,    # SchemaRegistry-канон (get/has)
    ISchemaManager,     # legacy ABC (get_schema/has_schema)
)
```

## Паттерн использования

```python
from multiprocess_framework.modules.data_schema_module import SchemaBase, register_schema

# Декоратор регистрирует в default registry
@register_schema("processing")
class ProcessingRegister(SchemaBase):
    threshold: float = 0.5

# Получить экземпляр default registry (НЕ Singleton — для тестов создавайте свой)
from multiprocess_framework.modules.data_schema_module import get_default_registry
registry = get_default_registry()
ProcessingClass = registry.get("processing")
```

## Состав

| Файл | Содержимое |
|------|------------|
| `schema_registry.py` | `SchemaRegistry`, `SchemaManager` (alias), `register_schema`, `get_default_registry` |
| `discovery.py` | `RegistersScanner`, `discover_registers_from_package`, `register_package_*` |
| `process_registry.py` | `ProcessRegistersRegistry` (Singleton реестр `RegistersContainer` по процессам), `RegistersMeta` |
| `interfaces.py` | `ISchemaRegistry`, `ISchemaManager` (ADR-DS-005) |

## ADR

- **No Singleton для SchemaRegistry** (ADR-DS-2.0): `_default_registry = SchemaRegistry()` + accessor `get_default_registry()`. В тестах создавайте `SchemaRegistry()` напрямую для изоляции.
- **ProcessRegistersRegistry — Singleton** (отдельная история): реестр контейнеров по имени процесса, инициализируется один раз на старт системы.

См. [STATUS.md](STATUS.md), [interfaces.py](interfaces.py), [data_schema_module/README.md](../README.md).
