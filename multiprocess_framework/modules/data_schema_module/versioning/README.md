# versioning/ — Версионирование моделей

`VersionManager` — создание/откат/diff/история версий моделей в `ProcessData`.

`versioning/` — **application layer**, **зависит от `process_module` и `config_module`**. Используется через `extensions/versioning` (тонкая обёртка, ADR-DS-004).

## Публичный API

```python
from multiprocess_framework.modules.data_schema_module.extensions.versioning import (
    VersionManager,
    VersionInfo,                     # metadata одной версии
)

# Контракт
from multiprocess_framework.modules.data_schema_module.interfaces import IVersionManager
```

## Паттерн использования

```python
from multiprocess_framework.modules.data_schema_module.extensions.versioning import VersionManager

vm = VersionManager(process_data)

# Создать версию
version_id = vm.create_version(
    my_manager_model,
    comment="initial config",
    author="alice",
    tags=["v1", "release"],
)

# История
history = vm.get_version_history(
    manager_type="theme",
    manager_name="dark",
)

# Откат
vm.rollback(
    manager_type="theme",
    manager_name="dark",
    target_version=42,
    create_new_version=True,
    comment="reverted to v42",
)

# Сравнение версий
diff = vm.compare_versions(
    manager_type="theme",
    manager_name="dark",
    version1=42,
    version2=43,
)
```

## Состав

| Файл | Содержимое |
|------|------------|
| `version_manager.py` | `VersionManager` + `VersionInfo` |
| `interfaces.py` | `IVersionManager` ABC (ADR-DS-005) |

## Известные ограничения

- Версионирование не интегрировано с `SchemaRegistry` — реестр сейчас хранит одну версию класса. Концепция «версионированный реестр» обсуждается.

См. [STATUS.md](STATUS.md), [interfaces.py](interfaces.py).
