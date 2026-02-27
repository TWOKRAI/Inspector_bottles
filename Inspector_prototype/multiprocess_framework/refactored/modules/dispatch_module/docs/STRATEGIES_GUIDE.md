# Руководство по стратегиям диспетчеризации

## Обзор

DispatchModule поддерживает 4 стратегии диспетчеризации, каждая из которых оптимизирована для определенных сценариев использования.

## EXACT_MATCH - Точное совпадение

### Описание

Самая быстрая стратегия - точное совпадение ключей. Используется по умолчанию.

### Когда использовать

- Когда ключи известны заранее
- Когда нужна максимальная производительность
- Для простой маршрутизации команд

### Особенности

- Самый быстрый поиск (O(1))
- Уникальные ключи для каждого обработчика
- Используется по умолчанию

### Пример

```python
dispatcher = Dispatcher("exact_dispatcher")

def process_handler(data):
    return {"processed": True, "data": data}

dispatcher.register_handler("process", process_handler)

# Обработает только сообщения с command="process"
result = dispatcher.dispatch({"command": "process", "data": {}})
```

### Производительность

- Регистрация: O(1)
- Поиск: O(1)
- Хранилище: `Dict[str, HandlerInfo]`

## PATTERN_MATCH - Паттерн-матчинг

### Описание

Гибкая маршрутизация по регулярным выражениям. Позволяет обрабатывать группы команд с похожими именами.

### Когда использовать

- Когда нужно обрабатывать группы команд с похожими именами
- Когда ключи следуют определенному паттерну
- Для динамической маршрутизации

### Особенности

- Использует регулярные выражения
- Первый подходящий паттерн выбирается
- Поддерживает полное совпадение (`re.fullmatch`)

### Пример

```python
dispatcher = Dispatcher("pattern_dispatcher")

def process_handler(data):
    return {"processed": True}

dispatcher.register_handler(
    r"process_\d+",
    process_handler,
    strategy=DispatchStrategy.PATTERN_MATCH
)

# Обработает: process_1, process_123, process_999
result = dispatcher.dispatch({"command": "process_123", "data": {}})
```

### Производительность

- Регистрация: O(1) (с валидацией паттерна)
- Поиск: O(n) где n - количество паттернов
- Хранилище: `List[HandlerInfo]`

### Валидация паттернов

Паттерны валидируются при регистрации:

```python
# Валидный паттерн
dispatcher.register_handler(r"process_\d+", handler, strategy=DispatchStrategy.PATTERN_MATCH)

# Невалидный паттерн - вернет False
result = dispatcher.register_handler("[invalid", handler, strategy=DispatchStrategy.PATTERN_MATCH)
```

## FALLBACK_MATCH - Fallback стратегия

### Описание

Позволяет иметь несколько обработчиков для одного ключа с разной эффективностью. Выбирается обработчик с наивысшей эффективностью.

### Когда использовать

- Когда нужно иметь несколько обработчиков для одного ключа
- Когда нужен fallback механизм
- Для оптимизации производительности

### Особенности

- Разрешает несколько обработчиков с одним ключом
- Выбирает обработчик с наивысшей эффективностью
- Автоматическая сортировка по эффективности

### Пример

```python
dispatcher = Dispatcher("fallback_dispatcher")

# Низкоэффективный обработчик (fallback)
def slow_handler(data):
    # Медленная обработка
    return {"result": "slow"}

dispatcher.register_handler(
    "process",
    slow_handler,
    strategy=DispatchStrategy.FALLBACK_MATCH,
    efficiency=1
)

# Высокоэффективный обработчик (основной)
def fast_handler(data):
    # Быстрая обработка для определенных случаев
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

### Производительность

- Регистрация: O(1) + сортировка
- Поиск: O(1) (возвращается первый элемент после сортировки)
- Хранилище: `Dict[str, List[HandlerInfo]]`

### Управление эффективностью

```python
# Обновление эффективности всех обработчиков с ключом
dispatcher.update_handler_efficiency("process", 20)
```

## CHAIN_MATCH - Цепочки выполнения (сценарии)

### Описание

Позволяет создавать сценарии - цепочки обработчиков, которые выполняются последовательно.

### Когда использовать

- Когда нужно выполнить последовательность операций
- Для сложных пайплайнов обработки
- Когда результат одного этапа нужен для следующего

### Особенности

- Обработчики выполняются последовательно по stage
- Результат предыдущего этапа передается следующему
- Поддержка остановки при ошибке (`stop_on_error`)

### Пример

```python
dispatcher = Dispatcher("chain_dispatcher")

# Создание сценария
dispatcher.create_scenario("image_pipeline", "Обработка изображений")

# Этап 1: Предобработка
def preprocess(data):
    image = data.get("image")
    return {"preprocessed": True, "data": {"image": image}}

# Этап 2: Детекция объектов
def detect_objects(data):
    image = data.get("image")
    objects = ["bottle", "cap"]
    return {"detected": True, "data": {"objects": objects}}

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
```

### Производительность

- Регистрация: O(1) + сортировка по stage
- Поиск: O(m) где m - количество этапов в сценарии
- Хранилище: `Dict[str, Scenario]`

### Передача данных между этапами

Результат предыдущего этапа передается следующему:

```python
# Если результат содержит поле "data", оно используется
stage_result = {"data": {"processed": True}}
# Следующий этап получит {"processed": True}

# Если результат не содержит "data", используется весь результат
stage_result = {"processed": True}
# Следующий этап получит {"processed": True}
```

### Обработка ошибок

```python
# Остановка при ошибке (по умолчанию)
result = dispatcher.dispatch_scenario("scenario", message, stop_on_error=True)

# Продолжение при ошибке
result = dispatcher.dispatch_scenario("scenario", message, stop_on_error=False)
```

## Сравнение стратегий

| Стратегия | Скорость поиска | Уникальность ключей | Использование |
|-----------|----------------|---------------------|---------------|
| EXACT_MATCH | O(1) | Да | По умолчанию, максимальная производительность |
| PATTERN_MATCH | O(n) | Нет | Группы команд с паттернами |
| FALLBACK_MATCH | O(1) | Нет | Несколько обработчиков с fallback |
| CHAIN_MATCH | O(m) | Да (сценарии) | Последовательные операции |

## Выбор стратегии

### Рекомендации

1. **EXACT_MATCH** - используйте по умолчанию для максимальной производительности
2. **PATTERN_MATCH** - используйте только когда необходимо обрабатывать группы команд
3. **FALLBACK_MATCH** - используйте когда нужен fallback механизм
4. **CHAIN_MATCH** - используйте для сложных последовательных операций

### Комбинирование стратегий

Все стратегии могут использоваться одновременно:

```python
dispatcher = Dispatcher("multi_strategy")

# EXACT_MATCH
dispatcher.register_handler("exact_cmd", handler1)

# PATTERN_MATCH
dispatcher.register_handler(r"pattern_\d+", handler2, strategy=DispatchStrategy.PATTERN_MATCH)

# FALLBACK_MATCH
dispatcher.register_handler("fallback_cmd", handler3, strategy=DispatchStrategy.FALLBACK_MATCH)

# CHAIN_MATCH
dispatcher.create_scenario("chain_scenario", "Сценарий")
dispatcher.add_handler_to_scenario("chain_scenario", "step1", handler4, stage=1)
```

## Дополнительные ресурсы

- [USAGE_GUIDE.md](USAGE_GUIDE.md) - Руководство по использованию
- [ARCHITECTURE.md](ARCHITECTURE.md) - Архитектура модуля
- [SCENARIOS_GUIDE.md](SCENARIOS_GUIDE.md) - Руководство по сценариям
- [API_REFERENCE.md](API_REFERENCE.md) - Справочник API

