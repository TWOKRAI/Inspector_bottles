# Message Module v2.0

Универсальная система сообщений для межпроцессного взаимодействия.

## 🎯 Философия

- **Один класс для всех** - `Message` инкапсулирует всю логику работы с сообщениями
- **Простота использования** - создал, наполнил, отправил
- **Fluent API** - цепочки методов для удобного наполнения данными
- **Типобезопасность** - Enum'ы для типов, приоритетов и уровней логирования
- **Валидация** - автоматическая проверка перед отправкой
- **Гибкость** - поддержка множества форматов (dict, JSON, YAML, text)

## 📦 Структура модуля

```
Message_module/
├── message.py           # Основной класс Message
├── message_types.py     # Типы, Enum'ы, схемы
├── examples.py          # Примеры использования
├── __init__.py          # Экспорты
└── README.md            # Документация
```

## 🚀 Быстрый старт

### Установка

```python
from src.Modules.Message_module import Message, MessageType, Priority
```

### Создание простого сообщения

```python
# Командное сообщение
msg = Message.create(
    type=MessageType.COMMAND,
    sender="GUI",
    targets=["Worker"],
    command="process_image",
    args={"image_id": 123}
)

# Получение словаря для отправки
data = msg.to_dict()
```

### Использование Fluent API

```python
msg = (Message.create(
    type=MessageType.GENERAL,
    sender="Process1",
    targets=["Process2"]
)
.set_content({"message": "Hello"})
.set_priority(Priority.HIGH)
.add_metadata("user_id", "12345")
)
```

## 📋 Типы сообщений

### 1. GENERAL - Обычное сообщение

Для передачи произвольных данных между процессами.

```python
msg = Message.create(
    type=MessageType.GENERAL,
    sender="Process1",
    targets=["Process2"],
    content={"data": "Hello World"}
)
```

**Обязательные поля:** `content`

### 2. COMMAND - Командное сообщение

Для выполнения команд и действий.

```python
msg = Message.create(
    type=MessageType.COMMAND,
    sender="GUI",
    targets=["Worker"],
    command="process_image",
    args={"image_id": 123, "filters": ["blur"]},
    need_ack=True
)
```

**Обязательные поля:** `command`

### 3. LOG - Лог-сообщение

Для централизованного логирования.

```python
msg = Message.create(
    type=MessageType.LOG,
    sender="VisionProcess",
    level="error",
    message="Failed to capture frame",
    module="camera"
)
```

**Обязательные поля:** `level`, `message`  
**Автоматические значения:** `targets=["logger"]`, `routers=["log"]`

### 4. SYSTEM - Системное сообщение

Для управления процессами.

```python
msg = (Message.create(
    type=MessageType.SYSTEM,
    sender="ProcessManager",
    targets=["all"]
)
.set_system_action("shutdown", {"reason": "user_request"})
)
```

**Обязательные поля:** `action`

### 5. BROADCAST - Широковещательное сообщение

Для отправки всем процессам.

```python
msg = Message.create(
    type=MessageType.BROADCAST,
    sender="ProcessManager",
    content="System update available",
    exclude=["Logger"]  # Исключить из рассылки
)
```

**Обязательные поля:** `content`  
**Автоматические значения:** `targets=["all"]`

### 6. DATA - Сообщение с данными

Для передачи больших объемов данных (может использовать shared memory).

```python
msg = Message.create(
    type=MessageType.DATA,
    sender="Camera",
    targets=["VisionProcess"],
    data_type="image",
    use_shared_memory=True,
    memory_key="frame_buffer_001"
)
```

**Обязательные поля:** `data_type`

### 7. REQUEST - Запрос

Сообщение, ожидающее ответа.

```python
msg = Message.create(
    type=MessageType.REQUEST,
    sender="GUI",
    targets=["Database"],
    request_type="query",
    query="SELECT * FROM users",
    timeout=5.0
)
```

**Обязательные поля:** `request_type`

### 8. RESPONSE - Ответ

Ответ на запрос.

```python
msg = Message.create(
    type=MessageType.RESPONSE,
    sender="Database",
    targets=["GUI"],
    request_id="req_abc123",
    success=True,
    result={"users": [...]}
)
```

**Обязательные поля:** `request_id`

### 9. EVENT - Событие

Событийное сообщение (pub/sub паттерн).

```python
msg = (Message.create(
    type=MessageType.EVENT,
    sender="Camera"
)
.set_event("frame_captured", {"frame_id": 999, "fps": 30})
)
```

**Обязательные поля:** `event_type`  
**Автоматические значения:** `targets=["all"]`

## 🛠️ API Reference

### Создание сообщений

#### `Message.create(type, sender, **kwargs)`

Фабричный метод для создания сообщений.

```python
msg = Message.create(
    type=MessageType.COMMAND,
    sender="GUI",
    targets=["Worker"],
    command="process"
)
```

#### `create_message(type, sender, **kwargs)`

Вспомогательная функция (алиас для `Message.create`).

### Fluent API методы

#### Общие методы

- `set_priority(priority)` - установить приоритет
- `set_targets(targets)` - установить получателей
- `add_target(target)` - добавить получателя
- `set_routers(routers)` - установить роутеры
- `add_router(router)` - добавить роутер
- `set_channel(channel)` - установить канал доставки
- `add_metadata(key, value)` - добавить метаданные
- `set_metadata(metadata)` - установить все метаданные

#### Специфичные методы

- `set_content(content)` - для GENERAL
- `set_command(command, args)` - для COMMAND
- `set_args(args)` / `add_arg(key, value)` - для COMMAND
- `set_log(level, message, module)` - для LOG
- `set_system_action(action, data)` - для SYSTEM
- `set_data(data, data_type)` - для DATA
- `set_event(event_type, event_data)` - для EVENT
- `set_need_ack(need_ack)` - для COMMAND

### Валидация

#### `validate()`

Валидирует сообщение, выбрасывает `MessageValidationError` при ошибке.

```python
try:
    msg.validate()
except MessageValidationError as e:
    print(f"Validation error: {e}")
```

#### `is_valid()`

Проверяет валидность без выброса исключения.

```python
if msg.is_valid():
    # отправить
```

### Конвертация

#### `to_dict(exclude_none=True, exclude_fields=None, include_fields=None)`

Конвертирует в словарь.

```python
data = msg.to_dict()
data = msg.to_dict(exclude_fields={"metadata", "timestamp"})
data = msg.to_dict(include_fields={"type", "sender", "targets"})
```

#### `to_json(exclude_none=True, exclude_fields=None, include_fields=None, indent=None)`

Конвертирует в JSON строку.

```python
json_str = msg.to_json()
json_str = msg.to_json(indent=2)  # С форматированием
```

#### `to_yaml(exclude_none=True, exclude_fields=None, include_fields=None)`

Конвертирует в YAML строку (требует PyYAML).

```python
yaml_str = msg.to_yaml()
```

#### `to_text(exclude_none=True, exclude_fields=None, include_fields=None)`

Конвертирует в текстовый формат (key: value).

```python
text = msg.to_text()
```

### Парсинг

#### `Message.from_dict(data)`

Создает сообщение из словаря.

```python
msg = Message.from_dict({"type": "general", "sender": "Test", ...})
```

#### `Message.from_json(json_str)`

Создает сообщение из JSON строки.

```python
msg = Message.from_json('{"type": "general", ...}')
```

#### `Message.from_yaml(yaml_str)`

Создает сообщение из YAML строки.

```python
msg = Message.from_yaml('type: general\nsender: Test\n...')
```

#### `parse_message(data)`

Автоматически определяет формат и парсит.

```python
msg = parse_message(json_str)  # или dict, или yaml
```

### Вспомогательные методы

- `get_type()` - возвращает `MessageType` enum
- `get_priority()` - возвращает `Priority` enum
- `get_log_level()` - возвращает `LogLevel` enum (для LOG)
- `clone()` - создает копию с новым ID

## 🔄 Интеграция с Router

Отправка сообщений делегируется роутеру. Роутер получает объект `Message` и использует его методы для получения данных.

### В Router Manager

```python
class RouterManager:
    def send(self, message: Message) -> Dict[str, Any]:
        """Отправка сообщения."""
        # Валидация
        if not message.is_valid():
            return {"status": "error", "message": "Invalid message"}
        
        # Получение данных
        data = message.to_dict()
        
        # Определение канала
        channel = message.channel or self._get_default_channel(message.type)
        
        # Отправка по роутерам
        for router_name in message.routers:
            router = self._get_router(router_name)
            router.route(data, channel)
        
        return {"status": "success", "message_id": message.id}
```

### Использование

```python
# Создаем сообщение
msg = Message.create(
    type=MessageType.COMMAND,
    sender="GUI",
    targets=["Worker"],
    command="process"
)

# Отправляем через роутер
result = router.send(msg)
```

## 📊 Примеры использования

### Пример 1: Простая команда

```python
msg = Message.create(
    type=MessageType.COMMAND,
    sender="GUI",
    targets=["Worker"],
    command="start_processing"
)

router.send(msg)
```

### Пример 2: Сложный workflow

```python
# 1. Отправка команды
command = (Message.create(
    type=MessageType.COMMAND,
    sender="GUI",
    targets=["ImageProcessor"]
)
.set_command("process_image", {"image_id": 42})
.set_priority(Priority.HIGH)
.set_need_ack(True)
)

router.send(command)

# 2. Логирование
log = Message.create(
    type=MessageType.LOG,
    sender="ImageProcessor",
    level="info",
    message="Processing started"
)

router.send(log)

# 3. Отправка события
event = (Message.create(
    type=MessageType.EVENT,
    sender="ImageProcessor"
)
.set_event("processing_started", {"image_id": 42})
)

router.send(event)
```

### Пример 3: Request-Response

```python
# Запрос
request = Message.create(
    type=MessageType.REQUEST,
    sender="GUI",
    targets=["Database"],
    request_type="query",
    query="SELECT * FROM users"
)

router.send(request)

# Ответ (в другом процессе)
response = Message.create(
    type=MessageType.RESPONSE,
    sender="Database",
    targets=["GUI"],
    request_id=request.id,
    success=True,
    result={"users": [...]}
)

router.send(response)
```

## ⚙️ Конфигурация

### Дефолтные значения для типов

Каждый тип сообщения имеет свои дефолтные значения, определенные в `MESSAGE_TYPE_DEFAULTS`:

- `channel` - канал доставки по умолчанию
- `targets` - получатели по умолчанию
- `routers` - роутеры по умолчанию
- `required_fields` - обязательные поля для валидации

### Исключаемые поля

Некоторые типы сообщений исключают определенные поля при сериализации (определено в `MESSAGE_TYPE_EXCLUDE_FIELDS`):

- LOG: исключает `routers` из словаря

## 🧪 Тестирование

### Запуск тестов

```bash
# Из корня проекта
python -m pytest tests/Test_Message_module/ -v

# С покрытием кода
python -m pytest tests/Test_Message_module/ --cov=src/Modules/Message_module --cov-report=term-missing
```

### Статистика тестов

- **Всего тестов:** 69
- **Покрытие кода:** 91%
- **Статус:** ✅ Все тесты проходят

Подробнее о тестах: [tests/Test_Message_module/README.md](../../../tests/Test_Message_module/README.md)

## 📝 Миграция со старой версии

### Было (старая версия)

```python
from src.Modules.Message_module import MessageManager, MessageAdapter

manager = MessageManager("Process1")
adapter = MessageAdapter(manager)

msg = adapter.create_command(
    command="process",
    args={"id": 123},
    targets=["Worker"]
)

# Отправка через роутер
router.send(msg.to_dict())
```

### Стало (новая версия)

```python
from src.Modules.Message_module import Message, MessageType

msg = Message.create(
    type=MessageType.COMMAND,
    sender="Process1",
    targets=["Worker"],
    command="process",
    args={"id": 123}
)

# Отправка через роутер
router.send(msg)
```

## 🎨 Преимущества новой версии

1. **Простота** - один класс вместо трех (Manager, Adapter, Converter)
2. **Элегантность** - Fluent API для цепочек вызовов
3. **Инкапсуляция** - вся логика в одном месте
4. **Гибкость** - легко расширяется новыми типами
5. **Типобезопасность** - Enum'ы вместо строк
6. **Удобство** - множество вспомогательных методов

## 📚 Дополнительные ресурсы

- `examples.py` - 13 подробных примеров использования
- `message_types.py` - все типы и схемы
- `message.py` - полная документация в docstrings

## 🔮 Будущие улучшения

- [ ] Поддержка асинхронной отправки
- [ ] Сериализация в Protobuf
- [ ] Компрессия больших сообщений
- [ ] Шифрование чувствительных данных
- [ ] Метрики и мониторинг

