# Руководство по работе со сценариями

## Введение

Сценарии позволяют создавать цепочки обработчиков, которые выполняются последовательно. Это полезно для сложных пайплайнов обработки данных.

## Основные концепции

### Сценарий

Сценарий - это именованная цепочка обработчиков, которые выполняются последовательно по порядку stage.

### Этап (Stage)

Каждый обработчик в сценарии имеет stage - номер этапа выполнения. Обработчики выполняются в порядке возрастания stage.

### Передача данных

Результат предыдущего этапа передается следующему этапу как входные данные.

## Создание сценариев

### Базовое создание

```python
dispatcher = Dispatcher("scenario_dispatcher")

# Создание сценария
dispatcher.create_scenario(
    "image_processing",
    description="Обработка изображений",
    metadata={"type": "vision"}
)
```

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
```

## Добавление обработчиков в сценарий

### Базовое добавление

```python
def preprocess(data):
    return {"preprocessed": True, "data": data}

dispatcher.add_handler_to_scenario(
    "image_processing",
    "preprocess",
    preprocess,
    stage=1
)
```

### Добавление с метаданными

```python
dispatcher.add_handler_to_scenario(
    "image_processing",
    "preprocess",
    preprocess,
    stage=1,
    metadata={"version": "1.0", "category": "vision"},
    tags=["preprocessing", "image"]
)
```

### Добавление с полным сообщением

```python
def full_message_handler(message):
    # Получает полное сообщение, а не только data
    command = message.get("command")
    data = message.get("data", {})
    return {"command": command, "processed": True}

dispatcher.add_handler_to_scenario(
    "image_processing",
    "preprocess",
    full_message_handler,
    stage=1,
    expects_full_message=True
)
```

## Выполнение сценариев

### Базовое выполнение

```python
result = dispatcher.dispatch_scenario(
    "image_processing",
    {"data": {"image": "test.jpg"}}
)
```

### Выполнение через dispatch

```python
# Если ключ совпадает с именем сценария
result = dispatcher.dispatch({
    "command": "image_processing",
    "data": {"image": "test.jpg"}
})

# Или явно указать сценарий
result = dispatcher.dispatch({
    "command": "process",
    "scenario": "image_processing",
    "data": {"image": "test.jpg"}
})
```

### Обработка ошибок

```python
# Остановка при ошибке (по умолчанию)
result = dispatcher.dispatch_scenario(
    "image_processing",
    {"data": {"image": "test.jpg"}},
    stop_on_error=True
)

# Продолжение при ошибке
result = dispatcher.dispatch_scenario(
    "image_processing",
    {"data": {"image": "test.jpg"}},
    stop_on_error=False
)
```

## Передача данных между этапами

### Автоматическая передача

Результат предыдущего этапа автоматически передается следующему:

```python
def step1(data):
    return {"step1": "done", "data": {"value": 10}}

def step2(data):
    # Получит {"value": 10}
    value = data.get("value", 0)
    return {"step2": "done", "value": value + 1}

dispatcher.add_handler_to_scenario("scenario", "step1", step1, stage=1)
dispatcher.add_handler_to_scenario("scenario", "step2", step2, stage=2)
```

### Использование поля "data"

Если результат содержит поле "data", оно используется для следующего этапа:

```python
def step1(data):
    return {"status": "ok", "data": {"processed": True}}
    # Следующий этап получит {"processed": True}

def step2(data):
    return {"status": "ok", "result": data}
    # Получит {"processed": True}
```

### Использование expects_full_message

Если обработчик использует `expects_full_message=True`, он получает полное сообщение:

```python
def full_message_handler(message):
    # Получает полное сообщение со всеми полями
    command = message.get("command")
    data = message.get("data", {})
    return {"command": command, "processed": True}

dispatcher.add_handler_to_scenario(
    "scenario",
    "handler",
    full_message_handler,
    stage=1,
    expects_full_message=True
)
```

## Управление сценариями

### Получение информации

```python
# Получение информации о сценарии
info = dispatcher.get_scenario_info("image_processing")
print(info)
# {
#     "name": "image_processing",
#     "description": "Обработка изображений",
#     "metadata": {...},
#     "handlers_count": 3,
#     "handlers": [...]
# }
```

### Получение всех сценариев

```python
all_scenarios = dispatcher.get_all_scenarios()
for scenario in all_scenarios:
    print(f"Scenario: {scenario['name']}, Handlers: {scenario['handlers_count']}")
```

### Обновление метаданных

```python
dispatcher.update_scenario_metadata(
    "image_processing",
    {"version": "2.0", "updated": True}
)
```

### Обновление описания

```python
dispatcher.update_scenario_description(
    "image_processing",
    "Новое описание сценария"
)
```

### Удаление обработчика

```python
dispatcher.remove_handler_from_scenario("image_processing", "preprocess")
```

### Изменение порядка обработчика

```python
dispatcher.reorder_handler_in_scenario("image_processing", "preprocess", new_stage=3)
```

### Удаление сценария

```python
dispatcher.delete_scenario("image_processing")
```

## Примеры использования

### Пример 1: Простой пайплайн обработки

```python
dispatcher = Dispatcher("pipeline")

# Создание сценария
dispatcher.create_scenario("data_pipeline", "Обработка данных")

# Этап 1: Загрузка данных
def load_data(data):
    return {"loaded": True, "data": {"items": [1, 2, 3]}}

# Этап 2: Обработка данных
def process_data(data):
    items = data.get("items", [])
    return {"processed": True, "data": {"result": sum(items)}}

# Этап 3: Сохранение результатов
def save_results(data):
    result = data.get("result", 0)
    return {"saved": True, "result": result}

# Добавление этапов
dispatcher.add_handler_to_scenario("data_pipeline", "load", load_data, stage=1)
dispatcher.add_handler_to_scenario("data_pipeline", "process", process_data, stage=2)
dispatcher.add_handler_to_scenario("data_pipeline", "save", save_results, stage=3)

# Выполнение
result = dispatcher.dispatch_scenario("data_pipeline", {"data": {}})
```

### Пример 2: Обработка изображений

```python
dispatcher = Dispatcher("image_processor")

dispatcher.create_scenario("image_pipeline", "Полный пайплайн обработки изображений")

# Этап 1: Предобработка
def preprocess(data):
    image = data.get("image")
    return {"preprocessed": True, "data": {"image": image, "size": (800, 600)}}

# Этап 2: Детекция объектов
def detect_objects(data):
    image = data.get("image")
    size = data.get("size")
    objects = ["bottle", "cap"]
    return {"detected": True, "data": {"objects": objects, "size": size}}

# Этап 3: Классификация дефектов
def classify_defects(data):
    objects = data.get("objects", [])
    defects = {obj: "ok" if obj == "bottle" else "defect" for obj in objects}
    return {"classified": True, "defects": defects}

# Добавление этапов
dispatcher.add_handler_to_scenario("image_pipeline", "preprocess", preprocess, stage=1)
dispatcher.add_handler_to_scenario("image_pipeline", "detect", detect_objects, stage=2)
dispatcher.add_handler_to_scenario("image_pipeline", "classify", classify_defects, stage=3)

# Выполнение
result = dispatcher.dispatch_scenario("image_pipeline", {
    "data": {"image": "bottle_image.jpg"}
})
```

### Пример 3: Использование ScenarioBuilder

```python
from multiprocess_framework.refactored.modules.dispatch_module import ScenarioBuilder

dispatcher = Dispatcher("builder_test")
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

# Проверка существования
if builder.exists("my_scenario"):
    print("Сценарий существует")

# Получение всех сценариев
all_scenarios = builder.list_all()
```

## Лучшие практики

1. **Используйте понятные имена** для сценариев и обработчиков
2. **Добавляйте описания** для документирования сценариев
3. **Используйте метаданные** для хранения дополнительной информации
4. **Группируйте обработчики по тегам** для удобства управления
5. **Используйте stage для контроля порядка** выполнения
6. **Обрабатывайте ошибки** на каждом этапе
7. **Используйте stop_on_error** для контроля поведения при ошибках

## Дополнительные ресурсы

- [USAGE_GUIDE.md](USAGE_GUIDE.md) - Руководство по использованию
- [ARCHITECTURE.md](ARCHITECTURE.md) - Архитектура модуля
- [STRATEGIES_GUIDE.md](STRATEGIES_GUIDE.md) - Руководство по стратегиям
- [API_REFERENCE.md](API_REFERENCE.md) - Справочник API

