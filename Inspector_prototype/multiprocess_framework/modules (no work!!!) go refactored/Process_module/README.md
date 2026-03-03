# Process Module

Базовый модуль для создания процессов в многопроцессной архитектуре. Предоставляет инфраструктуру для жизненного цикла процессов, работы с конфигурацией, управления менеджерами и межпроцессной коммуникации.

## 🚀 Быстрый старт

### Создание простого процесса

```python
from src.Modules.Process_module import ProcessModule
from src.Modules.Shared_resources_module import SharedResourcesManager

# Создание общих ресурсов
shared_resources = SharedResourcesManager()

# Создание процесса
class MyProcess(ProcessModule):
    def run(self):
        """Основной цикл процесса"""
        while not self.stop_event.is_set():
            # Ваша логика здесь
            self.log("INFO", "Process running", "my_process")
            time.sleep(1)

# Использование
process = MyProcess(
    name="MyProcess",
    shared_resources=shared_resources,
    config={"key": "value"}
)

process.start()
process.wait()
```

### Использование в ProcessManager

```python
from src.Modules.Process_manager_module import ProcessManager

# Регистрация процесса
pm = ProcessManager()
pm.register_process(
    name="MyProcess",
    class_path="my_module.MyProcess",
    config={"key": "value"}
)

pm.initialize_processes()
pm.start_processes()
```

## 📦 Основные компоненты

### ProcessModule

Главный класс модуля, объединяющий все компоненты процесса.

#### Инициализация

```python
process = ProcessModule(
    name="ProcessName",
    shared_resources=shared_resources,
    config={}
)
```

- `name`: Имя процесса
- `shared_resources`: SharedResourcesManager для доступа к общим ресурсам
- `config`: Локальная конфигурация процесса (опционально)

#### Компоненты ProcessModule

##### ProcessCore

Базовый жизненный цикл процесса:
- `start()` - Запуск процесса
- `stop()` - Остановка процесса
- `wait()` - Ожидание завершения
- `is_running()` - Проверка состояния

##### ProcessConfigHandler

Работа с конфигурацией:
- `get_config(key, default=None)` - Получение значения конфигурации
- `update_config(key, value)` - Обновление конфигурации
- Доступ к конфигурации через `self.config`

##### ManagersComponents

Управление менеджерами и адаптерами:
- `logger_manager` - Менеджер логирования
- `worker_manager` - Менеджер воркеров
- `router_manager` - Менеджер роутера
- `command_manager` - Менеджер команд

##### ProcessCommunication

Межпроцессная коммуникация:
- `send_message(target, message)` - Отправка сообщения
- `broadcast_message(message)` - Broadcast сообщения
- `receive_message(timeout=None)` - Получение сообщения

## 💡 Примеры использования

### Пример 1: Простой процесс

```python
from src.Modules.Process_module import ProcessModule
import time

class SimpleProcess(ProcessModule):
    def run(self):
        """Основной цикл процесса"""
        self.log("INFO", "Process started", "simple")
        
        while not self.stop_event.is_set():
            # Ваша логика
            self.log("DEBUG", "Processing...", "simple")
            time.sleep(1)
        
        self.log("INFO", "Process stopped", "simple")
```

### Пример 2: Процесс с воркерами

```python
from src.Modules.Process_module import ProcessModule
from src.Modules.Worker_module.worker_manager import ThreadConfig, ThreadPriority
import time

class ProcessWithWorkers(ProcessModule):
    def _init_application_threads(self):
        """Инициализация потоков приложения"""
        # Создание воркера
        config = ThreadConfig(priority=ThreadPriority.NORMAL)
        self.worker_manager.create_worker(
            "data_processor",
            self._process_data,
            config,
            auto_start=True
        )
    
    def _process_data(self, stop_event, pause_event):
        """Функция воркера"""
        while not stop_event.is_set():
            # Обработка данных
            self.log("DEBUG", "Processing data", "worker")
            time.sleep(0.5)
    
    def run(self):
        """Основной цикл процесса"""
        self.log("INFO", "Process with workers started", "main")
        
        # Основной цикл
        while not self.stop_event.is_set():
            time.sleep(1)
        
        self.log("INFO", "Process stopped", "main")
```

### Пример 3: Процесс с коммуникацией

```python
from src.Modules.Process_module import ProcessModule
from src.Modules.Message_module.message import Message
from src.Modules.Message_module.message_types import MessageType
import time

class CommunicatingProcess(ProcessModule):
    def run(self):
        """Основной цикл процесса"""
        self.log("INFO", "Process started", "comm")
        
        # Отправка сообщения другому процессу
        message = Message(
            message_type=MessageType.DATA,
            sender=self.name,
            target="OtherProcess",
            content={"data": "Hello"}
        )
        self.send_message("OtherProcess", message)
        
        # Получение сообщений
        while not self.stop_event.is_set():
            try:
                received = self.receive_message(timeout=1.0)
                if received:
                    self.log("INFO", f"Received: {received.content}", "comm")
            except Exception as e:
                pass
        
        self.log("INFO", "Process stopped", "comm")
```

### Пример 4: Процесс с очередями

```python
from src.Modules.Process_module import ProcessModule
import time

class QueueProcess(ProcessModule):
    def run(self):
        """Основной цикл процесса"""
        self.log("INFO", "Process started", "queue")
        
        # Доступ к очередям через shared_resources
        if self.shared_resources:
            data_queue = self.shared_resources.get_process_data(self.name)
            if data_queue and hasattr(data_queue, 'queues'):
                system_queue = data_queue.queues.get('system')
                
                if system_queue:
                    # Отправка в очередь
                    system_queue.put({"message": "Hello"})
                    
                    # Получение из очереди
                    try:
                        message = system_queue.get(timeout=1.0)
                        self.log("INFO", f"Received: {message}", "queue")
                    except:
                        pass
        
        self.log("INFO", "Process stopped", "queue")
```

### Пример 5: Процесс с конфигурацией

```python
from src.Modules.Process_module import ProcessModule
import time

class ConfiguredProcess(ProcessModule):
    def run(self):
        """Основной цикл процесса"""
        # Получение конфигурации
        interval = self.get_config("interval", 1.0)
        max_iterations = self.get_config("max_iterations", 100)
        
        self.log("INFO", f"Interval: {interval}, Max: {max_iterations}", "config")
        
        iterations = 0
        while not self.stop_event.is_set() and iterations < max_iterations:
            # Ваша логика
            self.log("DEBUG", f"Iteration {iterations}", "config")
            time.sleep(interval)
            iterations += 1
        
        self.log("INFO", "Process completed", "config")
```

## 🔧 Архитектура

```
ProcessModule (ProcessCore)
    ├─> ProcessConfigHandler      # Работа с конфигурацией
    ├─> ManagersComponents        # Управление менеджерами
    │   ├─> LoggerManager         # Логирование
    │   ├─> WorkerManager         # Управление воркерами
    │   ├─> RouterManager         # Маршрутизация сообщений
    │   └─> CommandManager        # Обработка команд
    └─> ProcessCommunication      # Межпроцессная коммуникация
```

## 📋 Жизненный цикл процесса

1. **Инициализация** (`__init__`)
   - Создание компонентов
   - Загрузка конфигурации
   - Инициализация менеджеров

2. **Запуск** (`start()`)
   - Запуск основного потока
   - Инициализация воркеров (`_init_application_threads()`)
   - Запуск основного цикла (`run()`)

3. **Выполнение** (`run()`)
   - Основной цикл процесса
   - Обработка сообщений
   - Выполнение бизнес-логики

4. **Остановка** (`stop()`)
   - Установка `stop_event`
   - Остановка воркеров
   - Очистка ресурсов

## 🔗 Интеграция с другими модулями

### SharedResourcesManager

Процессы получают доступ к общим ресурсам через `SharedResourcesManager`:

```python
# Доступ к данным процесса
process_data = self.shared_resources.get_process_data(self.name)

# Доступ к очередям
if process_data:
    queues = process_data.queues
    system_queue = queues.get('system')
```

### ConfigManager

Конфигурация загружается из `ProcessData`:

```python
# Получение конфигурации
config_value = self.get_config("key", default_value)

# Обновление конфигурации
self.update_config("key", new_value)
```

### LoggerManager

Логирование через `LoggerManager`:

```python
# Логирование
self.log("INFO", "Message", "module")
self.log("ERROR", "Error message", "module", exc_info=True)
```

### WorkerManager

Управление потоками через `WorkerManager`:

```python
# Создание воркера
config = ThreadConfig(priority=ThreadPriority.NORMAL)
self.worker_manager.create_worker(
    "worker_name",
    worker_function,
    config,
    auto_start=True
)
```

### RouterManager

Маршрутизация сообщений через `RouterManager`:

```python
# Отправка сообщения
self.send_message("target_process", message)

# Broadcast сообщения
self.broadcast_message(message, exclude_self=True)
```

## 🧪 Тесты

```bash
# Все тесты Process модуля
pytest tests/Test_Process_module/ -v

# Конкретные тесты
pytest tests/Test_Process_module/test_process_module.py -v
pytest tests/Test_Process_module/test_core.py -v
pytest tests/Test_Process_module/test_communication.py -v

# С покрытием кода
pytest tests/Test_Process_module/ --cov=src.Modules.Process_module
```

## 🎯 Ключевые особенности

- ✅ **Композиция компонентов**: Разделение ответственности через композицию
- ✅ **Жизненный цикл**: Четкий жизненный цикл процесса
- ✅ **Конфигурация**: Гибкая система конфигурации
- ✅ **Менеджеры**: Интеграция с менеджерами системы
- ✅ **Коммуникация**: Межпроцессная коммуникация через сообщения
- ✅ **Воркеры**: Управление потоками через WorkerManager
- ✅ **Логирование**: Структурированное логирование

## 📖 Дополнительная документация

- **[Process Manager Module](../Process_manager_module/README.md)** - Управление процессами
- **[Launcher Module](../Launcher_module/README.md)** - Запуск системы
- **[Shared Resources Module](../Shared_resources_module/README.md)** - Общие ресурсы
- **[Worker Module](../Worker_module/README.md)** - Управление воркерами
- **[Router Module](../Router_module/README.md)** - Маршрутизация сообщений

## ⚠️ Важные замечания

1. **Наследование**: Все процессы должны наследоваться от `ProcessModule` и реализовывать метод `run()`.

2. **stop_event**: Всегда проверяйте `self.stop_event.is_set()` в циклах для корректной остановки.

3. **Конфигурация**: Конфигурация загружается из `ProcessData` через `SharedResourcesManager`.

4. **Менеджеры**: Менеджеры инициализируются автоматически при создании процесса.

5. **Коммуникация**: Используйте `ProcessCommunication` для межпроцессной коммуникации.

6. **Воркеры**: Воркеры создаются в методе `_init_application_threads()`.

## 🔍 Отладка

Для отладки используйте логирование:

```python
class DebugProcess(ProcessModule):
    def run(self):
        self.log("INFO", "Process started", "debug")
        
        # Отладочная информация
        self.log("DEBUG", f"Config: {self.config}", "debug")
        self.log("DEBUG", f"Name: {self.name}", "debug")
        
        # Ваша логика
        while not self.stop_event.is_set():
            self.log("DEBUG", "Processing...", "debug")
            time.sleep(1)
```

## 📝 Примеры реализации

См. примеры в:
- `src/Test_example/multiprocess_chat_app.py` - Пример чат-приложения
- `src/Modules/GUI_module/chat_gui.py` - Пример GUI процесса

