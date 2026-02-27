# Base Manager Module

Модуль базовых классов и миксинов для менеджеров системы. Предоставляет фундаментальные абстракции для создания менеджеров, адаптеров и добавления наблюдаемости к классам.

## Содержание

1. [Обзор модуля](#обзор-модуля)
2. [Архитектура и концепция](#архитектура-и-концепция)
3. [Компоненты](#компоненты)
   - [BaseManager](#basemanager)
   - [BaseAdapter](#baseadapter)
   - [ObservableMixin](#observablemixin)
4. [Взаимодействие компонентов](#взаимодействие-компонентов)
5. [Примеры использования](#примеры-использования)
6. [Руководство по выбору](#руководство-по-выбору)

---

## Обзор модуля

Модуль `Base_manager_module` предоставляет три основных компонента:

1. **BaseManager** - базовый абстрактный класс для всех менеджеров системы
2. **BaseAdapter** - базовый класс для адаптеров (инструментов менеджера)
3. **ObservableMixin** - миксин для добавления наблюдаемости (логирование, статистика, ошибки)

Эти компоненты работают вместе, обеспечивая единообразную архитектуру для всех менеджеров в системе.

---

## Архитектура и концепция

### Философия дизайна

**Метафора:**
- **Manager** (BaseManager) = человек с профессией (врач, полицейский) - основной класс с основной функциональностью
- **ObservableMixin** = телефон (дополнительный инструмент) - миксин для логирования/мониторинга
- **Adapter** (BaseAdapter) = инструмент (скальпель, микроскоп) - композиция, подключается к менеджеру

**Ключевые принципы:**
1. **Manager - главный класс** - вся основная функциональность в менеджере
2. **Adapter - инструмент** - подключается К менеджеру через `attach_adapter()`, добавляет только уникальную функциональность
3. **Нет дублирования** - адаптер не дублирует методы менеджера, только расширяет
4. **Композиция вместо наследования** - адаптер включается в менеджер, а не наследуется
5. **Гибкость** - у менеджера может быть несколько адаптеров разных типов

### Диаграмма архитектуры

```
┌─────────────────────────────────────────────────────────┐
│                    Base Manager Module                    │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌──────────────────────────────────────────────┐      │
│  │           BaseManager (основной класс)        │      │
│  │  - Основная функциональность                  │      │
│  │  - Управление адаптерами (attach_adapter)     │      │
│  │  - Magic-доступ через атрибуты                │      │
│  └────────────┬───────────────────┬──────────────┘      │
│               │                   │                      │
│               │ использует        │ владеет              │
│               │                   │                      │
│  ┌────────────▼────────┐  ┌──────▼─────────────────┐  │
│  │  ObservableMixin     │  │  BaseAdapter           │  │
│  │  (телефон)           │  │  (инструмент)          │  │
│  │  - Логирование       │  │  - Уникальная функц.   │  │
│  │  - Статистика        │  │  - Интеграция процесса │  │
│  │  - Мониторинг        │  │                        │  │
│  └──────────────────────┘  └────────────────────────┘  │
│                                                           │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Примеры:                                         │  │
│  │  CommandManager + CommandAdapter                 │  │
│  │  LoggerManager + LoggerAdapter                   │  │
│  │  RouterManager + RouterAdapter                   │  │
│  └──────────────────────────────────────────────────┘  │
│                                                           │
└─────────────────────────────────────────────────────────┘
```

### Принципы дизайна

- **Единообразие** - все менеджеры следуют одному интерфейсу
- **Разделение ответственности** - менеджер делает основную работу, адаптер только расширяет
- **Гибкость** - можно подключить несколько адаптеров к одному менеджеру
- **Простота** - минимум абстракций, максимум пользы
- **Нет дублирования** - адаптер не повторяет методы менеджера

---

## Компоненты

### BaseManager

Базовый абстрактный класс для всех менеджеров системы.

#### Назначение

Предоставляет унифицированный интерфейс для всех менеджеров:
- Стандартизированный жизненный цикл (initialize/shutdown)
- Единый способ получения статистики
- Система событий для взаимодействия
- **Управление адаптерами** - менеджер владеет адаптерами как инструментами

#### Ключевые особенности

- Абстрактные методы `initialize()` и `shutdown()` - обязательны для реализации
- Метод `get_stats()` - получение статистики менеджера (включает информацию об адаптерах)
- Система событий (`on_event`, `emit_event`) - для взаимодействия между компонентами
- **Управление адаптерами:**
  - `attach_adapter(adapter, name=None)` - подключить адаптер
    - **Рекомендуется указывать имя явно** для надежности
    - Если имя не указано, определяется автоматически (простая логика)
  - `get_adapter(name=None)` - получить адаптер
  - `has_adapter(name)` - проверить наличие адаптера
  - `list_adapters()` - список подключенных адаптеров
  - `detach_adapter(name)` - отключить адаптер
  - **Magic-доступ** - `manager.command_adapter` через `__getattr__()`
- Связь с процессом - менеджер может знать о родительском процессе

#### Пример использования

```python
from multiprocess_framework.modules.Base_manager_module import BaseManager

class MyManager(BaseManager):
    def __init__(self, manager_name: str, process=None):
        super().__init__(manager_name, process)
    
    def initialize(self) -> bool:
        """Инициализация менеджера."""
        # Логика инициализации
        self.is_initialized = True
        return True
    
    def shutdown(self) -> bool:
        """Корректное завершение работы."""
        # Логика завершения
        self.is_initialized = False
        return True

# Использование с адаптером
manager = MyManager("MyManager")
adapter = MyAdapter(manager, process=my_process)

# Рекомендуемый способ - явное указание имени
manager.attach_adapter(adapter, name="my")
adapter.setup()

# Или автоматическое определение (fallback)
# manager.attach_adapter(adapter)  # Имя определится автоматически

# Доступ к адаптеру
adapter = manager.get_adapter("my")
# Или через magic-атрибут
adapter = manager.my_adapter
```

#### API

**Основные методы:**
- `__init__(manager_name: str, process: Optional[Any] = None)` - инициализация
- `initialize() -> bool` - абстрактный метод инициализации
- `shutdown() -> bool` - абстрактный метод завершения
- `get_stats() -> Dict[str, Any]` - получение статистики (включая адаптеры)

**Управление адаптерами:**
- `attach_adapter(adapter: Any, name: Optional[str] = None) -> bool` - подключить адаптер
- `get_adapter(name: Optional[str] = None) -> Optional[Any]` - получить адаптер (фильтрует None)
- `has_adapter(name: str) -> bool` - проверить наличие адаптера
- `list_adapters() -> List[str]` - список имен адаптеров
- `detach_adapter(name: str) -> bool` - отключить адаптер
- `__getattr__(name: str)` - magic-доступ через атрибуты (`manager.command_adapter`)
  - **Безопасность:** проверяет что адаптер не None перед возвратом
  - **Обработка ошибок:** выбрасывает AttributeError с понятным сообщением если адаптер None

**События:**
- `on_event(event_type: str, callback: Callable)` - регистрация обработчика событий
- `emit_event(event_type: str, data: Dict[str, Any])` - генерация события

---

### BaseAdapter

Базовый абстрактный класс для всех адаптеров менеджеров.

#### Назначение

Адаптер - это **инструмент**, который подключается к менеджеру для расширения функциональности. Адаптер:
- **Не дублирует методы менеджера** - основная функциональность доступна через менеджер
- **Добавляет только уникальную функциональность** - интеграция с процессом, специализированные методы
- **Использует ObservableMixin менеджера** - для логирования, мониторинга, статистики

#### Ключевые особенности

- Абстрактный метод `setup()` - обязателен для реализации
- Связь с менеджером через `manager` атрибут
- Связь с процессом для доступа к ресурсам процесса
- **Автоматическое логирование** - `_log()` использует ObservableMixin менеджера, если доступен
- Приоритет логирования: менеджер (ObservableMixin) → процесс → fallback

#### Пример использования

```python
from multiprocess_framework.modules.Base_manager_module import BaseAdapter

class MyAdapter(BaseAdapter):
    def __init__(self, manager, process=None, logging_enabled=True):
        super().__init__(manager, process, adapter_name="MyAdapter", logging_enabled=logging_enabled)
    
    def setup(self) -> bool:
        """Настройка адаптера."""
        if not self.manager:
            self._log("error", "Manager is not set")
            return False
        
        self._initialized = True
        self._log("info", "MyAdapter initialized")  # Использует ObservableMixin менеджера
        return True
    
    def sensitive_operation(self):
        """Операция с отключенным логированием."""
        # Временно отключаем логирование
        self.enable_logging(False)
        try:
            # Конфиденциальная операция без логирования
            result = self._do_sensitive_work()
            return result
        finally:
            # Включаем обратно
            self.enable_logging(True)
    
    def special_integration_method(self):
        """
        Уникальная функциональность адаптера.
        Основные методы доступны через self.manager
        """
        # Используем менеджер для основной работы
        result = self.manager.main_method()
        
        # Добавляем интеграцию с процессом
        if self.process:
            # Специфичная логика интеграции
            pass
        
        return result
```

#### API

**Основные методы:**
- `__init__(manager: Any, process: Optional[Any] = None, adapter_name: str = None, logging_enabled: bool = True)` - инициализация
- `setup() -> bool` - абстрактный метод настройки
- `is_initialized() -> bool` - проверка инициализации
- `get_manager() -> Any` - получение менеджера
- `get_stats() -> Dict[str, Any]` - получение статистики

**Логирование:**
- `_log(level: str, message: str, context: str = None)` - логирование через ObservableMixin менеджера
- `enable_logging(enabled: bool = True)` - включить/выключить логирование
- `is_logging_enabled() -> bool` - проверить включено ли логирование

**Примечание:** Логирование использует приоритеты:
1. ObservableMixin менеджера через `_call_manager()` (предпочтительно)
2. Прямой доступ к методам ObservableMixin менеджера
3. LoggerManager процесса (обратная совместимость)
4. Fallback на print (если ничего не доступно)

---

### ObservableMixin

Универсальный миксин для добавления наблюдаемости к классам.

#### Назначение

Простой адаптер для связи классов с различными менеджерами (логирование, обработка ошибок, статистика) без усложнения основного функционала.

#### Ключевые особенности

- **Простота** - минимум кода, максимум пользы
- **Опциональность** - работает и без менеджеров
- **Безопасность** - ошибки в менеджерах не ломают основной код
- **Расширяемость** - легко добавлять новые менеджеры
- **Гибкость** - включение/выключение функций в реальном времени
- **Производительность** - кэширование методов менеджеров для оптимизации частых вызовов

#### Пример использования

```python
from multiprocess_framework.modules.Base_manager_module import ObservableMixin

class MyService(ObservableMixin):
    def __init__(self, logger=None, stats=None):
        managers = {}
        if logger:
            managers['logger'] = logger
        if stats:
            managers['statistics'] = stats
        
        ObservableMixin.__init__(
            self,
            managers=managers,
            config={'logger': True, 'statistics': True}
        )
    
    def process_data(self, data):
        self._log_info("Обработка данных")
        try:
            result = self._process(data)
            self._record_metric("operations.success")
            return result
        except Exception as e:
            self._track_error(e, {"operation": "process_data"})
            raise
```

#### Основные методы

**Логирование:**
- `_log_debug(message, **kwargs)`
- `_log_info(message, **kwargs)`
- `_log_warning(message, **kwargs)`
- `_log_error(message, **kwargs)`

**Статистика:**
- `_record_metric(metric_name, value=1, tags=None)`
- `_record_timing(metric_name, duration, tags=None)`

**Ошибки:**
- `_track_error(error, context=None)`

**Управление:**
- `enable(manager_name, enabled=True)` - включить/выключить менеджер
- `disable(manager_name)` - выключить менеджер
- `is_enabled(manager_name) -> bool` - проверить включен ли менеджер
- `context(manager_name, enabled=True)` - контекстный менеджер для временного изменения состояния
- `register_manager(name, manager, enabled=True)` - зарегистрировать новый менеджер
- `unregister_manager(name)` - удалить менеджер
- `get_manager(name) -> Optional[Any]` - получить менеджер по имени
- `has_manager(name) -> bool` - проверить наличие менеджера

**Производительность и кэширование:**
- `_call_manager(manager_name, method_name, *args, **kwargs)` - универсальный метод для вызова методов менеджеров
  - **Автоматическое кэширование:** методы менеджеров кэшируются при первом вызове через `getattr()`
  - **Ключ кэша:** `(manager_name, method_name)` - уникальная комбинация менеджера и метода
  - **Оптимизация:** избегает повторных вызовов `getattr()` для часто используемых методов
  - **Автоматическая очистка:** кэш очищается при:
    - Ошибках вызова метода (метод мог быть удален или изменен)
    - Удалении менеджера через `unregister_manager()`
    - Регистрации нового менеджера с тем же именем через `register_manager()`
  - **Безопасность:** кэшируются только callable методы, None значения также кэшируются для избежания повторных поисков

**Декораторы:**
- `@logged(level='info', log_args=False, log_result=False)`
- `@timed(metric_name=None, tags=None)`
- `@monitored(level='info', metric_name=None)`

#### Кэширование методов менеджеров

`ObservableMixin` использует автоматическое кэширование методов менеджеров для оптимизации производительности.

**Как это работает:**

1. **Первый вызов:** При первом вызове `_call_manager('logger', 'info', ...)` метод `info` получается через `getattr()` и сохраняется в кэше с ключом `('logger', 'info')`.

2. **Последующие вызовы:** При повторных вызовах метод берется из кэша, избегая повторных вызовов `getattr()`.

3. **Автоматическая очистка:** Кэш автоматически очищается в следующих случаях:
   - При ошибке вызова метода (метод мог быть удален или изменен динамически)
   - При удалении менеджера через `unregister_manager()`
   - При регистрации нового менеджера с тем же именем через `register_manager()`

**Пример:**

```python
class MyService(ObservableMixin):
    def __init__(self):
        from unittest.mock import Mock
        logger = Mock()
        logger.info = Mock()
        ObservableMixin.__init__(self, managers={'logger': logger}, config={'logger': True})
    
    def process(self):
        # Первый вызов - метод кэшируется
        self._call_manager('logger', 'info', 'First call')
        
        # Второй вызов - используется кэш (быстрее)
        self._call_manager('logger', 'info', 'Second call')
        
        # getattr() вызывается только один раз!
```

**Преимущества:**
- Улучшает производительность при частых вызовах одних и тех же методов
- Прозрачно для пользователя - работает автоматически
- Безопасно - кэш очищается при изменениях

#### Подробная документация

Полная документация по `ObservableMixin` доступна в [QUICK_START.md](QUICK_START.md) для быстрого старта.

---

## Взаимодействие компонентов

### Типичные паттерны использования

#### 1. Менеджер с ObservableMixin и адаптером

```python
class CommandManager(BaseCommandManager, ObservableMixin):
    """Менеджер команд с поддержкой наблюдаемости."""
    
    def __init__(self, process_name: str, managers=None, config=None, process=None):
        BaseCommandManager.__init__(self, process_name)
        
        ObservableMixin.__init__(
            self,
            managers=managers or {},
            config=config or {}
        )
        
        # Основная функциональность менеджера
        self.dispatcher = Dispatcher(f"{process_name}_commands")
    
    def register_command(self, command_name: str, handler: Callable):
        """Регистрация команды."""
        self._log_info(f"Registering command: {command_name}")
        return self.dispatcher.register_handler(command_name, handler)
    
    def handle_command(self, message: Dict):
        """Обработка команды."""
        self._log_debug(f"Handling command: {message.get('command')}")
        return self.dispatcher.dispatch(message)

# Использование с адаптером
manager = CommandManager("app", managers={'logger': logger_manager})
adapter = CommandAdapter(manager, process=my_process)
manager.attach_adapter(adapter)
adapter.setup()

# Основная функциональность через менеджер
manager.register_command("test", handler)
result = manager.handle_command({"command": "test", "data": {}})

# Уникальная функциональность через адаптер
adapter.execute_via_message("test", {}, ["target_process"])
```

#### 2. Адаптер как инструмент (не дублирует методы менеджера)

```python
class CommandAdapter(BaseAdapter):
    """Адаптер для интеграции CommandManager с процессом."""
    
    def setup(self) -> bool:
        """Настройка адаптера."""
        if not self.manager:
            self._log("error", "Manager is not set")
            return False
        
        self._initialized = True
        self._log("info", "CommandAdapter initialized")
        return True
    
    def execute_via_message(self, command_name: str, args: Dict, targets: List[str]):
        """
        УНИКАЛЬНАЯ функциональность адаптера.
        Основные методы (register_command, handle_command) доступны через manager.
        """
        # Интеграция с процессом - уникальная для адаптера
        if not self.process or not hasattr(self.process, 'message_manager'):
            self._log("error", "Process integration not available")
            return False
        
        # Используем менеджер для основной работы
        cmd_msg = self.process.message_manager.create_command_message(
            command=command_name, args=args, targets=targets
        )
        
        # Отправляем через роутер процесса
        return self.process.router.send(cmd_msg.to_dict())
```

#### 3. Полный пример использования

```python
# Создание менеджера с ObservableMixin
command_manager = CommandManager(
    "app",
    managers={'logger': logger_manager, 'statistics': stats_manager},
    config={'logger': True, 'statistics': True}
)

# Подключение адаптера (инструмента)
command_adapter = CommandAdapter(command_manager, process=my_process)
command_manager.attach_adapter(command_adapter, name="command")  # Рекомендуется указывать имя явно
command_adapter.setup()

# Использование - основная функциональность через менеджер
command_manager.register_command("greet", lambda data: f"Hello, {data.get('name')}!")
result = command_manager.handle_command({"command": "greet", "data": {"name": "Alice"}})

# Уникальная функциональность через адаптер
command_adapter.execute_via_message("greet", {"name": "Bob"}, ["other_process"])

# Доступ к адаптеру разными способами
adapter1 = command_manager.get_adapter("command")
adapter2 = command_manager.get_adapter()  # Первый адаптер
adapter3 = command_manager.command_adapter  # Magic-атрибут
```

---

## Примеры использования

### Пример 1: Создание менеджера с ObservableMixin и адаптером

```python
from multiprocess_framework.modules.Base_manager_module import (
    BaseManager, ObservableMixin, BaseAdapter
)

class DataManager(BaseManager, ObservableMixin):
    def __init__(self, manager_name: str, logger=None, stats=None, process=None):
        BaseManager.__init__(self, manager_name, process)
        
        managers = {}
        if logger:
            managers['logger'] = logger
        if stats:
            managers['statistics'] = stats
        
        ObservableMixin.__init__(
            self,
            managers=managers,
            config={'logger': True, 'statistics': True}
        )
    
    def initialize(self) -> bool:
        self._log_info("Инициализация DataManager")
        self.is_initialized = True
        return True
    
    def shutdown(self) -> bool:
        self._log_info("Завершение DataManager")
        self.is_initialized = False
        return True
    
    def process_data(self, data):
        """Основная функциональность менеджера."""
        self._log_info("Обработка данных")
        start_time = time.time()
        
        try:
            result = self._process(data)
            duration = time.time() - start_time
            self._record_timing("data.processing", duration)
            self._record_metric("data.processed")
            return result
        except Exception as e:
            self._track_error(e, {"operation": "process_data"})
            raise

# Адаптер с уникальной функциональностью
class DataAdapter(BaseAdapter):
    def setup(self) -> bool:
        if not self.manager:
            self._log("error", "Manager is not set")
            return False
        self._initialized = True
        return True
    
    def send_to_external_system(self, data):
        """Уникальная функциональность - интеграция с внешней системой."""
        # Основная обработка через менеджер
        processed = self.manager.process_data(data)
        
        # Уникальная логика адаптера
        if self.process and hasattr(self.process, 'external_api'):
            return self.process.external_api.send(processed)
        return processed

# Использование
manager = DataManager("DataManager", logger=logger_manager)
adapter = DataAdapter(manager, process=my_process)
manager.attach_adapter(adapter)
adapter.setup()

# Основная функциональность
result = manager.process_data(data)

# Уникальная функциональность
adapter.send_to_external_system(data)
```

---

## Руководство по выбору

### Когда использовать Manager?

**Всегда!** Менеджер - это основной класс, содержащий всю бизнес-логику и функциональность.

### Когда использовать Adapter?

Используйте адаптер, когда нужно:
- ✅ Интегрировать менеджер с процессом (межпроцессное взаимодействие)
- ✅ Добавить специализированные методы, которые не являются основной функциональностью
- ✅ Упростить доступ к менеджеру в конкретном контексте

**НЕ используйте адаптер** для:
- ❌ Дублирования методов менеджера - используйте менеджер напрямую
- ❌ Основной функциональности - это работа менеджера

### Когда использовать ObservableMixin?

Используйте ObservableMixin, когда нужно:
- ✅ Добавить логирование к менеджеру или сервису
- ✅ Добавить мониторинг и статистику
- ✅ Обработку ошибок
- ✅ Комбинировать несколько менеджеров (logger, statistics, error_tracker)

---

## Преимущества новой архитектуры

### ✅ Упрощение

- **Один источник истины** - основная функциональность в менеджере
- **Нет дублирования** - адаптер не повторяет методы менеджера
- **Понятная структура** - менеджер главный, адаптер - инструмент

### ✅ Гибкость

- **Несколько адаптеров** - можно подключить несколько адаптеров к одному менеджеру
- **Опциональность** - адаптер не обязателен, менеджер работает сам по себе
- **Легкое расширение** - легко добавлять новые типы адаптеров

### ✅ Удобство использования

- **Magic-доступ** - `manager.command_adapter` вместо `manager.get_adapter("command")`
- **Автоматическое определение имени** - не нужно явно указывать имя адаптера
- **Единый интерфейс** - все менеджеры работают одинаково

### ✅ Чистая архитектура

- **Композиция вместо наследования** - адаптер включается в менеджер
- **Разделение ответственности** - менеджер делает работу, адаптер расширяет
- **Интеграция ObservableMixin** - адаптеры автоматически используют логирование менеджера

---

## Миграция со старой архитектуры

Если у вас был код, использующий старую архитектуру:

**Было:**
```python
adapter.register("cmd", handler)
adapter.execute("cmd", data)
adapter.list_commands()
```

**Стало:**
```python
manager.register_command("cmd", handler)  # Через менеджер
manager.handle_command({"command": "cmd", "data": data})  # Через менеджер
manager.get_commands()  # Через менеджер

# Адаптер только для уникальной функциональности
adapter.execute_via_message("cmd", data, ["target"])
```
