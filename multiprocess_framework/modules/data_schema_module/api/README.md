# api/ — Высокоуровневый API менеджеров

Удобные обёртки над `StorageManager` + `SchemaRegistry` для типичных операций «создать конфиг», «получить конфиг», «авто-создать менеджер». Снижает boilerplate в прикладном коде.

`api/` — **application layer**, тонкие helper'ы. Используется через `extensions/simple_api` (re-export, ADR-DS-004).

## Публичный API

```python
from multiprocess_framework.modules.data_schema_module.extensions.simple_api import (
    create_config,                   # создать новый конфиг
    create_manager_config,           # создать конфиг менеджера
    get_config,                      # получить конфиг
    config_from_dict,                # dict → конфиг с валидацией
    auto_config,                     # auto-создать менеджер по типу/имени
)

from multiprocess_framework.modules.data_schema_module.api import (
    ManagerDataAdapter,              # адаптер для прикладного кода
)
```

## Паттерн использования

```python
from multiprocess_framework.modules.data_schema_module.extensions.simple_api import (
    create_manager_config, get_config,
)

# Создать новый конфиг менеджера
create_manager_config(
    process_data,
    manager_type="theme",
    manager_name="dark",
    config={"palette": "#000000"},
)

# Получить
config = get_config(
    process_data,
    manager_type="theme",
    manager_name="dark",
)
```

## Состав

| Файл | Содержимое |
|------|------------|
| `simple_api.py` | Функции `create_*` / `get_*` / `auto_*` — pythonic-обёртки |
| `manager_adapter.py` | `ManagerDataAdapter` — для интеграции с config_module |

## Когда использовать `api/` vs прямой `StorageManager`

| Случай | Используйте |
|---|---|
| Простые CRUD-операции с менеджером | `api/simple_api` |
| Сложная логика с lock'ами, batch'ами | `storage.StorageManager` напрямую |
| Адаптер для своего модуля | `api/manager_adapter` или свой адаптер по `ISchemaAdapter` |

См. [STATUS.md](STATUS.md), [data_schema_module/README.md](../README.md).
