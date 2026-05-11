# container/ — Контейнеры и конвертеры конфигов

`RegistersContainer` — контейнер для набора `*Registers`-моделей одного процесса. Конвертеры конфигов в dict для пересечения границы процесса (ADR-008 «Dict at Boundary»).

`container/` — **application layer**. Зависит только от `core/`.

## Публичный API

```python
from multiprocess_framework.modules.data_schema_module import (
    RegistersContainer,              # контейнер схем процесса

    # Конвертеры Dict at Boundary
    config_to_dict,                  # схема → (name, dict)
    configs_to_dicts,                # список схем → список (name, dict)
    build_process_with_workers,      # сборка ProcessConfig + WorkerConfig'и в dict
    process,                         # короткий alias для build_process_with_workers
)
```

## Паттерн использования

```python
from multiprocess_framework.modules.data_schema_module import process
from my_app.configs import MyProcessConfig, MyWorkerConfig

# Dict at Boundary: на границе процесса передаём словари, не Pydantic-объекты
launcher.add_process(*process(MyProcessConfig(), MyWorkerConfig()))

# Эквивалент:
# launcher.add_process("my_process", {"key": "value", "workers": {...}})
```

## Состав

| Файл | Содержимое |
|------|------------|
| `registers_container.py` | `RegistersContainer` — контейнер схем процесса |
| `config_converters.py` | `config_to_dict`, `process()`, `build_process_with_workers` |

## Почему Dict at Boundary

Pydantic-объекты не pickle-safe для всех ситуаций (особенно `frozen=True` + `model_config`). Между процессами передаём **только `dict`** — `to_dict`/`from_dict` пересекает границу, Pydantic-валидация происходит **внутри** процесса при `from_dict`.

См. ADR-008 в [framework/DECISIONS.md](../../../DECISIONS.md).

См. [STATUS.md](STATUS.md), [data_schema_module/README.md](../README.md).
