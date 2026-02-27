# Process Module (Refactored)

Рефакторенный модуль процессов на основе BaseManager.

## Архитектура

Все процессы теперь наследуются от `BaseManager` и используют `ObservableMixin` для логирования и мониторинга.

```
ProcessModule (BaseManager + ObservableMixin)
    ├── initialize() - инициализация процесса
    ├── shutdown() - завершение работы
    ├── run() - основной цикл процесса
    └── Компоненты:
        ├── ProcessConfigHandler - работа с конфигурацией
        ├── ProcessManagers - управление менеджерами (через ObservableMixin)
        └── ProcessCommunication - межпроцессная коммуникация
```

## Использование

```python
from multiprocess_framework.refactored.modules.process_module import ProcessModule

class MyProcess(ProcessModule):
    def initialize(self) -> bool:
        """Инициализация процесса."""
        # Инициализация компонентов
        self.is_initialized = True
        return True
    
    def shutdown(self) -> bool:
        """Завершение работы процесса."""
        # Очистка ресурсов
        self.is_initialized = False
        return True
    
    def run(self):
        """Основной цикл процесса."""
        while not self.should_stop():
            # Ваша логика
            self.log_info("Processing...")
            time.sleep(1)
```

## Преимущества новой архитектуры

- ✅ Единообразие - все менеджеры наследуются от BaseManager
- ✅ ObservableMixin - автоматическое логирование и мониторинг
- ✅ Стандартный жизненный цикл - initialize/shutdown
- ✅ Упрощение кода - меньше дублирования

