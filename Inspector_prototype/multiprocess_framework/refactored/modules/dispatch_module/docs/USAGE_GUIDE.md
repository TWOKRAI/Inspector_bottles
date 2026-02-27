# Руководство по использованию DispatchModule

## Введение

DispatchModule предоставляет гибкую систему маршрутизации и обработки сообщений с поддержкой различных стратегий диспетчеризации.

## Быстрый старт

### Базовое использование

```python
from multiprocess_framework.refactored.modules.dispatch_module import Dispatcher, DispatchStrategy

# Создание диспетчера (менеджера)
dispatcher = Dispatcher("my_dispatcher")

# Инициализация менеджера
dispatcher.initialize()

# Регистрация обработчика
def process_data(data):
    return {"result": data.get("value", 0) * 2}

dispatcher.register_handler("process", process_data)

# Диспетчеризация сообщения
message = {"command": "process", "data": {"value": 5}}
result = dispatcher.dispatch(message)
print(result)  # {"result": 10}

# Завершение работы менеджера
dispatcher.shutdown()
```

## Регистрация обработчиков

### Простая регистрация

```python
def handler(data):
    return {"processed": True, "data": data}

dispatcher.register_handler("process", handler)
```

### Регистрация с метаданными

```python
dispatcher.register_handler(
    "process",
    handler,
    metadata={"category": "vision", "version": "1.0"},
    tags=["image", "processing"],
    efficiency=10
)
```

### Регистрация с полным сообщением

```python
def full_message_handler(message):
    # Получает полное сообщение, а не только data
    command = message.get("command")
    data = message.get("data", {})
    return {"command": command, "processed": True}

dispatcher.register_handler(
    "process",
    full_message_handler,
    expects_full_message=True
)
```

## Использование стратегий

### EXACT_MATCH (по умолчанию)

Самая быстрая стратегия - точное совпадение ключей:

```python
dispatcher.register_handler("process", handler)

# Обработает только сообщения с command="process"
result = dispatcher.dispatch({"command": "process", "data": {}})
```

### PATTERN_MATCH

Гибкая маршрутизация по регулярным выражениям:

```python
dispatcher.register_handler(
    r"process_\d+",
    handler,
    strategy=DispatchStrategy.PATTERN_MATCH
)

# Обработает: process_1, process_123, process_999
result = dispatcher.dispatch({"command": "process_123", "data": {}})
```

### FALLBACK_MATCH

Несколько обработчиков с одним ключом, выбор по эффективности:

```python
# Медленный универсальный обработчик
def slow_handler(data):
    return {"result": "slow"}

dispatcher.register_handler(
    "process",
    slow_handler,
    strategy=DispatchStrategy.FALLBACK_MATCH,
    efficiency=1
)

# Быстрый специализированный обработчик
def fast_handler(data):
    return {"result": "fast"}

dispatcher.register_handler(
    "process",
    fast_handler,
    strategy=DispatchStrategy.FALLBACK_MATCH,
    efficiency=10
)

# Будет использован fast_handler
result = dispatcher.dispatch({
    "command": "process",
    "strategy": "fallback",
    "data": {}
})
```

### CHAIN_MATCH (Сценарии)

Последовательное выполнение обработчиков:

```python
# Создание сценария
dispatcher.create_scenario("image_processing", "Обработка изображений")

# Добавление обработчиков
def preprocess(data):
    return {"preprocessed": True, "data": data}

def process(data):
    return {"processed": True, "result": data}

dispatcher.add_handler_to_scenario("image_processing", "preprocess", preprocess, stage=1)
dispatcher.add_handler_to_scenario("image_processing", "process", process, stage=2)

# Выполнение сценария
result = dispatcher.dispatch({"command": "image_processing", "data": {"image": "test.jpg"}})
```

## Работа со сценариями

### Использование ScenarioBuilder

```python
from multiprocess_framework.refactored.modules.dispatch_module import ScenarioBuilder

builder = ScenarioBuilder(dispatcher)

# Создание сценария
builder.create("my_scenario", "Описание сценария")

# Добавление обработчиков
def step1(data):
    return {"step": 1}

def step2(data):
    return {"step": 2}

builder.add_handler("my_scenario", "step1", step1, stage=1)
builder.add_handler("my_scenario", "step2", step2, stage=2)

# Получение информации
info = builder.get_info("my_scenario")
print(info)
```

### Управление сценариями

```python
# Создание
dispatcher.create_scenario("scenario_name", "Описание", {"metadata": "value"})

# Получение информации
info = dispatcher.get_scenario_info("scenario_name")

# Обновление метаданных
dispatcher.update_scenario_metadata("scenario_name", {"new": "metadata"})

# Удаление
dispatcher.delete_scenario("scenario_name")

# Получение всех сценариев
all_scenarios = dispatcher.get_all_scenarios()
```

## Интеграция с ObservableMixin

### Логирование

```python
from multiprocess_framework.modules.Logger_module import LoggerManager

logger = LoggerManager("dispatcher_logger")
dispatcher = Dispatcher(
    "my_dispatcher",
    managers={'logger': logger},
    config={'logger': True}
)

# Все операции будут логироваться автоматически
dispatcher.register_handler("test", handler)
dispatcher.dispatch({"command": "test", "data": {}})
```

### Статистика

```python
dispatcher = Dispatcher(
    "my_dispatcher",
    managers={'statistics': stats_manager},
    config={'statistics': True}
)

# Метрики собираются автоматически
dispatcher.dispatch({"command": "process", "data": {}})
```

## Поиск и фильтрация обработчиков

### Получение информации об обработчике

```python
handler_info = dispatcher.get_handler_info("process")
print(handler_info)
# {
#     "key": "process",
#     "metadata": {...},
#     "efficiency": 10,
#     "tags": ["vision"],
#     "stage": 0
# }
```

### Получение всех обработчиков

```python
all_handlers = dispatcher.get_all_handlers()
for handler in all_handlers:
    print(f"Key: {handler['key']}, Tags: {handler['tags']}")
```

### Поиск по тегам

```python
vision_handlers = dispatcher.get_handlers_by_tag("vision")
for handler in vision_handlers:
    print(f"Vision handler: {handler['key']}")
```

## Обновление обработчиков

### Обновление метаданных

```python
dispatcher.update_handler_metadata(
    "process",
    {"version": "2.0", "updated": True}
)
```

### Обновление эффективности

```python
dispatcher.update_handler_efficiency("process", 20)
```

### Обновление тегов

```python
dispatcher.update_handler_tags("process", ["vision", "high_priority"])
```

### Обновление функции обработчика

```python
def new_handler(data):
    return {"new": "result"}

dispatcher.update_handler_function("process", new_handler)
```

## Обработка ошибок

### Обработка отсутствующих обработчиков

```python
result = dispatcher.dispatch({"command": "unknown", "data": {}})
if result.get("status") == "error":
    print(f"Error: {result.get('reason')}")
```

### Обработка ошибок в обработчиках

```python
def failing_handler(data):
    raise ValueError("Error in handler")

dispatcher.register_handler("fail", failing_handler)
result = dispatcher.dispatch({"command": "fail", "data": {}})
# {"status": "error", "reason": "Dispatch failed: Error in handler"}
```

## Примеры использования

### Пример 1: Простая маршрутизация команд

```python
dispatcher = Dispatcher("command_router")

# Регистрация обработчиков
dispatcher.register_handler("start", lambda data: {"status": "started"})
dispatcher.register_handler("stop", lambda data: {"status": "stopped"})
dispatcher.register_handler("status", lambda data: {"status": "running"})

# Использование
result = dispatcher.dispatch({"command": "start", "data": {}})
print(result)  # {"status": "started"}
```

### Пример 2: Обработка изображений с паттернами

```python
dispatcher = Dispatcher("image_processor")

def process_image(data):
    image_id = data.get("image_id")
    return {"processed": True, "image_id": image_id}

dispatcher.register_handler(
    r"process_image_\d+",
    process_image,
    strategy=DispatchStrategy.PATTERN_MATCH
)

# Обработает: process_image_1, process_image_123 и т.д.
result = dispatcher.dispatch({
    "command": "process_image_123",
    "strategy": "pattern",
    "data": {"image_id": 123}
})
```

### Пример 3: Сложный сценарий обработки

```python
dispatcher = Dispatcher("complex_processor")

# Создание сценария
dispatcher.create_scenario(
    "image_pipeline",
    description="Полный пайплайн обработки изображений"
)

# Этап 1: Предобработка
def preprocess(data):
    image = data.get("image")
    return {"preprocessed": True, "image": image, "data": {"image": image}}

# Этап 2: Детекция объектов
def detect_objects(data):
    image = data.get("image")
    objects = ["bottle", "cap"]
    return {"detected": True, "objects": objects, "data": {"objects": objects}}

# Этап 3: Классификация дефектов
def classify_defects(data):
    objects = data.get("objects", [])
    defects = {"bottle": "ok", "cap": "defect"}
    return {"classified": True, "defects": defects}

# Добавление этапов
dispatcher.add_handler_to_scenario("image_pipeline", "preprocess", preprocess, stage=1)
dispatcher.add_handler_to_scenario("image_pipeline", "detect", detect_objects, stage=2)
dispatcher.add_handler_to_scenario("image_pipeline", "classify", classify_defects, stage=3)

# Выполнение сценария
result = dispatcher.dispatch_scenario("image_pipeline", {
    "data": {"image": "bottle_image.jpg"}
})

print(result)
# {
#     "status": "success",
#     "scenario": "image_pipeline",
#     "stages": [...],
#     "final_result": {...}
# }
```

## Лучшие практики

1. **Используйте EXACT_MATCH для максимальной производительности** когда ключи известны заранее

2. **Используйте PATTERN_MATCH только когда необходимо** - он медленнее чем EXACT_MATCH

3. **Группируйте обработчики по тегам** для удобства управления

4. **Используйте метаданные** для хранения дополнительной информации об обработчиках

5. **Используйте сценарии** для сложных последовательных операций

6. **Настраивайте эффективность** для FALLBACK_MATCH стратегии

7. **Используйте ObservableMixin** для логирования и мониторинга

## Дополнительные ресурсы

- [ARCHITECTURE.md](ARCHITECTURE.md) - Архитектура модуля
- [STRATEGIES_GUIDE.md](STRATEGIES_GUIDE.md) - Детальное описание стратегий
- [SCENARIOS_GUIDE.md](SCENARIOS_GUIDE.md) - Руководство по сценариям
- [API_REFERENCE.md](API_REFERENCE.md) - Справочник API

