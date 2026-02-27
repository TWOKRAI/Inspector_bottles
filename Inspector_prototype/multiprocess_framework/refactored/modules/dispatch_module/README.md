# DispatchModule (Refactored)

Модуль диспетчеризации сообщений с поддержкой различных стратегий маршрутизации.

## Описание

DispatchModule предоставляет гибкую систему маршрутизации и обработки сообщений с поддержкой различных стратегий диспетчеризации. Модуль позволяет регистрировать обработчики сообщений и автоматически направлять входящие сообщения к соответствующим обработчикам.

## Архитектура

```
dispatch_module/
├── __init__.py              # Экспорт основных классов
├── interfaces.py             # Интерфейсы модуля
├── types/                    # Типы данных
│   └── types.py             # DispatchStrategy, HandlerInfo, Scenario
├── core/                     # Основные классы
│   ├── base_dispatcher.py   # Базовый класс диспетчера
│   └── dispatcher.py        # Универсальный диспетчер
├── strategies/              # Стратегии диспетчеризации
│   ├── base_strategy.py     # Базовый класс стратегии
│   ├── exact_match.py       # Точное совпадение
│   ├── pattern_match.py     # Паттерн-матчинг
│   ├── fallback_match.py    # Fallback стратегия
│   └── chain_match.py       # Цепочки (сценарии)
├── builders/                # Построители
│   └── scenario_builder.py  # Построитель сценариев
├── docs/                    # Документация
└── tests/                   # Тесты
```

## Основные возможности

- ✅ **Множественные стратегии диспетчеризации** - поддержка 4 различных стратегий одновременно
- ✅ **Точное совпадение** - быстрая маршрутизация по точному ключу
- ✅ **Паттерн-матчинг** - гибкая маршрутизация по регулярным выражениям
- ✅ **Fallback стратегия** - выбор обработчика по эффективности
- ✅ **Сценарии (цепочки)** - последовательное выполнение обработчиков
- ✅ **Метаданные и теги** - организация и группировка обработчиков
- ✅ **Интеграция с ObservableMixin** - логирование, статистика, обработка ошибок

## Быстрый старт

### Базовое использование

```python
from multiprocess_framework.refactored.modules.dispatch_module import Dispatcher, DispatchStrategy

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
from multiprocess_framework.refactored.modules.dispatch_module import Dispatcher, DispatchStrategy

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

# Использование стратегии из сообщения
message = {
    "command": "pattern_123",
    "strategy": "pattern",
    "data": {}
}
result = dispatcher.dispatch(message)
```

## Стратегии диспетчеризации

### EXACT_MATCH
Точное совпадение ключей (самый быстрый, O(1)).

### PATTERN_MATCH
Сопоставление по регулярным выражениям.

### FALLBACK_MATCH
Fallback с приоритетом эффективности - позволяет несколько обработчиков с одним ключом.

### CHAIN_MATCH
Цепочки выполнения обработчиков (сценарии) - последовательное выполнение.

## Интеграция с ObservableMixin

Dispatcher наследуется от ObservableMixin, что позволяет использовать:
- **Логирование** - автоматическое логирование операций
- **Статистика** - сбор метрик производительности
- **Обработка ошибок** - отслеживание и обработка ошибок

```python
from multiprocess_framework.modules.Logger_module import LoggerManager

logger_manager = LoggerManager("dispatcher_logger")
dispatcher = Dispatcher(
    "my_dispatcher",
    managers={'logger': logger_manager},
    config={'logger': True}
)

# Все операции будут логироваться автоматически
dispatcher.register_handler("test", handler)
dispatcher.dispatch({"command": "test", "data": {}})
```

## Документация

См. `docs/` для детальной документации:
- `docs/USAGE_GUIDE.md` - Подробное руководство по использованию с примерами
- `docs/ARCHITECTURE.md` - Архитектура модуля
- `docs/STRATEGIES_GUIDE.md` - Руководство по стратегиям диспетчеризации
- `docs/SCENARIOS_GUIDE.md` - Руководство по работе со сценариями
- `docs/API_REFERENCE.md` - Справочник API

## Тесты

Тесты находятся в `tests/`:
- `test_types.py` - Тесты для типов данных (DispatchStrategy, HandlerInfo, Scenario)
- `test_dispatcher.py` - Тесты для Dispatcher
- `test_strategies.py` - Тесты для всех стратегий
- `test_scenario_builder.py` - Тесты для ScenarioBuilder

Запуск тестов:
```bash
python -m pytest tests/ -v
```

## Структура модуля

```
dispatch_module/
├── __init__.py              # Экспорт основных классов
├── README.md                # Основная документация
├── interfaces.py            # Интерфейсы модуля
├── types/                   # Типы данных
│   └── types.py            # DispatchStrategy, HandlerInfo, Scenario
├── core/                    # Основные классы
│   ├── base_dispatcher.py  # Базовый класс диспетчера
│   └── dispatcher.py       # Универсальный диспетчер
├── strategies/             # Стратегии диспетчеризации
│   ├── base_strategy.py    # Базовый класс стратегии
│   ├── exact_match.py      # Точное совпадение
│   ├── pattern_match.py    # Паттерн-матчинг
│   ├── fallback_match.py   # Fallback стратегия
│   └── chain_match.py      # Цепочки (сценарии)
├── builders/               # Построители
│   └── scenario_builder.py # Построитель сценариев
├── docs/                   # Документация
│   ├── README.md          # Навигация по документации
│   ├── USAGE_GUIDE.md      # Руководство по использованию
│   ├── ARCHITECTURE.md     # Архитектура модуля
│   ├── STRATEGIES_GUIDE.md # Руководство по стратегиям
│   ├── SCENARIOS_GUIDE.md  # Руководство по сценариям
│   └── API_REFERENCE.md    # Справочник API
└── tests/                  # Тесты
    ├── test_types.py       # Тесты типов данных
    ├── test_dispatcher.py  # Тесты Dispatcher
    ├── test_strategies.py  # Тесты стратегий
    └── test_scenario_builder.py # Тесты ScenarioBuilder
```

