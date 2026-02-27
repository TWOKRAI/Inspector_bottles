# Руководство для новичков

## Быстрый старт

### Простой пример использования

```python
from multiprocess_framework.refactored.modules.base_manager import BaseManager, ObservableMixin
from multiprocess_framework.refactored.core.logging_facade import log

# Создаем простой менеджер
class MyManager(BaseManager, ObservableMixin):
    def __init__(self, name: str):
        BaseManager.__init__(self, manager_name=name)
        # Простой режим - без "магии", только явные методы
        ObservableMixin.__init__(self, simple_mode=True)
    
    def initialize(self) -> bool:
        log.info("Инициализация менеджера")
        self.is_initialized = True
        return True
    
    def shutdown(self) -> bool:
        log.info("Завершение работы менеджера")
        self.is_initialized = False
        return True

# Использование
manager = MyManager("MyManager")
manager.initialize()

# Логирование работает всегда (даже без LoggerManager)
log.info("Сообщение")
log.error("Ошибка")

manager.shutdown()
```

## Два режима работы

### 1. Простой режим (simple_mode=True) - Рекомендуется для новичков

```python
class SimpleManager(BaseManager, ObservableMixin):
    def __init__(self, name: str):
        BaseManager.__init__(self, manager_name=name)
        # Простой режим - только приватные методы, без "магии"
        ObservableMixin.__init__(self, simple_mode=True)
    
    def do_work(self):
        # Используем приватные методы (всегда доступны)
        self._log_info("Выполняю работу")
        self._record_metric("operations.count")
```

**Преимущества:**
- Все методы явные и понятные
- Легко отлаживать
- Нет "магии" - все видно в коде

### 2. Полный режим (auto_proxy=True) - Для продвинутых

```python
class AdvancedManager(BaseManager, ObservableMixin):
    def __init__(self, name: str, logger=None):
        BaseManager.__init__(self, manager_name=name)
        # Полный режим - приватные + публичные прокси-методы
        ObservableMixin.__init__(
            self,
            managers={'logger': logger},
            auto_proxy=True  # Создает log_info(), record_metric() и т.д.
        )
    
    def do_work(self):
        # Используем публичные методы (создаются автоматически)
        self.log_info("Выполняю работу")
        self.record_metric("operations.count")
```

**Преимущества:**
- Удобный синтаксис
- Автоматическое создание методов
- Больше возможностей

## Работа с адаптерами

### Явный способ (рекомендуется)

```python
# Подключаем адаптер
adapter = CommandAdapter(manager, process)
manager.attach_adapter(adapter, name="command")

# Получаем адаптер явно
command_adapter = manager.get_adapter("command")
if command_adapter:
    command_adapter.execute("test")
```

### Magic-доступ (удобный, но менее явный)

```python
# Подключаем адаптер
adapter = CommandAdapter(manager, process)
manager.attach_adapter(adapter, name="command")

# Получаем адаптер через magic-доступ
command_adapter = manager.command_adapter  # Работает, но менее очевидно
command_adapter.execute("test")
```

## Диагностика и отладка

### Получение информации о менеджере

```python
# Получить информацию для отладки
info = manager.get_debug_info()
print(info)
# {
#   'manager_name': 'MyManager',
#   'is_initialized': True,
#   'adapters': ['command'],
#   'available_methods': [...]
# }

# Вывести информацию в консоль
manager.print_debug_info()
```

### Получение списка доступных методов

```python
# Если используется ObservableMixin
methods = manager.get_available_methods()
print(methods)
# {
#   'private': ['_log_info', '_record_metric', ...],
#   'public': ['log_info', 'record_metric', ...],
#   'managers': ['logger'],
#   'adapters': ['command']
# }

# Вывести список методов
manager.print_available_methods()
```

## Логирование

### Единая точка входа (работает всегда)

```python
from multiprocess_framework.refactored.core.logging_facade import log

# Логирование работает даже если LoggerManager не инициализирован
log.info("Информация")
log.debug("Отладка")
log.warning("Предупреждение")
log.error("Ошибка")
log.exception("Исключение")  # С автоматическим traceback
```

### После инициализации LoggerManager

```python
from multiprocess_framework.refactored.modules.logger_module import LoggerManager
from multiprocess_framework.refactored.core.logging_facade import log

# Создаем и инициализируем LoggerManager
logger_manager = LoggerManager()
logger_manager.initialize()

# Регистрируем в LoggingFacade
log.set_logger_manager(logger_manager)

# Теперь log использует LoggerManager вместо fallback
log.info("Сообщение")  # Использует LoggerManager
```

## Частые вопросы

### Q: Какой режим выбрать - simple_mode или auto_proxy?

**A:** Для новичков рекомендуется `simple_mode=True`:
- Все методы явные и понятные
- Легче отлаживать
- Нет "магии"

Для продвинутых пользователей можно использовать `auto_proxy=True`:
- Удобный синтаксис
- Больше возможностей

### Q: Как понять какие методы доступны?

**A:** Используйте методы диагностики:
```python
manager.print_available_methods()  # Вывести список методов
manager.print_debug_info()  # Вывести информацию о менеджере
```

### Q: Что делать если логирование не работает?

**A:** Используйте `LoggingFacade` - он работает всегда:
```python
from multiprocess_framework.refactored.core.logging_facade import log
log.info("Сообщение")  # Работает всегда
```

### Q: Как отладить проблему с адаптерами?

**A:** Используйте явный доступ и диагностику:
```python
# Явный доступ
adapter = manager.get_adapter("command")
if adapter is None:
    print("Адаптер не найден")

# Диагностика
manager.print_debug_info()  # Покажет все адаптеры
```

## Примеры

### Пример 1: Простой менеджер

```python
from multiprocess_framework.refactored.modules.base_manager import BaseManager, ObservableMixin
from multiprocess_framework.refactored.core.logging_facade import log

class SimpleWorker(BaseManager, ObservableMixin):
    def __init__(self, name: str):
        BaseManager.__init__(self, manager_name=name)
        ObservableMixin.__init__(self, simple_mode=True)
    
    def initialize(self) -> bool:
        log.info(f"Инициализация {self.manager_name}")
        self.is_initialized = True
        return True
    
    def shutdown(self) -> bool:
        log.info(f"Завершение {self.manager_name}")
        self.is_initialized = False
        return True
    
    def process(self):
        self._log_info("Обработка данных")
        return "result"

# Использование
worker = SimpleWorker("Worker1")
worker.initialize()
result = worker.process()
worker.shutdown()
```

### Пример 2: Менеджер с логированием

```python
from multiprocess_framework.refactored.modules.base_manager import BaseManager, ObservableMixin
from multiprocess_framework.refactored.modules.logger_module import LoggerManager
from multiprocess_framework.refactored.core.logging_facade import log

class ManagerWithLogger(BaseManager, ObservableMixin):
    def __init__(self, name: str):
        BaseManager.__init__(self, manager_name=name)
        
        # Создаем LoggerManager
        logger_manager = LoggerManager()
        logger_manager.initialize()
        log.set_logger_manager(logger_manager)
        
        # Используем простой режим
        ObservableMixin.__init__(
            self,
            managers={'logger': logger_manager},
            simple_mode=True
        )
    
    def initialize(self) -> bool:
        self._log_info("Инициализация")
        self.is_initialized = True
        return True
    
    def shutdown(self) -> bool:
        self._log_info("Завершение")
        self.is_initialized = False
        return True

# Использование
manager = ManagerWithLogger("MyManager")
manager.initialize()
manager.shutdown()
```

## Дополнительные ресурсы

- [Архитектура системы](../ARCHITECTURE.md)
- [API документация](API.md)
- [Примеры использования](../QUICK_START.md)

