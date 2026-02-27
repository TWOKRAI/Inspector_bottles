# Process Manager Module (Refactored)

Рефакторенный модуль управления процессами на основе BaseManager.

## Архитектура "Тройцы"

ProcessManager является **Сверхэго** в архитектуре "Тройцы создания циклов":

1. **ProcessManager** (Сверхэго) - управляет всеми процессами системы
2. **ProcessModule** (Эго) - базовый процесс, выполняет работу
3. **WorkerManager** (Ид) - управляет потоками внутри процесса

## Структура

```
ProcessManagerCore (BaseManager + ObservableMixin)
    ├── initialize() - инициализация менеджера
    ├── shutdown() - завершение работы
    ├── create_process() - создание процесса
    ├── start_process() / stop_process() - управление процессами
    └── Компоненты:
        ├── ProcessLifecycle - жизненный цикл процессов
        ├── ProcessPriority - управление приоритетами
        └── ProcessStatus - мониторинг статусов

ProcessManagerProcess (ProcessModule)
    └── Использует ProcessManagerCore для управления процессами
```

## Использование

```python
from multiprocess_framework.refactored.modules.process_manager_module import (
    ProcessManagerCore, ProcessManagerProcess
)

# Создание ProcessManagerCore
core = ProcessManagerCore(
    manager_name="ProcessManager",
    shared_resources=shared_resources,
    ...
)
core.initialize()

# Создание процесса
core.create_process("VisionProcess", "module.VisionProcess", config)

# Запуск
core.start_process("VisionProcess")

# Завершение
core.shutdown()
```

## Преимущества новой архитектуры

- ✅ Единообразие - все менеджеры наследуются от BaseManager
- ✅ ObservableMixin - автоматическое логирование и мониторинг
- ✅ Стандартный жизненный цикл - initialize/shutdown
- ✅ Четкая роль в "Тройце" - Сверхэго системы

