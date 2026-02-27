# RouterManager - Документация

## Обзор

`RouterManager` - универсальный менеджер маршрутизации с интеллектуальным диспетчером для выбора каналов передачи сообщений.

**Философия:**
- `Dispatcher` выбирает **КАКОЙ** канал использовать для отправки
- `MessageChannel` знает **КАК** отправлять/принимать через свой протокол
- `RouterManager` управляет всем процессом маршрутизации

## Архитектура

```
RouterManager
├── channel_dispatcher (Dispatcher) - выбор канала для отправки
├── message_dispatcher (Dispatcher) - обработка входящих сообщений
└── _channels (Dict[str, MessageChannel]) - реестр каналов
```

## Публичные методы (Public API)

### Основные операции

#### `send(message: Dict[str, Any]) -> Dict[str, Any]`
Отправить сообщение с интеллектуальным выбором канала через диспетчер.

**Параметры:**
- `message` - словарь с данными сообщения

**Возвращает:**
- `Dict[str, Any]` - результат отправки (статус, причина ошибки и т.д.)

**Пример:**
```python
result = router.send({
    'type': 'command',
    'sender': 'GUI',
    'targets': ['Worker'],
    'command': 'process_data'
})
```

**Особенности:**
- Если в сообщении указано поле `channel` - используется этот канал напрямую
- Иначе определяется ключ для диспетчера и выбирается канал автоматически

---

#### `receive(timeout: float = 0.0) -> List[Dict[str, Any]]`
Получить сообщения со всех каналов и обработать через диспетчер.

**Параметры:**
- `timeout` - таймаут опроса каналов (0 = non-blocking)

**Возвращает:**
- `List[Dict[str, Any]]` - список сообщений с результатами обработки

**Пример:**
```python
messages = router.receive(timeout=0.1)
for msg in messages:
    print(msg.get('_dispatch_result'))
```

---

### Управление каналами

#### `register_channel(channel: MessageChannel) -> bool`
Зарегистрировать канал в роутере.

**Параметры:**
- `channel` - канал, реализующий интерфейс `MessageChannel`

**Возвращает:**
- `bool` - True если канал успешно зарегистрирован

**Пример:**
```python
from src.Modules.Router_module.channel import QueueChannel

channel = QueueChannel("my_channel")
router.register_channel(channel)
```

**Особенности:**
- Канал должен реализовывать базовый интерфейс `MessageChannel`
- Если канал с таким именем уже зарегистрирован, он будет заменен

---

#### `unregister_channel(channel_name: str) -> bool`
Удалить канал из роутера.

**Параметры:**
- `channel_name` - имя канала для удаления

**Возвращает:**
- `bool` - True если канал успешно удален

---

#### `get_channel(channel_name: str) -> Optional[MessageChannel]`
Получить канал по имени.

**Параметры:**
- `channel_name` - имя канала

**Возвращает:**
- `Optional[MessageChannel]` - канал или None если не найден

---

#### `get_all_channels() -> List[MessageChannel]`
Получить все зарегистрированные каналы.

**Возвращает:**
- `List[MessageChannel]` - список всех каналов

---

### Регистрация обработчиков

#### `register_channel_handler(key, handler, ...) -> bool`
Зарегистрировать кастомный обработчик для выбора каналов.

**Параметры:**
- `key: str` - ключ для диспетчеризации
- `handler: Callable` - функция-обработчик, возвращающая `{'channel': 'channel_name'}`
- `expects_full_message: bool = True` - использовать полное сообщение
- `metadata: Dict[str, Any] = None` - метаданные обработчика
- `priority: int = 0` - приоритет обработчика
- `tags: List[str] = None` - теги для группировки

**Возвращает:**
- `bool` - True если обработчик успешно зарегистрирован

**Пример:**
```python
def custom_channel_selector(message):
    if message.get('urgent'):
        return {'channel': 'priority_queue'}
    return {'channel': 'internal_queue'}

router.register_channel_handler('urgent_message', custom_channel_selector)
```

---

#### `register_message_handler(key, handler, ...) -> bool`
Зарегистрировать обработчик для входящих сообщений.

**Параметры:**
- `key: str` - ключ для диспетчеризации входящих сообщений
- `handler: Callable` - функция-обработчик входящих сообщений
- `expects_full_message: bool = True` - использовать полное сообщение
- `metadata: Dict[str, Any] = None` - метаданные обработчика
- `priority: int = 0` - приоритет обработчика
- `tags: List[str] = None` - теги для группировки

**Возвращает:**
- `bool` - True если обработчик успешно зарегистрирован

---

### Асинхронное прослушивание

#### `add_message_callback(callback: Callable) -> None`
Добавить колбэк для асинхронного приема сообщений.

**Параметры:**
- `callback: Callable[[Dict[str, Any]], None]` - функция обратного вызова

**Пример:**
```python
def my_callback(message):
    print(f"Received: {message}")

router.add_message_callback(my_callback)
router.start_listening()
```

---

#### `start_listening(poll_interval: float = 0.01) -> None`
Запустить асинхронное прослушивание с диспетчеризацией.

**Параметры:**
- `poll_interval` - интервал опроса каналов в секундах

**Особенности:**
- Запускается в отдельном потоке (daemon thread)
- Если уже запущено, предупреждение будет залогировано

---

#### `stop_listening(timeout: float = 5.0) -> bool`
Остановить асинхронное прослушивание сообщений.

**Параметры:**
- `timeout` - таймаут ожидания остановки потока в секундах

**Возвращает:**
- `bool` - True если остановка успешна, False в противном случае

**Пример:**
```python
router.start_listening()
# ... работа ...
router.stop_listening(timeout=1.0)
```

---

#### `cleanup() -> None`
Очистка ресурсов роутера.

Останавливает прослушивание, очищает каналы и колбэки.
Вызывается при завершении работы роутера.

**Пример:**
```python
try:
    router.start_listening()
    # ... работа ...
finally:
    router.cleanup()
```

---

### Мониторинг и статистика

#### `get_stats() -> Dict[str, Any]`
Получить полную статистику работы роутера.

**Возвращает:**
- `Dict[str, Any]` - статистика включая:
  - `router_id` - идентификатор роутера
  - `sent` - количество отправленных сообщений
  - `received` - количество полученных сообщений
  - `processed` - количество обработанных сообщений
  - `errors` - количество ошибок
  - `dispatch_errors` - ошибки диспетчеризации
  - `listening` - статус прослушивания
  - `callbacks_count` - количество зарегистрированных колбэков
  - `channel_handlers` - количество обработчиков каналов
  - `message_handlers` - количество обработчиков сообщений
  - `channels_count` - количество зарегистрированных каналов
  - `channels` - информация о каналах

---

#### `get_dispatcher_info() -> Dict[str, Any]`
Получить информацию о диспетчерах.

**Возвращает:**
- `Dict[str, Any]` - информация о `channel_dispatcher` и `message_dispatcher`

---

## Приватные методы (Internal API)

Эти методы используются внутри класса и не предназначены для внешнего использования.

### `_init_default_handlers() -> None`
Инициализация обработчиков по умолчанию для диспетчера каналов:
- `log_message` - для логических сообщений
- `broadcast_message` - для широковещательных сообщений
- `default_queue` - обработчик по умолчанию

### `_get_dispatch_key(message: Dict[str, Any]) -> str`
Определяет ключ для диспетчера на основе сообщения.

**Приоритет определения:**
1. Поле `command` для командных сообщений
2. Поле `type` для типизированных сообщений
3. Автоматическое определение по содержимому
4. По умолчанию: `default_queue`

### `_send_via_channel(message, channel_name) -> Dict[str, Any]`
Отправка сообщения через конкретный канал.

### `_handle_send_error(error_msg: str) -> Dict[str, Any]`
Обработка ошибок отправки.

### `_handle_log_message(message) -> Dict[str, Any]`
Обработчик для логических сообщений (возвращает `{'channel': 'log_channel'}`).

### `_handle_broadcast_message(message) -> Dict[str, Any]`
Обработчик для широковещательных сообщений.

### `_handle_default_queue(message) -> Dict[str, Any]`
Обработчик по умолчанию для очередей.

### `_poll_all_channels(timeout: float) -> List[Dict[str, Any]]`
Получить сообщения со всех зарегистрированных каналов.

### `_listen_loop(poll_interval: float) -> None`
Цикл асинхронного прослушивания.

### `_log(level: str, message: str) -> None`
Внутреннее логирование (делегирует в logger если передан).

### `_log_debug/info/warning/error(message: str) -> None`
Удобные обертки для логирования разных уровней.

---

## Создание роутера

### Через конструктор

```python
from src.Modules.Router_module.router_manager import RouterManager
from src.Modules.Dispatch_module import DispatchStrategy

router = RouterManager(
    router_id="my_router",
    logger=my_logger,  # опционально
    queue_registry=my_queue_registry,  # опционально
    dispatch_strategy=DispatchStrategy.EXACT_MATCH
)
```

### Через фабрику

```python
from src.Modules.Router_module.router_manager import create_router

router = create_router(
    router_id="my_router",
    logger=my_logger,
    channels=[channel1, channel2],  # опционально
    dispatch_strategy=DispatchStrategy.EXACT_MATCH
)
```

---

## Примеры использования

### Базовый пример

```python
from src.Modules.Router_module.router_manager import RouterManager
from src.Modules.Router_module.channel import QueueChannel

# Создаем роутер
router = RouterManager("test_router")

# Регистрируем канал
queue_channel = QueueChannel("internal_queue")
router.register_channel(queue_channel)

# Отправляем сообщение
result = router.send({
    'type': 'command',
    'command': 'process',
    'data': {'file': 'test.txt'}
})

# Получаем сообщения
messages = router.receive(timeout=0.1)
```

### С кастомными обработчиками

```python
def select_priority_channel(message):
    if message.get('priority') == 'high':
        return {'channel': 'priority_queue'}
    return {'channel': 'normal_queue'}

router.register_channel_handler('high_priority', select_priority_channel)
```

### Асинхронное прослушивание

```python
def message_handler(message):
    print(f"Received: {message}")

router.add_message_callback(message_handler)
router.start_listening(poll_interval=0.01)

# ... работа приложения ...

# Остановка прослушивания
router.stop_listening()
router.cleanup()
```

### Использование в multiprocessing

**Важно:** RouterManager должен создаваться в каждом процессе отдельно, так как содержит несериализуемые объекты (threading.Thread, Queue).

```python
from multiprocessing import Process, Queue as MPQueue
from src.Modules.Router_module.router_manager import RouterManager
from src.Modules.Router_module.channel import QueueChannel

def worker_process():
    # Создаем роутер в процессе
    router = RouterManager("worker_router")
    
    # Создаем канал с multiprocessing.Queue
    mp_queue = MPQueue()
    channel = QueueChannel("internal_queue", mp_queue)
    router.register_channel(channel)
    
    try:
        router.start_listening()
        # ... работа процесса ...
    finally:
        router.cleanup()

if __name__ == '__main__':
    process = Process(target=worker_process)
    process.start()
    process.join()
```

---

## Принципы проектирования

### Единственная ответственность
- Роутер отвечает только за маршрутизацию сообщений
- Логирование, статистика, обработка ошибок делегируются внешним менеджерам

### Зависимости
- Зависит только от базового интерфейса `MessageChannel`
- Не знает о конкретных реализациях каналов (QueueChannel, LogChannel и т.д.)

### Расширяемость
- Каналы регистрируются извне
- Обработчики могут быть зарегистрированы динамически
- Диспетчеры настраиваются через стратегии

---

## Зависимости

- `MessageChannel` (базовый интерфейс из `.channel`)
- `Dispatcher` (из `src.Modules.Dispatch_module`)
- `DispatchStrategy` (из того же модуля)
- `BaseAdapter` (из `src.Modules.Base_manager_module.base_adapter`)

---

## Сериализация для multiprocessing

### Что сериализуется ✅

- Базовый RouterManager (без активного потока)
- Статистика и конфигурация
- Параметры инициализации

### Что НЕ сериализуется ❌

- `threading.Thread` объекты - не сериализуются
- `queue.Queue` объекты - не сериализуются (используйте `multiprocessing.Queue`)
- Callable функции в обработчиках - могут не сериализоваться

### Рекомендации

1. **Создавать RouterManager в каждом процессе отдельно**
   - Не передавать RouterManager между процессами через pickle
   - Использовать только сериализуемые данные (словари, списки)

2. **Использовать multiprocessing.Queue для межпроцессных каналов**
   - QueueChannel должен работать с multiprocessing.Queue
   - Очереди создаются отдельно в каждом процессе

3. **Корректная очистка ресурсов**
   - Всегда вызывать `cleanup()` при завершении процесса
   - Использовать try/finally для гарантированной очистки

---

## Примечания

1. Статистика (`_stats`) временно хранится внутри роутера, в будущем может быть вынесена в отдельный менеджер статистики
2. Логирование временно реализовано через приватные методы, в будущем будет делегироваться менеджеру логирования
3. Обработчики по умолчанию можно переопределить через `register_channel_handler`
4. Для корректного завершения всегда вызывайте `cleanup()` или `stop_listening()` перед уничтожением роутера



