# core/ — Фундамент data_schema_module

Pydantic-based ядро описания структур данных. Zero dependencies от других модулей фреймворка (только Pydantic v2 + typing).

`core/` — **domain layer** модуля. Любая зависимость от `process_module`, `config_module` и т.п. отсюда запрещена — такие компоненты живут в `storage/`, `versioning/`, `extensions/` (см. ADR-DS-004).

## Публичный API

```python
from multiprocess_framework.modules.data_schema_module import (
    # Базовые классы схем
    SchemaBase, RegisterBase,       # Pydantic-наследник + legacy alias
    SchemaMixin, RegisterMixin,     # mixin с методами get_field_meta/update_field/validate_field

    # Метаданные полей
    FieldMeta,                       # описание поля: default, description, access, validation
    FieldRouting,                    # маршрут изменения поля (process_targets, channel)
    RegisterDispatchMeta,            # метаданные диспатча на уровне регистра

    # Type aliases для FieldMeta
    Percent, NormalizedFloat, Scale, Milliseconds, Seconds, Pixels,
    ImageScale, HsvHue, HsvChannel, NetworkPort, FpsLimit,
    register_field_type, get_field_type,

    # Валидатор данных
    DataValidator,

    # Контракты (Protocol/ABC)
    ISchema, ISchemaAdapter, HasBuild, IDataValidator,

    # Утилиты для вложенных dict
    get_nested_value, set_nested_value, merge_with_defaults,
    extract_fields, get_model_schema,

    # Ссылки между схемами (cross-schema references)
    DataReference, is_reference, convert_reference_to_data, convert_all_references,

    # Исключения
    DataSchemaError, SchemaNotFoundError, SchemaValidationError,
    SchemaRegistrationError, InvalidParameterError, DataManagerError,
    VersionManagerError,
)
```

## Состав

| Файл | Содержимое |
|------|------------|
| `schema_base.py` | `SchemaBase`, `RegisterBase` (alias) |
| `schema_mixin.py` | `SchemaMixin`, `RegisterMixin` (alias) — `get_field_meta`, `update_field`, `validate_field` |
| `field_meta.py` | `FieldMeta` — описание поля |
| `field_routing.py` | `FieldRouting` — маршрут изменений |
| `field_types.py` | Pydantic type aliases (Percent, Scale, ...) |
| `register_dispatch.py` | `RegisterDispatchMeta` |
| `validators.py` | `DataValidator` — валидация по модели |
| `helpers.py` | Утилиты работы с вложенными dict |
| `reference.py` | Cross-schema ссылки |
| `exceptions.py` | Исключения модуля |
| `metrics.py` | `MetricsCollector` — счётчики операций (опц.) |
| `interfaces.py` | Контракты `core/`: `ISchema`, `ISchemaAdapter`, `HasBuild`, `IDataValidator` (ADR-DS-005) |

## Пример

```python
from multiprocess_framework.modules.data_schema_module import SchemaBase, FieldMeta, register_schema

@register_schema("processing")
class ProcessingRegister(SchemaBase):
    threshold: float = FieldMeta(default=0.5, description="Порог отсечки")
    enabled: bool = FieldMeta(default=True)
```

## Расширение

- **Свой field type**: `register_field_type("MyType", lambda v: ...)` — добавить кастомный валидатор.
- **Свой адаптер**: реализуйте `ISchemaAdapter` в потребляющем модуле, не в `core/`.

См. [STATUS.md](STATUS.md), [interfaces.py](interfaces.py), [data_schema_module/README.md](../README.md).
