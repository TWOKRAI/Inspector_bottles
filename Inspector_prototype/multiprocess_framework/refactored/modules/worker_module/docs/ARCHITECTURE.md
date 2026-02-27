# Архитектура рефакторенного Worker Module

## Концепция

WorkerManager теперь наследуется от `BaseManager` и использует `ObservableMixin` для логирования и мониторинга. Это обеспечивает единообразие со всеми менеджерами системы.

## Структура

```
WorkerManager (BaseManager + ObservableMixin)
    ├── initialize() - инициализация менеджера (из BaseManager)
    ├── shutdown() - завершение работы (из BaseManager)
    │
    ├── Компоненты:
    │   ├── WorkerRegistry - реестр воркеров
    │   ├── WorkerLifecycle - жизненный цикл воркеров
    │   └── ThreadConfig - конфигурация потоков
    │
    └── Публичный API:
        ├── create_worker() - создание воркера
        ├── start_worker() / stop_worker() - управление
        ├── pause_worker() / resume_worker() - пауза/возобновление
        ├── get_worker_status() - статус воркера
        └── get_stats() - статистика менеджера
```

## Изменения по сравнению со старым WorkerManager

### Было:
- WorkerManager - обычный класс без наследования
- Логирование через print/traceback
- Вся логика в одном файле

### Стало:
- WorkerManager наследуется от BaseManager + ObservableMixin
- Логирование через ObservableMixin (_log_info, log_error)
- Модульная структура (registry, lifecycle, core)

## Преимущества

1. ✅ Единообразие - все менеджеры наследуются от BaseManager
2. ✅ ObservableMixin - автоматическое логирование и мониторинг
3. ✅ Стандартный жизненный цикл - initialize/shutdown
4. ✅ Упрощение кода - меньше дублирования
5. ✅ Лучшая тестируемость - стандартные интерфейсы

## Использование в ProcessModule

```python
from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_framework.refactored.modules.worker_module import (
    ThreadConfig, ThreadPriority
)

class MyProcess(ProcessModule):
    def _init_application_threads(self):
        """Инициализация потоков приложения."""
        # WorkerManager доступен через self.worker_manager
        def worker(stop_event, pause_event):
            while not stop_event.is_set():
                if pause_event.is_set():
                    time.sleep(0.1)
                    continue
                # Работа воркера
                self.process_data()
                time.sleep(0.1)
        
        config = ThreadConfig(priority=ThreadPriority.NORMAL)
        self.worker_manager.create_worker("data_worker", worker, config, auto_start=True)
```

## Миграция

Старый код:
```python
from src.Modules.Worker_module import WorkerManager

manager = WorkerManager("MyProcess")
```

Новый код:
```python
from multiprocess_framework.refactored.modules.worker_module import WorkerManager

manager = WorkerManager("MyProcess")
manager.initialize()  # Явная инициализация
# ... работа ...
manager.shutdown()  # Явное завершение
```

