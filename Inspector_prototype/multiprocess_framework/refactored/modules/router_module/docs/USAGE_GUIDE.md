# Руководство по использованию RouterModule

## Введение

RouterModule предоставляет систему маршрутизации сообщений с интеллектуальным выбором каналов через Dispatch модуль.

## Быстрый старт

### Базовое использование

```python
from multiprocess_framework.refactored.modules.router_module import RouterManager, QueueChannel
from queue import Queue

# Создание роутера
router = RouterManager(
    manager_name="my_router",
    dispatch_strategy=DispatchStrategy.EXACT_MATCH
)

# Инициализация
router.initialize()

# Создание и регистрация канала
queue = Queue()
channel = QueueChannel("internal_queue", queue)
router.register_channel(channel)

# Отправка сообщения
result = router.send({
    'type': 'command',
    'command': 'process',
    'data': {'file': 'test.txt'}
})

# Получение сообщений
messages = router.receive(timeout=0.1)

# Завершение работы
router.shutdown()
```

## Работа с каналами

### Регистрация каналов

```python
from queue import Queue
from multiprocess_framework.refactored.modules.router_module import QueueChannel

# Создание канала очереди
queue = Queue()
channel = QueueChannel("my_queue", queue)

# Регистрация в роутере
router.register_channel(channel)

# Получение канала
retrieved_channel = router.get_channel("my_queue")

# Получение всех каналов
all_channels = router.get_all_channels()
```

### Создание кастомного канала

```python
from multiprocess_framework.refactored.modules.router_module import MessageChannel
from typing import Dict, Any, List

class CustomChannel(MessageChannel):
    """Кастомный канал для примера."""
    
    def __init__(self, name: str):
        self._name = name
        self._messages = []
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def channel_type(self) -> str:
        return "custom"
    
    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        self._messages.append(message)
        return {'status': 'success', 'channel': self.name}
    
    def poll(self, timeout: float = 0.0) -> List[Dict[str, Any]]:
        messages = self._messages[:]
        self._messages.clear()
        return messages

# Использование
custom_channel = CustomChannel("custom")
router.register_channel(custom_channel)
```

## Интеграция с Dispatch модулем

### Регистрация обработчиков каналов

RouterManager использует Dispatch модуль для выбора канала отправки:

```python
def priority_handler(message: Dict[str, Any]) -> Dict[str, Any]:
    """Обработчик для приоритетных сообщений."""
    if message.get('urgent'):
        return {'status': 'success', 'channel': 'priority_queue'}
    return {'status': 'success', 'channel': 'internal_queue'}

# Регистрация обработчика
router.register_channel_handler(
    key='priority_message',
    handler=priority_handler,
    efficiency=10,
    tags=['priority', 'routing']
)
```

### Регистрация обработчиков сообщений

Для обработки входящих сообщений:

```python
def process_message(message: Dict[str, Any]) -> Dict[str, Any]:
    """Обработчик входящих сообщений."""
    data = message.get('data', {})
    # Обработка данных
    return {'status': 'processed', 'result': data}

# Регистрация обработчика
router.register_message_handler(
    key='process_data',
    handler=process_message,
    expects_full_message=False
)
```

### Использование разных стратегий

```python
from multiprocess_framework.modules.Dispatch_module import DispatchStrategy

# Создание роутера с паттерн-матчинг стратегией
router = RouterManager(
    manager_name="pattern_router",
    dispatch_strategy=DispatchStrategy.PATTERN_MATCH
)

# Регистрация обработчика с паттерном
def pattern_handler(message: Dict[str, Any]) -> Dict[str, Any]:
    return {'status': 'success', 'channel': 'pattern_queue'}

router.register_channel_handler(
    key=r'process_\d+',  # Регулярное выражение
    handler=pattern_handler,
    strategy=DispatchStrategy.PATTERN_MATCH
)
```

## Асинхронное прослушивание

### Использование колбэков

```python
def message_callback(message: Dict[str, Any]):
    """Обработчик входящих сообщений."""
    print(f"Received message: {message}")

# Добавление колбэка
router.add_message_callback(message_callback)

# Запуск прослушивания
router.start_listening(poll_interval=0.01)

# ... работа приложения ...

# Остановка прослушивания
router.stop_listening()
```

## Работа с Message объектами

RouterModule поддерживает как словари, так и объекты Message:

```python
from multiprocess_framework.refactored.modules.message_module import Message, MessageType

# Создание Message объекта
message = Message.create(
    type=MessageType.COMMAND,
    sender="GUI",
    targets=["Worker"],
    command="process",
    data={'file': 'test.txt'}
)

# Отправка Message объекта
result = router.send(message)

# Получение Message объектов
messages = router.receive(timeout=0.1, return_messages=True)
for msg in messages:
    print(f"Command: {msg.command}, Data: {msg.data}")
```

## Статистика и мониторинг

### Получение статистики

```python
stats = router.get_stats()

print(f"Sent: {stats['router']['sent']}")
print(f"Received: {stats['router']['received']}")
print(f"Errors: {stats['router']['errors']}")
print(f"Channels: {stats['router']['channels_count']}")
```

### Информация о диспетчерах

```python
dispatcher_info = router.get_dispatcher_info()

print(f"Channel handlers: {dispatcher_info['channel_dispatcher']['handlers_count']}")
print(f"Message handlers: {dispatcher_info['message_dispatcher']['handlers_count']}")
```

## Примеры использования

### Пример 1: Простая маршрутизация

```python
from multiprocess_framework.refactored.modules.router_module import RouterManager, QueueChannel
from queue import Queue

# Создание роутера
router = RouterManager("simple_router")
router.initialize()

# Регистрация каналов
internal_queue = Queue()
router.register_channel(QueueChannel("internal", internal_queue))

priority_queue = Queue()
router.register_channel(QueueChannel("priority", priority_queue))

# Обработчик для приоритетных сообщений
def priority_selector(message):
    if message.get('priority'):
        return {'channel': 'priority'}
    return {'channel': 'internal'}

router.register_channel_handler('priority_message', priority_selector)

# Отправка сообщений
router.send({'type': 'command', 'command': 'normal', 'data': {}})
router.send({'type': 'command', 'command': 'urgent', 'priority': True, 'data': {}})
```

### Пример 2: Интеграция с процессами

```python
from multiprocess_framework.refactored.modules.router_module import RouterAdapter

# Создание адаптера для процесса
adapter = RouterAdapter(router, process=current_process)

# Отправка сообщения конкретному процессу
adapter.send_to_process("Worker1", {
    'type': 'command',
    'command': 'process',
    'data': {'file': 'test.txt'}
})

# Broadcast сообщения всем процессам
adapter.broadcast({
    'type': 'event',
    'event': 'system_started',
    'data': {}
})
```

### Пример 3: Обработка входящих сообщений

```python
# Регистрация обработчиков для разных типов сообщений
def handle_command(message):
    command = message.get('command')
    data = message.get('data', {})
    
    if command == 'process':
        # Обработка команды
        return {'status': 'processed', 'result': 'ok'}
    
    return {'status': 'unknown_command'}

def handle_event(message):
    event = message.get('event')
    # Обработка события
    return {'status': 'event_handled', 'event': event}

# Регистрация обработчиков
router.register_message_handler('process', handle_command)
router.register_message_handler('event', handle_event)

# Получение и обработка сообщений
messages = router.receive(timeout=0.1)
for msg in messages:
    dispatch_result = msg.get('_dispatch_result', {})
    print(f"Message processed: {dispatch_result}")
```

## Лучшие практики

1. **Всегда инициализируйте роутер** перед использованием:
   ```python
   router.initialize()
   ```

2. **Завершайте работу корректно**:
   ```python
   router.shutdown()
   ```

3. **Используйте таймауты** при получении сообщений:
   ```python
   messages = router.receive(timeout=0.1)  # Не блокирует навсегда
   ```

4. **Регистрируйте обработчики** до начала работы:
   ```python
   router.initialize()
   router.register_channel_handler(...)
   router.register_message_handler(...)
   ```

5. **Используйте интерфейсы** для расширяемости:
   ```python
   from multiprocess_framework.refactored.modules.router_module import IMessageChannel
   
   class MyChannel(IMessageChannel):
       # Реализация интерфейса
       ...
   ```

## Обработка ошибок

RouterModule автоматически обрабатывает ошибки и логирует их через ObservableMixin:

```python
# Ошибки автоматически логируются
result = router.send(invalid_message)
if result.get('status') == 'error':
    print(f"Error: {result.get('reason')}")
```

## Интеграция с другими модулями

### С ProcessModule

```python
from multiprocess_framework.refactored.modules.process_module import Process

class MyProcess(Process):
    def setup(self):
        # Создание роутера для процесса
        self.router = RouterManager(
            manager_name=f"{self.name}_router",
            process=self,
            queue_registry=self.queue_registry
        )
        self.router.initialize()
    
    def cleanup(self):
        if self.router:
            self.router.shutdown()
```

### С LoggerModule

```python
from multiprocess_framework.modules.Logger_module import LoggerManager

logger = LoggerManager("router_logger")
router = RouterManager(
    manager_name="logged_router",
    logger=logger  # Автоматическое логирование через ObservableMixin
)
```

## Дополнительные ресурсы

- [ARCHITECTURE.md](ARCHITECTURE.md) - Архитектура модуля
- [DISPATCH_INTEGRATION.md](DISPATCH_INTEGRATION.md) - Интеграция с Dispatch модулем
- [README.md](../README.md) - Общая документация модуля

