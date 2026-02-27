# Base Manager Module - Основа для всех менеджеров

## Описание

Base Manager Module предоставляет базовые классы и миксины для всех менеджеров системы. Это фундамент, на котором строятся все специализированные менеджеры (Process, Worker, Logger, Router, Command, Config и т.д.).

## Роль в архитектуре

Base Manager Module является **основой** для всех менеджеров (органов в аналогии с организмом):
- Все менеджеры наследуются от `BaseManager`
- Все адаптеры наследуются от `BaseAdapter`
- Миксины добавляют наблюдаемость и расширения

## Структура модуля

Модуль следует стандарту структуры:

```
base_manager/
├── __init__.py              # Публичный API модуля
├── interfaces.py            # Интерфейсы модуля
├── core/                    # Основные классы
│   ├── __init__.py
│   └── base_manager.py      # BaseManager (абстрактный класс)
├── adapters/                # Адаптеры
│   ├── __init__.py
│   └── base_adapter.py      # BaseAdapter (базовый класс)
├── mixins/                  # Миксины
│   ├── __init__.py
│   └── observable_mixin.py  # ObservableMixin (объединяет ObservableMixin и ManagerExtensionMixin)
├── types/                   # Типы, константы
│   └── __init__.py
├── utils/                   # Утилиты
│   ├── __init__.py
│   └── name_utils.py        # Утилиты для работы с именами
├── docs/                    # Документация
├── README.md
└── tests/
    └── test_base_manager.py
```

## Публичный API

### Импорт

```python
from multiprocess_framework.refactored.modules.base_manager import (
    BaseManager,
    BaseAdapter,
    ObservableMixin,  # Объединяет ObservableMixin и ManagerExtensionMixin
)
```

### BaseManager

Базовый абстрактный класс для всех менеджеров:

```python
class MyManager(BaseManager):
    def __init__(self, name):
        super().__init__(name)
    
    def initialize(self) -> bool:
        # Инициализация менеджера
        self.is_initialized = True
        return True
    
    def shutdown(self) -> bool:
        # Завершение работы менеджера
        self.is_initialized = False
        return True

# Использование
manager = MyManager("my_manager")
manager.initialize()
# ... работа ...
manager.shutdown()
```

### BaseAdapter

Базовый класс для адаптеров:

```python
class MyAdapter(BaseAdapter):
    def setup(self) -> bool:
        # Настройка адаптера
        self._initialized = True
        return True

# Использование
adapter = MyAdapter(manager, process)
manager.attach_adapter(adapter, name="my_adapter")
adapter.setup()
```

### ObservableMixin

Универсальный миксин для добавления наблюдаемости и расширений (объединяет ObservableMixin и ManagerExtensionMixin):

**Вариант 1: С приватными методами (как ObservableMixin):**

```python
class MyManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None):
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(
            self,
            managers={'logger': logger},
            config={'logger': True},
            auto_proxy=False  # Без автоматических прокси-методов
        )
    
    def do_something(self):
        self._log_info("Выполняю операцию")  # Приватный метод
        self._record_metric("operations.count")
```

**Вариант 2: С автоматическими прокси-методами (как ManagerExtensionMixin):**

```python
class MyManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None, stats=None):
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(
            self,
            managers={
                'logger': logger,
                'stats': stats
            },
            config={'logger': True, 'stats': True},
            auto_proxy=True  # Автоматически создаст log_info(), record_metric() и т.д.
        )
    
    def process(self):
        self.log_info("Обработка данных")  # Публичный метод (автоматически создан)
        self.record_metric("operations.count")  # Публичный метод (автоматически создан)
        
        # Приватные методы тоже работают
        self._log_info("Тоже работает")
        self._record_metric("operations.count")
```

**Преимущества объединенного миксина:**
- ✅ Один миксин вместо двух - нет дублирования
- ✅ Гибкость: приватные методы или автоматические прокси-методы
- ✅ Производительность: кэширование методов
- ✅ Обратная совместимость: поддерживает оба стиля использования

## Использование

### Создание менеджера

```python
from multiprocess_framework.refactored.modules.base_manager import BaseManager

class WorkerManager(BaseManager):
    def initialize(self) -> bool:
        # Инициализация воркеров
        self.is_initialized = True
        return True
    
    def shutdown(self) -> bool:
        # Остановка воркеров
        self.is_initialized = False
        return True
```

### Подключение адаптеров

```python
from multiprocess_framework.refactored.modules.base_manager import BaseAdapter

class ProcessAdapter(BaseAdapter):
    def setup(self) -> bool:
        # Интеграция с процессом
        self._initialized = True
        return True

# Подключение
manager = WorkerManager("worker")
adapter = ProcessAdapter(manager, process)
manager.attach_adapter(adapter, name="process")

# Доступ к адаптеру
process_adapter = manager.get_adapter("process")
# Или через magic-атрибут
process_adapter = manager.process_adapter
```

### Использование миксинов

```python
from multiprocess_framework.refactored.modules.base_manager import (
    BaseManager, ObservableMixin
)

class LoggerManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None):
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(
            self,
            managers={'logger': logger},
            config={'logger': True}
        )
    
    def initialize(self) -> bool:
        self._log_info("Инициализация LoggerManager")
        self.is_initialized = True
        return True
    
    def log_message(self, message: str):
        self._log_info(f"Log: {message}")
```

## Принципы использования

1. **Все менеджеры наследуются от BaseManager** - единый интерфейс
2. **Адаптеры подключаются через attach_adapter()** - композиция вместо наследования
3. **Миксины добавляют функциональность** - логирование, статистика, расширения
4. **Единственная ответственность** - менеджер делает основную работу, адаптер расширяет

## Структура компонентов

### Публичные компоненты (экспортируются из __init__.py)

- **BaseManager** (`core/base_manager.py`) - базовый класс менеджеров
- **BaseAdapter** (`adapters/base_adapter.py`) - базовый класс адаптеров
- **ObservableMixin** (`mixins/observable_mixin.py`) - миксин для наблюдаемости
- **ManagerExtensionMixin** (`mixins/extension_mixin.py`) - миксин для расширений

### Внутренние компоненты (не экспортируются)

- **utils/name_utils.py** - утилиты для работы с именами адаптеров

## Тесты

Тесты находятся в `tests/test_base_manager.py` и покрывают:
- Создание и жизненный цикл менеджеров
- Подключение и управление адаптерами
- События и статистика
- Magic-доступ к адаптерам

