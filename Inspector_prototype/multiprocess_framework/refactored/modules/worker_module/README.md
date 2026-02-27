# Worker Module (Refactored)

Рефакторенный модуль управления потоками на основе BaseManager.

## Архитектура

WorkerManager теперь наследуется от `BaseManager` и использует `ObservableMixin` для логирования и мониторинга.

```
WorkerManager (BaseManager + ObservableMixin)
    ├── initialize() - инициализация менеджера
    ├── shutdown() - завершение работы
    ├── create_worker() - создание воркера
    ├── start_worker() - запуск воркера
    ├── stop_worker() - остановка воркера
    └── Компоненты:
        ├── WorkerRegistry - реестр воркеров
        ├── WorkerLifecycle - жизненный цикл воркеров
        └── WorkerMetrics - метрики производительности
```

## Использование

```python
from multiprocess_framework.refactored.modules.worker_module import (
    WorkerManager, ThreadConfig, ThreadPriority
)

# Создание менеджера
manager = WorkerManager("MyProcess")
manager.initialize()

# Создание воркера
def my_worker(stop_event, pause_event):
    while not stop_event.is_set():
        if pause_event.is_set():
            time.sleep(0.1)
            continue
        # Работа воркера
        process_data()
        time.sleep(0.1)

config = ThreadConfig(priority=ThreadPriority.NORMAL)
manager.create_worker("worker1", my_worker, config, auto_start=True)

# Завершение
manager.shutdown()
```

## Преимущества новой архитектуры

- ✅ Единообразие - все менеджеры наследуются от BaseManager
- ✅ ObservableMixin - автоматическое логирование и мониторинг
- ✅ Стандартный жизненный цикл - initialize/shutdown
- ✅ Улучшенная структура - модульная организация

