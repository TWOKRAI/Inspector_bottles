# storage/ — Хранение в ProcessData

`StorageManager` — высокоуровневое хранение моделей/компонентов в `ProcessData` (для многопроцессного взаимодействия). `ProcessDataContainer` — обёртка над shared-memory структурой данных.

`storage/` — **infrastructure layer**. **Зависит от `process_module`** — поэтому НЕ импортируется автоматически через корневой `data_schema_module.__init__` (ADR-DS-004). Импортируйте напрямую:

```python
from multiprocess_framework.modules.data_schema_module.storage import StorageManager
```

## Публичный API

```python
from multiprocess_framework.modules.data_schema_module.storage import (
    StorageManager,                  # менеджер компонентов в ProcessData
    FileStorage,                     # re-export из serialization/
    ProcessDataContainer,            # опционально (если process_module доступен)
)

# Контракт
from multiprocess_framework.modules.data_schema_module.interfaces import IStorageManager
```

## Паттерн использования

```python
from multiprocess_framework.modules.data_schema_module.storage import StorageManager
from multiprocess_framework.modules.shared_resources_module import ProcessData

process_data = ProcessData(...)
storage = StorageManager(process_data)

# Регистрация менеджера в ProcessData
storage.register_manager(my_manager_model, process_name="renderer")

# Получение конфига
config = storage.get_manager_config(
    manager_type="theme",
    manager_name="dark",
    key="palette",
    process_name="renderer",
)
```

## Состав

| Файл | Содержимое |
|------|------------|
| `storage_manager.py` | `StorageManager` — фасад API над ProcessData |
| `process_data_container.py` | `ProcessDataContainer` — низкоуровневая обёртка |
| `interfaces.py` | `IStorageManager` Protocol (ADR-DS-005) |

## Зависимость от process_module — почему это в data_schema_module?

`StorageManager` хранит **Pydantic-модели** в `ProcessData`. Это операция «схема ↔ shared-memory» — её домен — это data_schema_module. Но поскольку impl требует `process_module`, она вынесена в `storage/` без автоматического импорта в корневой `__init__.py` (ADR-DS-004 «extensions — только явный импорт»). `core/` остаётся zero-dependency.

См. [STATUS.md](STATUS.md), [interfaces.py](interfaces.py), [framework/DECISIONS.md ADR-DS-004](../DECISIONS.md).
