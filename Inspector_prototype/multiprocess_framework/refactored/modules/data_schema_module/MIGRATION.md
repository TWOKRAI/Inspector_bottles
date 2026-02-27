# Миграция data_schema

Модуль перенесён из `Shared_resources_module/data_schema/` в `refactored/modules/data_schema_module/`.

**Импорт:**
```python
from multiprocess_framework.refactored.modules.data_schema_module import (
    SchemaManager, StorageManager, ModelFactory, FieldSchema,
    register_package_registers, registers_to_dict, registers_from_dict,
)
```

Подробнее: [README.md](README.md), [docs/STRUCTURE.md](docs/STRUCTURE.md).
