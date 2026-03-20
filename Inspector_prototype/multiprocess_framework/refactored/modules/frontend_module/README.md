# frontend_module — UI-фреймворк

## Назначение

Модуль предоставляет систему виджетов-конструктор для сборки UI из переиспользуемых компонентов. Использует `data_schema_module` и `config_module` для схем и конфигов. **Конкретные классы регистров** (поля, `FieldMeta`, `register_dispatch`) задаёт приложение как наследники `SchemaBase`; фреймворк их не поставляет. В прототипе Inspector — `multiprocess_prototype/registers/schemas`.

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
from registers_module import RegistersManager
from multiprocess_prototype.registers.schemas.processing_tab import (
    PROCESSOR_REGISTER,
    ProcessorRegisters,
)

registers = RegistersManager({PROCESSOR_REGISTER: ProcessorRegisters()})
connection_map = {PROCESSOR_REGISTER: "processor"}

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
from multiprocess_prototype.registers.schemas.processing_tab import (
    PROCESSOR_REGISTER,
    ProcessorRegisters,
)

rm = RegistersManager({PROCESSOR_REGISTER: ProcessorRegisters()})
bridge = FrontendRegistersBridge(rm, router=process, connection_map={PROCESSOR_REGISTER: "processor"})

# Виджет вызывает set_field_value → bridge → send_callback → process.send_message("processor", msg)
bridge.set_field_value(PROCESSOR_REGISTER, "min_area", 600)
```

## Пример: Простые виджеты

```python
from frontend_module import create_default_registry, compose_layout
from registers_module import RegistersManager
from multiprocess_prototype.registers.schemas.processing_tab import (
    PROCESSOR_REGISTER,
    ProcessorRegisters,
)

rm = RegistersManager({PROCESSOR_REGISTER: ProcessorRegisters()})
registry = create_default_registry()
descriptors = [
    {"widget_type": "slider", "register_name": PROCESSOR_REGISTER, "field_name": "min_area"},
]
compose_layout(parent, descriptors, registry, rm, orientation="vertical")
```

## Зависимости

- **Зависит от:** `data_schema_module`, `config_module`, `registers_module` (конкретные схемы регистров — в приложении)
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
    ├── (приложение подставляет классы регистров в RegistersManager)
    │
    └── используется в → multiprocess_prototype (GuiProcess)
    └── используется в → App (при миграции)
```

## Примечания

- Этап 0: создан фундамент (интерфейсы, структура папок)
- Реализация компонентов и виджетов — на следующих этапах
