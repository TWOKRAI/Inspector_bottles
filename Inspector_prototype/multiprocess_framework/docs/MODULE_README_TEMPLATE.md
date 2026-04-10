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

---

## Жизненный цикл (ProcessModule / менеджер)

- **`initialize()`** — поднять ресурсы, зарегистрировать адаптеры, подписаться на события.
- **`run()`** / основной цикл — рабочая фаза (для менеджера часто управляется родительским `ProcessModule`).
- **`shutdown()`** — освободить каналы, буферы, фоновые потоки; идемпотентность по возможности.

## Dict at Boundary (чеклист)

- [ ] Публичные методы, пересекающие границу процесса / IPC, принимают и возвращают **`dict`**, не Pydantic-модели.
- [ ] Внутри модуля допустимы `SchemaBase` и `model_validate` / `model_dump` на границах «внутри процесса».

## Конфиг (SchemaBase)

- Конфиг менеджера описывается подклассом **`SchemaBase`** (или наследником `ChannelRoutingConfig` для CRM-менеджеров).
- Сборка для оркестратора — через **`build()`** / **`process()`** приложения; см. [CONFIG_GUIDE.md](./CONFIG_GUIDE.md).

## DECISIONS.md модуля

- Локальные архитектурные решения — в **`DECISIONS.md`** рядом с модулем.
- Формат заголовка: **`## ADR-XX-NNN (was ADR-…): …`** — см. [ADR_REGISTRY.md](./ADR_REGISTRY.md).

## ObservableMixin

- Менеджеры с прокси-логированием/метриками наследуют **`ObservableMixin`** (часть `base_manager`); канальные менеджеры — от **`ChannelRoutingManager`**.

## Тесты

- Каталог **`tests/`**, имена **`test_*.py`**, pytest.
- Общие фикстуры при необходимости — `modules/conftest.py`.
