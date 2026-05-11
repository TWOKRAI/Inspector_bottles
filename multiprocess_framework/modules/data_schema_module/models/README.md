# models/ — Базовые Pydantic-модели компонентов

`BaseComponentModel`, `BaseManagerModel`, `ComponentDNA` — готовые Pydantic-наследники с типичной структурой компонента системы (имя, тип, метаданные, иерархия).

`models/` — **application layer**. Используется через `extensions/models` (тонкая обёртка, ADR-DS-004).

## Публичный API

```python
from multiprocess_framework.modules.data_schema_module.extensions.models import (
    BaseComponentModel,              # минимальный component
    BaseManagerModel,                # компонент-менеджер с конфигами
    ComponentType,                   # enum типов компонентов

    # Расширенная ДНК (опционально)
    ComponentDNA,                    # полное описание ДНК компонента
    ComponentLocation,
    ResourceReference,
    ResourceType,
    ComponentHierarchy,
)
```

## Паттерн использования

```python
from multiprocess_framework.modules.data_schema_module.extensions.models import BaseManagerModel

class MyManagerModel(BaseManagerModel):
    manager_type: str = "theme"
    manager_name: str = "dark"
    palette: dict = {}
```

## Состав

| Файл | Содержимое |
|------|------------|
| `base.py` | `BaseComponentModel`, `BaseManagerModel` |
| `types.py` | `ComponentType` enum |
| `dna.py` | `ComponentDNA` + расширения (`Location`, `ResourceReference`, etc.) |

## Связь с `factory/`

`ModelFactory` использует эти base-классы как **скелет** для динамически создаваемых моделей. `ComponentDNA` хранится в `StorageManager` (ProcessData).

См. [STATUS.md](STATUS.md), [docs/DNA_USAGE_EXAMPLES.md](../docs/DNA_USAGE_EXAMPLES.md).
