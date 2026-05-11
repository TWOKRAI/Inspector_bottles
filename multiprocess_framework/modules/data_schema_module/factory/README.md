# factory/ — Фабрики моделей

Динамическое создание Pydantic-моделей. `ModelFactory` — общий API; `DNAFactory` (опц.) — фабрики ДНК-компонентов.

`factory/` — **application layer**. Используется через `extensions/factory` (тонкая обёртка, ADR-DS-004).

## Публичный API

```python
from multiprocess_framework.modules.data_schema_module.extensions.factory import (
    ModelFactory,
    DNAFactory,                      # опционально
)
# Или напрямую (тоже корректно):
from multiprocess_framework.modules.data_schema_module.factory import ModelFactory
```

## Паттерн использования

```python
from multiprocess_framework.modules.data_schema_module.extensions.factory import ModelFactory

# Динамически создать класс из словаря описаний полей
DynamicSchema = ModelFactory.create_model(
    name="DynamicSchema",
    fields={"threshold": (float, 0.5), "name": (str, "")},
)
instance = DynamicSchema(threshold=0.8, name="x")
```

## Состав

| Файл | Содержимое |
|------|------------|
| `model_factory.py` | `ModelFactory` — динамическое создание Pydantic-моделей |
| `dna_factory.py` | `DNAFactory` — фабрики ДНК-компонентов (опц.) |

## Зачем это нужно

Полезно когда:
- Схема **не известна на этапе компиляции** (config-driven построение).
- Нужно сгенерировать класс из YAML/JSON-описания.
- ДНК-компоненты с динамической структурой (`ComponentDNA`).

См. [STATUS.md](STATUS.md), [data_schema_module/README.md](../README.md).
