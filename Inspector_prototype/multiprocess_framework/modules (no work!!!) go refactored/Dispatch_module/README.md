# Модуль диспетчеризации сообщений (Dispatch_module)

## Описание

Модуль `Dispatch_module` предоставляет гибкую систему маршрутизации и обработки сообщений с поддержкой различных стратегий диспетчеризации. Модуль позволяет регистрировать обработчики сообщений и автоматически направлять входящие сообщения к соответствующим обработчикам.

## Основные возможности

- ✅ **Множественные стратегии диспетчеризации** - поддержка 4 различных стратегий одновременно
- ✅ **Точное совпадение** - быстрая маршрутизация по точному ключу
- ✅ **Паттерн-матчинг** - гибкая маршрутизация по регулярным выражениям
- ✅ **Fallback стратегия** - выбор обработчика по эффективности
- ✅ **Сценарии (цепочки)** - последовательное выполнение обработчиков
- ✅ **Метаданные и теги** - организация и группировка обработчиков
- ✅ **Интеграция с ObservableMixin** - логирование, статистика, обработка ошибок

## Архитектура модуля

```
Dispatch_module/
├── __init__.py              # Экспорт основных классов
├── types.py                 # Типы данных (DispatchStrategy, HandlerInfo, Scenario)
├── base.py                  # Базовый класс BaseDispatcher
├── dispatcher.py            # Основной класс Dispatcher
├── scenario_builder.py     # Построитель сценариев
├── dispatch_handler.py      # Устаревший файл (для обратной совместимости)
└── strategies/             # Реализации стратегий
    ├── base_strategy.py     # Базовый класс стратегии
    ├── exact_match.py       # Стратегия точного совпадения
    ├── pattern_match.py     # Стратегия паттерн-матчинга
    ├── fallback_match.py    # Fallback стратегия
    └── chain_match.py       # Стратегия цепочек (сценариев)
```

## Основные классы

### DispatchStrategy (Enum)

Перечисление стратегий диспетчеризации:

- `EXACT_MATCH` - Точное совпадение ключей (самый быстрый)
- `PATTERN_MATCH` - Сопоставление по регулярным выражениям
- `FALLBACK_MATCH` - Fallback с приоритетом эффективности
- `CHAIN_MATCH` - Цепочки выполнения обработчиков (сценарии)

### HandlerInfo (dataclass)

Информация о зарегистрированном обработчике:

```python
@dataclass
class HandlerInfo:
    key: str                          # Уникальный ключ обработчика
    handler: Callable                 # Функция-обработчик
    expects_full_message: bool = False # Получает ли полное сообщение
    metadata: Dict[str, Any] = {}     # Метаданные обработчика
    efficiency: int = 0                # Уровень эффективности
    tags: Set[str] = set()             # Теги для группировки
    stage: int = 0                     # Этап выполнения (для сценариев)
```

### Scenario (dataclass)

Сценарий выполнения - цепочка обработчиков:

```python
@dataclass
class Scenario:
    name: str                         # Уникальное имя сценария
    handlers: List[HandlerInfo] = []  # Список обработчиков (отсортированы по stage)
    description: str = ""             # Описание сценария
    metadata: Dict[str, Any] = {}      # Метаданные сценария
```

### Dispatcher

Основной класс диспетчера, поддерживающий все стратегии одновременно.

## Быстрый старт

### Базовое использование

```python
from src.Modules.Dispatch_module import Dispatcher, DispatchStrategy

# Создание диспетчера
dispatcher = Dispatcher("my_dispatcher")

# Регистрация обработчика
def process_data(data):
    return {"result": data.get("value", 0) * 2}

dispatcher.register_handler("process", process_data)

# Диспетчеризация сообщения
message = {"command": "process", "data": {"value": 5}}
result = dispatcher.dispatch(message)
print(result)  # {"result": 10}
```

### Использование разных стратегий

```python
from src.Modules.Dispatch_module import Dispatcher, DispatchStrategy

dispatcher = Dispatcher("multi_strategy")

# 1. EXACT_MATCH (по умолчанию)
dispatcher.register_handler("exact_cmd", handler1)

# 2. PATTERN_MATCH
dispatcher.register_handler(
    r"pattern_\d+",
    handler2,
    strategy=DispatchStrategy.PATTERN_MATCH
)

# 3. FALLBACK_MATCH
dispatcher.register_handler(
    "fallback_cmd",
    handler3,
    strategy=DispatchStrategy.FALLBACK_MATCH,
    efficiency=10
)

# 4. Использование стратегии из сообщения
message = {
    "command": "pattern_123",
    "strategy": "pattern",
    "data": {}
}
result = dispatcher.dispatch(message)
```

### Работа со сценариями

```python
from src.Modules.Dispatch_module import Dispatcher, ScenarioBuilder

dispatcher = Dispatcher("scenario_dispatcher")

# Создание сценария
dispatcher.create_scenario(
    "image_processing",
    description="Обработка изображений",
    metadata={"type": "vision"}
)

# Добавление обработчиков в сценарий
def preprocess(data):
    return {"preprocessed": True, "data": data}

def process(data):
    return {"processed": True, "result": data}

dispatcher.add_handler_to_scenario("image_processing", "preprocess", preprocess, stage=1)
dispatcher.add_handler_to_scenario("image_processing", "process", process, stage=2)

# Выполнение сценария
message = {"data": {"image": "test.jpg"}}
result = dispatcher.dispatch_scenario("image_processing", message)

# Или через dispatch с ключом
message = {"command": "image_processing", "data": {"image": "test.jpg"}}
result = dispatcher.dispatch(message)
```

### Использование ScenarioBuilder

```python
from src.Modules.Dispatch_module import Dispatcher, ScenarioBuilder

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
```

## Детальное описание стратегий

### 1. EXACT_MATCH (Точное совпадение)

**Когда использовать:** Когда нужна максимальная производительность и ключи известны заранее.

**Особенности:**
- Самый быстрый поиск (O(1))
- Уникальные ключи для каждого обработчика
- Используется по умолчанию

**Пример:**

```python
dispatcher.register_handler("process", handler)
# Обработает только сообщения с command="process"
```

### 2. PATTERN_MATCH (Паттерн-матчинг)

**Когда использовать:** Когда нужно обрабатывать группы команд с похожими именами.

**Особенности:**
- Использует регулярные выражения
- Первый подходящий паттерн выбирается
- Поддерживает полное совпадение (`re.fullmatch`)

**Пример:**

```python
dispatcher.register_handler(
    r"process_\d+",
    handler,
    strategy=DispatchStrategy.PATTERN_MATCH
)
# Обработает: process_1, process_123, process_999
```

### 3. FALLBACK_MATCH (Fallback стратегия)

**Когда использовать:** Когда нужно иметь несколько обработчиков для одного ключа с разной эффективностью.

**Особенности:**
- Разрешает несколько обработчиков с одним ключом
- Выбирает обработчик с наивысшей эффективностью
- Автоматическая сортировка по эффективности

**Пример:**

```python
# Низкоэффективный обработчик (fallback)
dispatcher.register_handler(
    "process",
    slow_handler,
    strategy=DispatchStrategy.FALLBACK_MATCH,
    efficiency=1
)

# Высокоэффективный обработчик (основной)
dispatcher.register_handler(
    "process",
    fast_handler,
    strategy=DispatchStrategy.FALLBACK_MATCH,
    efficiency=10
)

# Будет использован fast_handler
```

### 4. CHAIN_MATCH (Сценарии)

**Когда использовать:** Когда нужно выполнить последовательность обработчиков.

**Особенности:**
- Обработчики выполняются последовательно по stage
- Результат предыдущего этапа передается следующему
- Поддержка остановки при ошибке (`stop_on_error`)

**Пример:**

```python
dispatcher.create_scenario("pipeline")

def step1(data):
    return {"step1": "done", "data": data}

def step2(data):
    return {"step2": "done", "value": data.get("value", 0) + 1}

dispatcher.add_handler_to_scenario("pipeline", "step1", step1, stage=1)
dispatcher.add_handler_to_scenario("pipeline", "step2", step2, stage=2)

# Результат step1 передается в step2
```

## API Reference

### Dispatcher

#### Инициализация

```python
Dispatcher(
    name: str,
    default_strategy: DispatchStrategy = DispatchStrategy.EXACT_MATCH,
    managers: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    config_manager: Optional[Any] = None,
    # Обратная совместимость
    logger_manager: Optional[Any] = None,
    error_manager: Optional[Any] = None,
    statistics_manager: Optional[Any] = None,
    enable_logging: bool = True,
    enable_error_tracking: bool = True,
    enable_statistics: bool = True
)
```

#### Основные методы

##### Регистрация обработчиков

```python
register_handler(
    key: str,
    handler: Callable,
    expects_full_message: bool = False,
    metadata: Dict[str, Any] = None,
    efficiency: int = 0,
    tags: List[str] = None,
    strategy: Optional[DispatchStrategy] = None
) -> bool
```

Регистрирует обработчик в указанной стратегии (или в стратегии по умолчанию).

##### Диспетчеризация

```python
dispatch(
    message: Dict[str, Any],
    key_field: str = "command",
    data_field: str = "data"
) -> Any
```

Диспетчеризует сообщение к соответствующему обработчику.

**Логика выбора стратегии:**
1. Если в сообщении есть поле `"scenario"` - выполняется сценарий
2. Если ключ найден в сценариях - выполняется сценарий
3. Если в сообщении есть поле `"strategy"` - используется указанная стратегия
4. Иначе - поиск по всем стратегиям (EXACT → FALLBACK → PATTERN → CHAIN)

##### Работа со сценариями

```python
create_scenario(name: str, description: str = "", metadata: Dict[str, Any] = None) -> bool
delete_scenario(name: str) -> bool
get_scenario_info(name: str) -> Optional[Dict[str, Any]]
get_all_scenarios() -> List[Dict[str, Any]]
add_handler_to_scenario(scenario_name: str, handler_key: str, handler: Callable, stage: int, ...) -> bool
remove_handler_from_scenario(scenario_name: str, handler_key: str) -> bool
reorder_handler_in_scenario(scenario_name: str, handler_key: str, new_stage: int) -> bool
dispatch_scenario(scenario_name: str, message: Dict[str, Any], data_field: str = "data", stop_on_error: bool = True) -> Dict[str, Any]
```

##### Получение информации

```python
get_handler_info(key: str) -> Optional[Dict]
get_all_handlers() -> List[Dict]
get_handlers_by_tag(tag: str) -> List[Dict]
```

### ScenarioBuilder

Удобный интерфейс для работы со сценариями:

```python
builder = ScenarioBuilder(dispatcher)

builder.create(name: str, description: str = "", metadata: Dict[str, Any] = None) -> bool
builder.delete(name: str) -> bool
builder.add_handler(scenario_name: str, handler_key: str, handler: Callable, stage: int, ...) -> bool
builder.remove_handler(scenario_name: str, handler_key: str) -> bool
builder.reorder(scenario_name: str, handler_key: str, new_stage: int) -> bool
builder.update_metadata(scenario_name: str, metadata: Dict[str, Any]) -> bool
builder.update_description(scenario_name: str, description: str) -> bool
builder.get_info(scenario_name: str) -> Optional[Dict[str, Any]]
builder.list_all() -> List[Dict[str, Any]]
builder.exists(scenario_name: str) -> bool
```

## Примеры использования

### Пример 1: Простая маршрутизация команд

```python
from src.Modules.Dispatch_module import Dispatcher

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
from src.Modules.Dispatch_module import Dispatcher, DispatchStrategy

dispatcher = Dispatcher("image_processor")

# Обработка изображений по паттерну
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

### Пример 3: Fallback обработчики

```python
from src.Modules.Dispatch_module import Dispatcher, DispatchStrategy

dispatcher = Dispatcher("fallback_processor")

# Медленный универсальный обработчик
def slow_processor(data):
    # Медленная обработка
    return {"result": "slow", "data": data}

# Быстрый специализированный обработчик
def fast_processor(data):
    # Быстрая обработка для определенных случаев
    return {"result": "fast", "data": data}

dispatcher.register_handler(
    "process",
    slow_processor,
    strategy=DispatchStrategy.FALLBACK_MATCH,
    efficiency=1
)

dispatcher.register_handler(
    "process",
    fast_processor,
    strategy=DispatchStrategy.FALLBACK_MATCH,
    efficiency=10
)

# Будет использован fast_processor
result = dispatcher.dispatch({
    "command": "process",
    "strategy": "fallback",
    "data": {}
})
```

### Пример 4: Сложный сценарий обработки

```python
from src.Modules.Dispatch_module import Dispatcher

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
    objects = ["bottle", "cap"]  # Пример
    return {"detected": True, "objects": objects, "data": {"objects": objects}}

# Этап 3: Классификация дефектов
def classify_defects(data):
    objects = data.get("objects", [])
    defects = {"bottle": "ok", "cap": "defect"}  # Пример
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
#     "stages": [
#         {"stage": 1, "handler_key": "preprocess", "status": "success", ...},
#         {"stage": 2, "handler_key": "detect", "status": "success", ...},
#         {"stage": 3, "handler_key": "classify", "status": "success", ...}
#     ],
#     "final_result": {"classified": True, "defects": {...}}
# }
```

### Пример 5: Использование метаданных и тегов

```python
from src.Modules.Dispatch_module import Dispatcher

dispatcher = Dispatcher("tagged_dispatcher")

# Регистрация обработчиков с тегами
dispatcher.register_handler(
    "process_image",
    image_handler,
    tags=["vision", "image"],
    metadata={"category": "vision", "version": "1.0"}
)

dispatcher.register_handler(
    "process_audio",
    audio_handler,
    tags=["audio", "sound"],
    metadata={"category": "audio", "version": "1.0"}
)

# Поиск по тегам
vision_handlers = dispatcher.get_handlers_by_tag("vision")
print(vision_handlers)  # [{"key": "process_image", ...}]

# Получение информации
info = dispatcher.get_handler_info("process_image")
print(info["metadata"])  # {"category": "vision", "version": "1.0"}
```

## Интеграция с ObservableMixin

`Dispatcher` наследуется от `ObservableMixin`, что позволяет использовать:

- **Логирование** - автоматическое логирование операций
- **Статистика** - сбор метрик производительности
- **Обработка ошибок** - отслеживание и обработка ошибок

```python
from src.Modules.Logger_module import LoggerManager

logger_manager = LoggerManager("dispatcher_logger")
dispatcher = Dispatcher(
    "my_dispatcher",
    logger_manager=logger_manager,
    enable_logging=True
)

# Все операции будут логироваться автоматически
dispatcher.register_handler("test", handler)
dispatcher.dispatch({"command": "test", "data": {}})
```

## Обработка ошибок

Диспетчер автоматически обрабатывает ошибки:

```python
# Если обработчик не найден
result = dispatcher.dispatch({"command": "unknown", "data": {}})
# {"status": "error", "reason": "No handler for key 'unknown'"}

# Если обработчик выбрасывает исключение
def failing_handler(data):
    raise ValueError("Error in handler")

dispatcher.register_handler("fail", failing_handler)
result = dispatcher.dispatch({"command": "fail", "data": {}})
# {"status": "error", "reason": "Dispatch failed: Error in handler"}
```

## Производительность

- **EXACT_MATCH**: O(1) - самый быстрый
- **FALLBACK_MATCH**: O(1) - быстрый поиск
- **PATTERN_MATCH**: O(n) где n - количество паттернов
- **CHAIN_MATCH**: O(m) где m - количество этапов в сценарии

Рекомендации:
- Используйте `EXACT_MATCH` для максимальной производительности
- Используйте `PATTERN_MATCH` только когда необходимо
- Группируйте обработчики по тегам для удобства управления

## Тестирование

Все тесты находятся в `tests/Test_Dispatch_module/`:

```bash
# Запуск всех тестов
pytest tests/Test_Dispatch_module/ -v

# Запуск конкретного теста
pytest tests/Test_Dispatch_module/test_dispatch_handler.py::TestDispatcherDispatching -v
```

## Обратная совместимость

Модуль поддерживает обратную совместимость через файл `dispatch_handler.py`:

```python
# Старый способ (устаревший, но работает)
from src.Modules.Dispatch_module.dispatch_handler import Dispatcher

# Новый способ (рекомендуется)
from src.Modules.Dispatch_module import Dispatcher
```

## Известные ограничения

1. **CHAIN_MATCH стратегия**: Обработчики не могут быть зарегистрированы напрямую через `register_handler`, только через сценарии
2. **PATTERN_MATCH**: Использует `re.fullmatch`, что требует полного совпадения паттерна
3. **FALLBACK_MATCH**: При обновлении эффективности обновляются все обработчики с одним ключом

## Дополнительные ресурсы

- [OBSERVABLE_USAGE.md](OBSERVABLE_USAGE.md) - Использование ObservableMixin
- Тесты в `tests/Test_Dispatch_module/` - Примеры использования

## Лицензия

Часть проекта Inspector_bottle_V2.

