# Архитектура DispatchModule

## Обзор

DispatchModule предоставляет гибкую систему маршрутизации и обработки сообщений с поддержкой различных стратегий диспетчеризации.

## Архитектурные компоненты

### Типы данных

**Расположение:** `types/types.py`

- **DispatchStrategy** (Enum) - стратегии диспетчеризации
- **HandlerInfo** (dataclass) - информация об обработчике
- **Scenario** (dataclass) - сценарий выполнения

### Основные классы

**Расположение:** `core/`

- **BaseDispatcher** - базовый класс диспетчера
- **Dispatcher** - универсальный диспетчер с поддержкой всех стратегий

### Стратегии

**Расположение:** `strategies/`

- **BaseStrategy** - базовый класс для стратегий
- **ExactMatchStrategy** - точное совпадение
- **PatternMatchStrategy** - паттерн-матчинг
- **FallbackMatchStrategy** - fallback стратегия
- **ChainMatchStrategy** - цепочки выполнения

### Построители

**Расположение:** `builders/`

- **ScenarioBuilder** - построитель сценариев

## Архитектурная диаграмма

```
Dispatcher
├── ObservableMixin (логирование, статистика, ошибки)
├── BaseDispatcher (базовая функциональность)
├── Strategies (4 стратегии)
│   ├── ExactMatchStrategy
│   ├── PatternMatchStrategy
│   ├── FallbackMatchStrategy
│   └── ChainMatchStrategy
└── Scenarios (хранилище сценариев)
```

## Поток диспетчеризации

### 1. Регистрация обработчика

```
register_handler() 
  → Выбор стратегии
  → Стратегия.register_handler()
  → Сохранение в хранилище стратегии
```

### 2. Диспетчеризация сообщения

```
dispatch(message)
  → Извлечение ключа из сообщения
  → Определение стратегии (из сообщения или по умолчанию)
  → Поиск обработчика через стратегию
  → Выполнение обработчика
  → Возврат результата
```

### 3. Выполнение сценария

```
dispatch_scenario(scenario_name, message)
  → Получение сценария
  → Последовательное выполнение обработчиков по stage
  → Передача результата между этапами
  → Возврат результатов всех этапов
```

## Хранилища обработчиков

Каждая стратегия использует свой тип хранилища:

- **EXACT_MATCH**: `Dict[str, HandlerInfo]` - O(1) поиск
- **PATTERN_MATCH**: `List[HandlerInfo]` - O(n) поиск по паттернам
- **FALLBACK_MATCH**: `Dict[str, List[HandlerInfo]]` - O(1) поиск, сортировка по эффективности
- **CHAIN_MATCH**: `Dict[str, Scenario]` - отдельное хранилище сценариев

## Интеграция с ObservableMixin

Dispatcher наследуется от ObservableMixin, что обеспечивает:

- **Логирование** - автоматическое логирование операций через `_log_*` методы
- **Статистика** - сбор метрик через `_record_metric` и `_record_timing`
- **Обработка ошибок** - отслеживание ошибок через `_track_error`

## Расширяемость

### Создание кастомной стратегии

```python
from ..strategies.base_strategy import BaseStrategy
from ..types.types import HandlerInfo

class CustomStrategy(BaseStrategy):
    def register_handler(self, key, handler, ..., handlers_storage):
        # Реализация регистрации
        pass
    
    def find_handler(self, key, handlers_storage):
        # Реализация поиска
        pass
    
    def get_all_handlers(self, handlers_storage):
        # Реализация получения всех обработчиков
        pass
    
    def get_handlers_by_tag(self, tag, handlers_storage):
        # Реализация поиска по тегам
        pass
```

### Использование интерфейсов

```python
from ..interfaces import IDispatcher

class CustomDispatcher(IDispatcher):
    # Реализация интерфейса
    pass
```

## Производительность

### Сложность операций

- **EXACT_MATCH**: O(1) - самый быстрый
- **FALLBACK_MATCH**: O(1) - быстрый поиск
- **PATTERN_MATCH**: O(n) где n - количество паттернов
- **CHAIN_MATCH**: O(m) где m - количество этапов в сценарии

### Рекомендации

1. Используйте EXACT_MATCH для максимальной производительности
2. Используйте PATTERN_MATCH только когда необходимо
3. Группируйте обработчики по тегам для удобства управления
4. Используйте метаданные для хранения дополнительной информации

## Потоки данных

### Отправка сообщения

```
Message → Dispatcher.dispatch()
  → Извлечение ключа
  → Выбор стратегии
  → Поиск обработчика
  → Выполнение обработчика
  → Результат
```

### Выполнение сценария

```
Message → Dispatcher.dispatch_scenario()
  → Получение сценария
  → Этап 1 → Результат 1
  → Этап 2 (Результат 1) → Результат 2
  → Этап 3 (Результат 2) → Финальный результат
```

## Безопасность

- Валидация паттернов в PatternMatchStrategy
- Проверка существования обработчиков перед выполнением
- Обработка ошибок на всех уровнях
- Логирование всех операций через ObservableMixin

## Тестируемость

Модуль разработан с учетом тестируемости:

- Разделение на стратегии позволяет тестировать каждую отдельно
- Интерфейсы позволяют создавать моки для тестирования
- ObservableMixin можно отключить для unit-тестов

## Дополнительные ресурсы

- [USAGE_GUIDE.md](USAGE_GUIDE.md) - Руководство по использованию
- [STRATEGIES_GUIDE.md](STRATEGIES_GUIDE.md) - Детальное описание стратегий
- [SCENARIOS_GUIDE.md](SCENARIOS_GUIDE.md) - Руководство по сценариям
- [API_REFERENCE.md](API_REFERENCE.md) - Справочник API

