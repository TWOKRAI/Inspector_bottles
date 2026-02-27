# API Multiprocess Framework (Рефакторинг)

## Общий API фреймворка

### Импорты

```python
# Основные компоненты
from multiprocess_framework.refactored import (
    SystemLauncher,
    ProcessManager,
    ProcessModule,
    RouterManager,
    Message,
    MessageType
)

# Модули
from multiprocess_framework.refactored.modules import (
    message,
    data_schema,
    shared_resources,
    router,
    process,
    worker,
    logger,
    config,
    command,
    dispatch,
    process_manager,
    console
)
```

## Message Module (Транспорт)

### Создание сообщений

```python
from multiprocess_framework.refactored.modules.message import Message, MessageType

# Создание сообщения
msg = Message.create(
    type=MessageType.COMMAND,
    sender="ProcessA",
    targets=["ProcessB"],
    command="process_data",
    args={"data_id": 123}
)

# Fluent API
msg.set_priority(Priority.HIGH)
msg.add_metadata("user_id", "12345")
```

## Router Module (Нервная система) ⭐

### Регистрация каналов

```python
from multiprocess_framework.refactored.modules.router import (
    RouterManager,
    QueueChannel,
    LoggerChannel
)

router = RouterManager("router_1")

# Регистрация каналов
router.register_channel(QueueChannel("process_queue", queue))
router.register_channel(LoggerChannel("logger", logger_manager))
```

### Отправка сообщений

```python
# Автоматический выбор канала
message = Message.create(type=MessageType.LOG, ...)
router.send(message)  # Автоматически выберет LoggerChannel

# Явное указание канала
message.channel = "process_queue"
router.send(message)  # Отправит в QueueChannel
```

## Process Module (Организм)

### Создание процесса

```python
from multiprocess_framework.refactored.modules.process import ProcessModule

class MyProcess(ProcessModule):
    def __init__(self, name, shared_resources, config):
        super().__init__(name, shared_resources, config)
    
    def run(self):
        # Использование Router
        message = Message.create(...)
        self.router_manager.send(message)
```

## Process Manager (Мозг)

### Запуск системы

```python
from multiprocess_framework.refactored.modules.process_manager import SystemLauncher

launcher = SystemLauncher()
launcher.initialize_system(config_dict)
launcher.start()
launcher.wait()
```

## Универсальные подходы

### 1. Через классы (декораторы)

```python
from multiprocess_framework.refactored.modules.process_manager.builders import process, worker

@process(name="MyProcess")
class MyProcess(ProcessModule):
    @worker(name="my_worker")
    def my_worker(self):
        while not self.should_stop():
            # логика
            pass
```

### 2. Через конфиги

```python
from multiprocess_framework.refactored.modules.process_manager.builders import ProcessConfig

config = ProcessConfig(
    name="MyProcess",
    class_path="module.MyProcess",
    config={"key": "value"}
)

launcher.add_process(config)
```

### 3. Через объекты (как PyQt5)

```python
process = ProcessModule("MyProcess", shared_resources)
process.add_manager("logger", logger_manager)
process.add_adapter("router", router_adapter)
process.add_worker("handler", handler_func)
```

