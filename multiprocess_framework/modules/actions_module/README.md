# Actions Module

Action-bus с undo/redo и coalescing для GUI-приложений на базе фреймворка (carve-out из `frontend_module/actions/`, ADR-124, 2026-05-11).

`Action` — иммутабельная единица изменения состояния с `forward_patch` и `backward_patch`. `ActionBuilder` — generic-фабрика (приложения наследуют для доменных методов). `ActionBus` — единая точка выполнения с undo/redo-стеками, coalescing по `coalesce_key` и опциональным персистентным журналированием через `IActionLogWriter`.

Модуль не зависит от `frontend_module` (PySide6 не требуется) — `ActionBus` работает с любым объектом, реализующим `IRegistersManagerGui` Protocol. Конкретный writer лога живёт в `Services/sql/action_log/`; framework знает только Protocol-контракт.

---

## Архитектура

| Подсистема | Файлы | Назначение |
|---|---|---|
| **Core** | `schemas.py`, `bus.py`, `builder.py` | `Action`, `ActionBus`, `ActionBuilder` |
| **Handlers** | `handlers/move_handler.py`, `handlers/topology_handler.py` | Generic-хэндлеры: перемещение нод и мутации topology |
| **Persistence (Protocols)** | `persistence/interfaces.py` | `IActionLogWriter`, `IActionLogRepository` — контракты для Services |

`Action(SchemaBase)` наследуется от `data_schema_module.SchemaBase` (единственная внешняя зависимость модуля). `ActionBuilder.from_field()` принимает любой объект с `register_name`/`field_name` (локальный Protocol `RegisterBindingLike`).

## Публичный API

```python
from multiprocess_framework.modules.actions_module import (
    Action,
    ActionBuilder,
    ActionBus,
    ActionHandler,
    IRegistersManagerGui,
)
from multiprocess_framework.modules.actions_module.handlers import (
    NodeMoveHandler,
    TopologyMutationHandler,
)
from multiprocess_framework.modules.actions_module.persistence import (
    IActionLogRepository,
    IActionLogWriter,
)
```

## Расширение в приложении

```python
class AppActionBuilder(ActionBuilder):
    @staticmethod
    def domain_action(...) -> Action:
        return Action(action_type="domain_action", ...)
```

См. `multiprocess_prototype/frontend/actions/` — пример прикладного слоя поверх actions_module.

## Тесты

- `tests/test_bus.py` — coalescing, undo/redo, callbacks (33 теста)
- `handlers/tests/test_move_handler.py`, `test_topology_handler.py` — apply/revert хэндлеров
