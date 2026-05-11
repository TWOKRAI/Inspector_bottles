# extensions/ — Изолятор зависимостей (re-export слой)

Тонкие реэкспорт-обёртки для опциональных компонентов модуля, которые **зависят от других модулей фреймворка**. Цель — изолировать side-effects при `import data_schema_module` и не тянуть `process_module` / `config_module` в `core/`.

**ADR-DS-004**: extensions/ — это **первая дверь** для opt-in компонентов; конкретные реализации живут в `storage/`, `versioning/`, `factory/`, `models/`, `tools/`, `api/`.

## Публичный API

```python
# StorageManager (зависит от ProcessData)
from multiprocess_framework.modules.data_schema_module.extensions.storage_manager import StorageManager
# (предпочтительно — напрямую):
from multiprocess_framework.modules.data_schema_module.storage import StorageManager

# VersionManager (зависит от ProcessData + config_module)
from multiprocess_framework.modules.data_schema_module.extensions.versioning import VersionManager

# ComponentDNA + base модели
from multiprocess_framework.modules.data_schema_module.extensions.models import (
    ComponentDNA, BaseManagerModel, BaseComponentModel, ComponentType,
)

# Визуализация
from multiprocess_framework.modules.data_schema_module.extensions.tools import (
    SchemaVisualizer, SchemaDocumentationGenerator,
)

# ModelFactory
from multiprocess_framework.modules.data_schema_module.extensions.factory import ModelFactory

# Simple API
from multiprocess_framework.modules.data_schema_module.extensions.simple_api import (
    create_config, create_manager_config, get_config, config_from_dict, auto_config,
)

# Metrics
from multiprocess_framework.modules.data_schema_module.extensions.metrics import MetricsCollector
```

## Зачем дублирование путей?

| Путь | Когда | Минусы |
|---|---|---|
| `data_schema_module.<subpkg>.X` (canonical) | Новый код, явно знаем зависимости | Длинно |
| `data_schema_module.extensions.X` (legacy/alias) | Старый код, или хочется единого пространства extensions/ | Дополнительный indirection |

Обе формы корректны (ADR-DS-004 разрешает). **Канонический путь — `subpkg`**, `extensions/` оставлен для backward-compat. Со временем потребители мигрируют на каноничный.

## Состав

| Файл | Re-export для |
|------|------------|
| `factory/__init__.py` | `data_schema_module.factory.ModelFactory` |
| `models/__init__.py` | `data_schema_module.models.{BaseComponentModel,ComponentDNA,…}` |
| `tools/__init__.py` | `data_schema_module.tools.{SchemaVisualizer,SchemaDocumentationGenerator}` |
| `versioning.py` | `data_schema_module.versioning.VersionManager` |
| `simple_api.py` | `data_schema_module.api.simple_api.{create_config,get_config,…}` |
| `manager_adapter.py` | `data_schema_module.api.manager_adapter.ManagerDataAdapter` |
| `metrics.py` | `data_schema_module.core.metrics.MetricsCollector` |
| `__init__.py` | docstring + usage examples |

## Принципы

1. **Один файл — одна цель**: каждый файл в extensions/ — это тонкий re-export, не реализация.
2. **Никаких side-effects**: импорт `extensions.X` НЕ должен тянуть `extensions.Y`.
3. **Никаких новых API**: всё, что в extensions, должно существовать в `<subpkg>/`.

См. [STATUS.md](STATUS.md), [DECISIONS.md ADR-DS-004](../DECISIONS.md).
