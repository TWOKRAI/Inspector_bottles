# frontend_module — UI-фреймворк

## Назначение

Модуль предоставляет систему виджетов-конструктор для сборки UI из переиспользуемых компонентов. Использует `data_schema_module` и `config_module` для схем и конфигов. Регистры — из `shared_registers` (общие для backend и frontend).

**Ключевые сущности:**
- **FrontendManager** (BaseManager) — единая точка входа: регистры, конфиг, окна, потоки
- **FrontendRegistersBridge** — связь frontend с backend (connection_map, send_callback)
- **ApplicationCoordinator** — фасад приложения, делегирует в FrontendManager
- **Config hot-reload** — подписка на config_module, обновление UI без перезапуска

## Импорты

```python
from frontend_module import (
    FrontendManager,
    FrontendRegistersBridge,
    ApplicationCoordinator,
    WindowManager,
    ThreadManager,
    create_default_registry,
    compose_layout,
)
from frontend_module.interfaces import IFrontendManager, IRegistersManager
```

## Пример: Coordinator + FrontendManager

```python
from frontend_module import ApplicationCoordinator, create_default_registry, compose_layout
from shared_registers import DrawRegisters
from registers_module import RegistersManager

registers = RegistersManager({"draw": DrawRegisters()})
connection_map = {"draw": "renderer"}  # при изменении → send в renderer

coordinator = ApplicationCoordinator(config={})
coordinator.initialize(registers=registers, connection_map=connection_map)

wm = coordinator.window_manager
wm.register("main", create_main_window)
coordinator.run(initial_window="main")
```

## Пример: Регистры и connection_map

```python
from frontend_module import FrontendRegistersBridge
from registers_module import RegistersManager
from shared_registers import DrawRegisters

rm = RegistersManager({"draw": DrawRegisters()})
bridge = FrontendRegistersBridge(rm, router=process, connection_map={"draw": "renderer"})

# Виджет вызывает set_field_value → bridge → send_callback → process.send_message("renderer", msg)
bridge.set_field_value("draw", "dp", 1.5)
```

## Пример: Простые виджеты

```python
from frontend_module import create_default_registry, compose_layout
from shared_registers import DrawRegisters
from registers_module import RegistersManager

rm = RegistersManager({"draw": DrawRegisters()})
registry = create_default_registry()
descriptors = [
    {"widget_type": "checkbox", "register_name": "draw", "field_name": "circles"},
    {"widget_type": "slider", "register_name": "draw", "field_name": "dp"},
]
compose_layout(parent, descriptors, registry, rm, orientation="vertical")
```

## Зависимости

- **Зависит от:** `data_schema_module`, `config_module`, `registers_module`, `shared_registers`
- **Используется в:** `multiprocess_prototype` (GuiProcess), `App` (при миграции)

## Структура модуля

```
frontend_module/
├── __init__.py
├── interfaces.py       # IRegistersManager, IFrontendManager, IWidgetRegistry, ...
├── application/       # FrontendManager, Coordinator, WindowManager, ThreadManager
├── core/              # BaseConfigurableWidget, WidgetRegistry, WindowRegistry, FrontendRegistersBridge
├── schemas/           # WidgetDescriptor, WindowConfig (SchemaBase)
└── tests/
```

## Связь с другими модулями

```
frontend_module
    │
    ├── использует → data_schema_module (схемы виджетов, WindowConfig)
    ├── использует → config_module (runtime-конфиг UI)
    ├── использует → registers_module (RegistersManager)
    ├── использует → shared_registers (схемы регистров)
    │
    └── используется в → multiprocess_prototype (GuiProcess)
    └── используется в → App (при миграции)
```

## Примечания

- Этап 0: создан фундамент (интерфейсы, структура папок)
- Реализация компонентов и виджетов — на следующих этапах
