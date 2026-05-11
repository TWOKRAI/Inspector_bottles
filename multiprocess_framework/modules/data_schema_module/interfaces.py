# -*- coding: utf-8 -*-
"""
Публичный контракт data_schema_module — агрегатор интерфейсов из sub-packages.

Контракты декомпозированы по слоям (ADR-DS-005, 2026-05-11) — реальные определения
живут в `<sub_package>/interfaces.py`. Этот файл — единая точка импорта для
потребителей, чтобы не привязываться к внутренней структуре модуля.

Иерархия по слоям:

```text
core/interfaces.py          ISchema, ISchemaAdapter, HasBuild, IDataValidator
registry/interfaces.py      ISchemaRegistry, ISchemaManager
serialization/interfaces.py IDataConverter, ISchemaStorage, IAsyncSchemaStorage,
                            IRegisterStorage*, IAsyncRegisterStorage* (* = legacy alias)
storage/interfaces.py       IStorageManager
versioning/interfaces.py    IVersionManager
tools/interfaces.py         IVisualizationFormatter, IDocumentationFormatter,
                            ISchemaVisualizer, ISchemaDocumentationGenerator
```

Импорт через корень модуля (рекомендуется):

```python
from multiprocess_framework.modules.data_schema_module import (
    ISchema, ISchemaAdapter, HasBuild,
    ISchemaRegistry, IDataConverter, ISchemaStorage,
)
```

Прямой импорт `from data_schema_module.interfaces import ...` тоже работает —
файл реэкспортирует всё.
"""
from __future__ import annotations

from .core.interfaces import (
    HasBuild,
    IDataValidator,
    ISchema,
    ISchemaAdapter,
)
from .registry.interfaces import (
    ISchemaManager,
    ISchemaRegistry,
)
from .serialization.interfaces import (
    IAsyncRegisterStorage,
    IAsyncSchemaStorage,
    IDataConverter,
    IRegisterStorage,
    ISchemaStorage,
)
from .storage.interfaces import IStorageManager
from .tools.interfaces import (
    IDocumentationFormatter,
    ISchemaDocumentationGenerator,
    ISchemaVisualizer,
    IVisualizationFormatter,
)
from .versioning.interfaces import IVersionManager

__all__ = [
    # core
    "ISchema",
    "ISchemaAdapter",
    "HasBuild",
    "IDataValidator",
    # registry
    "ISchemaRegistry",
    "ISchemaManager",
    # serialization
    "IDataConverter",
    "ISchemaStorage",
    "IAsyncSchemaStorage",
    "IRegisterStorage",
    "IAsyncRegisterStorage",
    # storage
    "IStorageManager",
    # versioning
    "IVersionManager",
    # tools
    "IVisualizationFormatter",
    "IDocumentationFormatter",
    "ISchemaVisualizer",
    "ISchemaDocumentationGenerator",
]
