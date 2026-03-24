# dispatch_module

Маршрутизация входящих сообщений к обработчикам внутри одного процесса. `Dispatcher` — единственный публичный класс, через который worker регистрирует обработчики и вызывает `dispatch()` на каждом входящем сообщении.

---

## Структура модуля

```
dispatch_module/
├── interfaces.py            ← ЕДИНСТВЕННЫЙ публичный контракт (IDispatcher)
├── __init__.py              ← Публичный API (Dispatcher, DispatchStrategy, ScenarioBuilder, ...)
│
├── core/
│   ├── dispatcher.py        ← Фасад (BaseManager + ObservableMixin) — основной класс
│   └── base_dispatcher.py   ← Абстрактный базовый диспетчер (без ObservableMixin)
│
├── strategies/
│   ├── base_strategy.py     ← Абстрактный BaseStrategy
│   ├── exact_match.py       ← O(1) lookup по точному ключу
│   ├── pattern_match.py     ← Регулярные выражения
│   ├── fallback_match.py    ← Несколько обработчиков → выбор по efficiency
│   └── chain_match.py       ← Сценарии (цепочки)
│
├── builders/
│   └── scenario_builder.py  ← ScenarioBuilder — fluent API для сценариев
│
├── types/
│   └── types.py             ← DispatchStrategy, HandlerInfo, Scenario
│
└── tests/
    ├── test_dispatcher.py
    ├── test_strategies.py
    ├── test_scenario_builder.py
    └── test_types.py
```

---

## Как работает маршрутизация

```
dispatch(message) → key = message[key_field]
    │
    ├─ key == msg["scenario"]?  → dispatch_scenario()
    ├─ key in _scenarios?       → dispatch_scenario()
    ├─ msg["strategy"] задан?   → ищем только в указанной стратегии
    └─ иначе: обход всех стратегий по приоритету:
            1. EXACT_MATCH   (O(1), самый быстрый)
            2. FALLBACK_MATCH
            3. PATTERN_MATCH (regex)
            4. CHAIN_MATCH   (сценарии)
```

---

## Быстрый старт

```python
from multiprocess_framework.modules.dispatch_module import Dispatcher, DispatchStrategy

dispatcher = Dispatcher("my_dispatcher")
dispatcher.initialize()

# Регистрация обработчика (EXACT_MATCH по умолчанию)
dispatcher.register_handler("process", lambda data: {"result": data.get("value", 0) * 2})

# Диспетчеризация
result = dispatcher.dispatch({"command": "process", "data": {"value": 5}})
# → {"result": 10}

dispatcher.shutdown()
```

---

## API Dispatcher

### Жизненный цикл

| Метод | Описание |
|-------|----------|
| `initialize()` | Инициализация, `is_initialized = True`. Вернуть `True` при успехе. |
| `shutdown()` | Очистить все обработчики, сценарии и стратегии. |

### Регистрация обработчиков

| Метод | Описание |
|-------|----------|
| `register_handler(key, handler, ...)` | Зарегистрировать обработчик. По умолчанию `EXACT_MATCH`. |
| `overwrite_handler(key, handler, ...)` | Принудительная перезапись во всех стратегиях. |

**Параметры `register_handler`:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `key` | `str` | Ключ для поиска (команда, паттерн и т.д.) |
| `handler` | `Callable` | Функция `fn(data) -> Any` или `fn(message) -> Any` |
| `expects_full_message` | `bool` | Если `True` — handler получает всё сообщение, иначе только `data` поле |
| `efficiency` | `int` | Приоритет для `FALLBACK_MATCH` (выше = вызывается первым) |
| `tags` | `List[str]` | Теги для группировки (`get_handlers_by_tag`) |
| `strategy` | `DispatchStrategy` | Стратегия для регистрации (`None` → `default_strategy`) |

### Диспетчеризация

| Метод | Описание |
|-------|----------|
| `dispatch(message, key_field, data_field)` | Найти и вызвать обработчик. Вернуть результат или `{"status": "error", ...}`. |
| `dispatch_scenario(name, message, data_field, stop_on_error)` | Выполнить цепочку напрямую. |

**Разрешение стратегии** (по порядку):
1. `msg["scenario"]` задан → прямой вызов сценария
2. `key` совпадает с именем сценария → вызов сценария
3. `msg["strategy"]` задан → ищем только в указанной стратегии
4. Иначе: EXACT → FALLBACK → PATTERN → CHAIN

### Запросы обработчиков

| Метод | Описание |
|-------|----------|
| `get_handler_info(key)` | Информация о конкретном обработчике или `None`. |
| `get_all_handlers()` | Список всех обработчиков из всех стратегий. |
| `get_handlers_by_tag(tag)` | Обработчики по тегу. |

### Обновление обработчиков

Все методы работают с `default_strategy`.

| Метод | Описание |
|-------|----------|
| `update_handler_metadata(key, metadata)` | Заменить метаданные. |
| `update_handler_efficiency(key, efficiency)` | Изменить приоритет (для FALLBACK). |
| `update_handler_tags(key, tags)` | Заменить теги. |
| `update_handler_function(key, handler)` | Заменить функцию. |
| `update_expects_full_message(key, flag)` | Изменить режим передачи данных. |

---

## Стратегии

### EXACT_MATCH (по умолчанию)

```python
dispatcher.register_handler("set_fps", lambda data: set_fps(data["fps"]))
result = dispatcher.dispatch({"command": "set_fps", "data": {"fps": 30}})
```

### PATTERN_MATCH

```python
dispatcher.register_handler(
    r"process_\d+",          # Регулярное выражение
    handle_numbered_process,
    strategy=DispatchStrategy.PATTERN_MATCH
)
result = dispatcher.dispatch({"command": "process_42", "data": {}})
```

### FALLBACK_MATCH

Несколько обработчиков с одним ключом. Вызывается тот, у которого `efficiency` выше.

```python
dispatcher.register_handler("process", fast_handler,   strategy=DispatchStrategy.FALLBACK_MATCH, efficiency=10)
dispatcher.register_handler("process", slow_handler,   strategy=DispatchStrategy.FALLBACK_MATCH, efficiency=1)

# Явное указание стратегии в сообщении
result = dispatcher.dispatch({"command": "process", "strategy": "fallback", "data": {}})
# → fast_handler вызывается (efficiency=10 > 1)
```

### CHAIN_MATCH (Сценарии)

```python
dispatcher.create_scenario("image_pipeline", "Обработка изображений")
dispatcher.add_handler_to_scenario("image_pipeline", "preprocess", preprocess_fn, stage=1)
dispatcher.add_handler_to_scenario("image_pipeline", "detect",     detect_fn,     stage=2)
dispatcher.add_handler_to_scenario("image_pipeline", "postprocess", postprocess_fn, stage=3)

result = dispatcher.dispatch({"command": "image_pipeline", "data": {"image": "frame.jpg"}})
# result["stages"] → список результатов каждого этапа
# result["final_result"] → результат последнего этапа
```

**Передача данных между этапами:** если этап вернул `dict` с полем `"data"` — следующий этап получит его значение, иначе — весь `dict`.

---

## Сценарии — полный API

| Метод | Описание |
|-------|----------|
| `create_scenario(name, description, metadata)` | Создать сценарий. `False` если уже существует. |
| `delete_scenario(name)` | Удалить. |
| `add_handler_to_scenario(scenario, key, fn, stage, ...)` | Добавить шаг. |
| `remove_handler_from_scenario(scenario, key)` | Удалить шаг. |
| `reorder_handler_in_scenario(scenario, key, new_stage)` | Изменить порядок. |
| `update_scenario_description(name, description)` | Обновить описание. |
| `update_scenario_metadata(name, metadata)` | Обновить метаданные. |
| `get_scenario_info(name)` | Информация о сценарии. |
| `get_all_scenarios()` | Список всех сценариев. |

### ScenarioBuilder — fluent API

```python
from multiprocess_framework.modules.dispatch_module import ScenarioBuilder

builder = ScenarioBuilder(dispatcher)
builder.create("pipeline", "Цепочка обработки")
builder.add_handler("pipeline", "step_1", handler_1, stage=1)
builder.add_handler("pipeline", "step_2", handler_2, stage=2)
builder.reorder("pipeline", "step_2", new_stage=1)   # Изменить порядок
builder.remove_handler("pipeline", "step_1")
```

---

## Интеграция с LoggerManager

`Dispatcher` наследует `BaseManager + ObservableMixin`. Подключение через конструктор:

```python
dispatcher = Dispatcher(
    "my_dispatcher",
    managers={"logger": logger_manager, "error": error_manager},
    config={"logger": True, "error": True}
)
```

После этого все `_log_info / _log_warning / _log_error` идут через `LoggerManager`.

**Текущее состояние интеграции:**
- `LoggerManager` — подключается через `ObservableMixin` ✅
- `ErrorManager` — подключается через `ObservableMixin` ✅
- `StatsManager` — метрики через `_record_metric` / `_record_timing` ✅

---

## Тесты

```bash
python -m pytest Inspector_prototype/multiprocess_framework/modules/dispatch_module/tests/ -v
```

Покрытие (49 тестов):
- Жизненный цикл: `initialize` / `shutdown`
- Стратегии: EXACT / PATTERN / FALLBACK / CHAIN — регистрация и поиск
- Диспетчеризация: точное совпадение, паттерн, fallback, полное сообщение
- Сценарии: создание, добавление шагов, выполнение, порядок этапов
- `ScenarioBuilder`: create / delete / add / remove / reorder / update
- Типы: `DispatchStrategy`, `HandlerInfo`, `Scenario`

---

## BaseDispatcher — lightweight вариант

`BaseDispatcher` — конкретный (не абстрактный) класс для случаев, когда полный `Dispatcher` избыточен: юнит-тесты, инструменты, простые внутренние маршрутизаторы. Поддерживает только `EXACT_MATCH`, без `ObservableMixin`.

```python
from multiprocess_framework.modules.dispatch_module import BaseDispatcher

d = BaseDispatcher("simple")
d.register_handler("ping", lambda data: {"pong": True})
result = d.dispatch({"command": "ping", "data": {}})
```

Для production-кода с логированием и мульти-стратегиями → используй `Dispatcher`.

---

## Roadmap / Что не хватает

| Задача | Приоритет | Этап |
|--------|-----------|------|
| Интеграция с `ProcessModule` (использование в worker_1.py) | Высокий | 3 |
| `correlation_id` для request-response паттерна | Средний | 5 |
