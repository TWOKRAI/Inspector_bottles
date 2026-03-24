# Модуль {module_name}

## Назначение

Краткое описание (1–3 предложения): что делает модуль, какую проблему решает.

## Импорты

```python
from multiprocess_framework.modules.{module_name} import (
    ClassName1,
    ClassName2,
)
```

## Точки входа

| Класс/функция | Метод | Описание |
|---------------|-------|----------|
| MainClass | `initialize()` | Инициализация |
| MainClass | `shutdown()` | Завершение работы |
| MainClass | `method_name()` | Краткое описание |

## Зависимости

- **Зависит от:** `base_manager`, `message_module`
- **Используется в:** `router_module`, `App.Coordinator`

## Пример

```python
from multiprocess_framework.modules.{module_name} import MainClass

obj = MainClass("name")
obj.initialize()
# ... работа ...
obj.shutdown()
```

## Связь с другими модулями

```
{module_name}
    │
    ├── использует → base_manager
    ├── использует → message_module
    │
    └── используется в → router_module
    └── используется в → App
```

## Структура модуля

```
{module_name}/
├── __init__.py      # Публичный API
├── README.md
├── core/
├── ...
└── tests/
```

## Примечания

- Опционально: известные ограничения, roadmap, backward compatibility
