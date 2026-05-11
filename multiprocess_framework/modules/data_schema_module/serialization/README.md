# serialization/ — Сериализация моделей

Конвертация Pydantic-моделей в dict/JSON/YAML и обратно. Файловое хранилище для `RegistersContainer`.

`serialization/` — **application layer**. Зависит только от `core/` + Pydantic + опционально PyYAML.

## Публичный API

```python
from multiprocess_framework.modules.data_schema_module import (
    # Конвертер моделей
    DataConverter,
    FormatType,                      # enum: DICT / JSON / YAML / FLAT_DICT

    # Функции IO для RegistersContainer
    registers_to_dict, registers_from_dict,
    registers_to_json, registers_from_json,
    registers_to_yaml, registers_from_yaml,
    registers_to_flat_dict, registers_from_flat_dict,

    # Файловое хранилище (реализует ISchemaStorage)
    FileStorage,
)

# Контракты
from multiprocess_framework.modules.data_schema_module.interfaces import (
    IDataConverter,
    ISchemaStorage,                  # bynchron storage protocol
    IAsyncSchemaStorage,             # async-версия
    IRegisterStorage,                # legacy alias
    IAsyncRegisterStorage,           # legacy alias
)
```

## Паттерн использования

```python
from multiprocess_framework.modules.data_schema_module import DataConverter, FormatType

converter = DataConverter()
# model → dict
data = converter.model_to_dict(my_model)
# dict → model
my_model = converter.dict_to_model(data, MySchema)
# model → JSON
json_str = converter.model_to_json(my_model)

# Файловое хранилище
from multiprocess_framework.modules.data_schema_module import FileStorage
storage = FileStorage(base_path="data/")
storage.save("container_name", {"key": "value"})
data = storage.load("container_name")
```

## Состав

| Файл | Содержимое |
|------|------------|
| `converter.py` | `DataConverter` — Pydantic ↔ dict/JSON; `FormatType` enum |
| `io.py` | Функции `registers_to_*` / `registers_from_*` для контейнеров |
| `file_storage.py` | `FileStorage` — JSON-файлы (реализует `ISchemaStorage`) |
| `interfaces.py` | `IDataConverter`, `ISchemaStorage`, `IAsyncSchemaStorage` + legacy aliases (ADR-DS-005) |

## Расширение

Для нового бэкенда (SQLite, Redis, S3) реализуйте `ISchemaStorage` Protocol:

```python
from multiprocess_framework.modules.data_schema_module.interfaces import ISchemaStorage

class SQLiteStorage:
    def load(self, container_name: str) -> dict: ...
    def save(self, container_name: str, data: dict) -> None: ...
    def exists(self, container_name: str) -> bool: ...
    def delete(self, container_name: str) -> bool: ...
```

См. [STATUS.md](STATUS.md), [interfaces.py](interfaces.py).
