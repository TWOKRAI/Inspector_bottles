# Модуль Command_module

Модуль для управления и выполнения команд в многопроцессной архитектуре приложения.

## Содержание

- [Обзор](#обзор)
- [Архитектура](#архитектура)
- [Быстрый старт](#быстрый-старт)
- [API Reference](#api-reference)
- [Примеры использования](#примеры-использования)
- [Интеграция с другими модулями](#интеграция-с-другими-модулями)
- [Тестирование](#тестирование)

## Обзор

Модуль `Command_module` предоставляет систему управления командами, которая позволяет:
- Регистрировать обработчики команд
- Выполнять команды с различными стратегиями диспетчеризации
- Управлять метаданными и тегами команд
- Интегрироваться с системой логирования, статистики и обработки ошибок
- Работать со сценариями выполнения команд

### Основные компоненты

1. **BaseCommandManager** - абстрактный базовый класс, определяющий интерфейс
2. **CommandManager** - основная реализация менеджера команд
3. **CommandAdapter** - адаптер для упрощенной работы с командами

## Архитектура

```
CommandManager
├── BaseCommandManager (абстрактный интерфейс)
├── ObservableMixin (логирование, статистика, ошибки)
└── Dispatcher (диспетчеризация команд)
    ├── EXACT_MATCH (точное совпадение)
    ├── PATTERN_MATCH (регулярные выражения)
    ├── FALLBACK_MATCH (fallback с приоритетом)
    └── CHAIN_MATCH (сценарии)
```

### Зависимости

- `Dispatch_module` - для диспетчеризации команд
- `Base_manager_module` - для ObservableMixin и BaseAdapter

## Быстрый старт

### Базовое использование

```python
from src.Modules.Command_module import CommandManager

# Создание менеджера
manager = CommandManager("my_process")

# Регистрация команды
def greet_handler(data):
    name = data.get("name", "World")
    return f"Hello, {name}!"

manager.register_command("greet", greet_handler)

# Выполнение команды
message = {
    "command": "greet",
    "data": {"name": "Alice"}
}
result = manager.handle_command(message)
print(result)  # "Hello, Alice!"
```

### Использование с менеджерами

```python
from src.Modules.Command_module import CommandManager

# Создание с менеджерами логирования и статистики
manager = CommandManager(
    "my_process",
    managers={
        'logger': logger_manager,
        'statistics': stats_manager,
        'error': error_manager
    }
)

# Команды автоматически логируются и учитываются в статистике
manager.register_command("process", process_handler)
result = manager.handle_command({"command": "process", "data": {}})
```

### Использование адаптера

```python
from src.Modules.Command_module import CommandManager, CommandAdapter

# Создание менеджера и адаптера
manager = CommandManager("my_process")
adapter = CommandAdapter(manager)
adapter.setup()

# Упрощенная регистрация и выполнение
adapter.register("greet", greet_handler)
result = adapter.execute("greet", {"name": "Bob"})
```

## API Reference

### BaseCommandManager

Абстрактный базовый класс для командных менеджеров.

#### Методы

- `register_command(command_name: str, handler: Callable, **kwargs) -> bool`
- `handle_command(message: Dict) -> Any`
- `get_commands() -> List[Dict]`

### CommandManager

Основная реализация менеджера команд.

#### Инициализация

```python
CommandManager(
    process_name: str,
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

##### register_command

Регистрация новой команды.

```python
register_command(
    command_name: str,
    handler: Callable,
    expects_full_message: bool = False,
    metadata: Dict[str, Any] = None,
    efficiency: int = 0,
    tags: List[str] = None,
    strategy: Optional[DispatchStrategy] = None,
    **kwargs
) -> bool
```

**Параметры:**
- `command_name` - название команды (ключ для диспетчеризации)
- `handler` - функция-обработчик команды
- `expects_full_message` - если True, обработчик получает всё сообщение
- `metadata` - дополнительные метаданные команды
- `efficiency` - уровень эффективности (для FALLBACK_MATCH)
- `tags` - список тегов для группировки
- `strategy` - стратегия для регистрации (опционально)

**Возвращает:** `True` если регистрация успешна

**Пример:**
```python
metadata = {"description": "Greeting command", "version": "1.0"}
manager.register_command(
    "greet",
    greet_handler,
    metadata=metadata,
    tags=["user", "interaction"]
)
```

##### handle_command

Обработка командного сообщения.

```python
handle_command(message: Dict) -> Any
```

**Параметры:**
- `message` - сообщение для обработки. Ожидается поле `command` с именем команды и `data` с данными

**Возвращает:** Результат выполнения команды или сообщение об ошибке

**Пример:**
```python
message = {
    "command": "greet",
    "data": {"name": "Alice"}
}
result = manager.handle_command(message)
```

##### get_commands

Получение списка всех зарегистрированных команд.

```python
get_commands() -> List[Dict]
```

**Возвращает:** Список словарей с информацией о каждом обработчике

##### get_command_info

Получение информации о конкретной команде.

```python
get_command_info(command_name: str) -> Optional[Dict]
```

**Возвращает:** Словарь с информацией о команде или `None`

##### get_commands_by_tag

Получение команд по тегу.

```python
get_commands_by_tag(tag: str) -> List[Dict]
```

**Возвращает:** Список команд с указанным тегом

##### update_command_metadata

Обновление метаданных команды.

```python
update_command_metadata(command_name: str, metadata: Dict[str, Any]) -> bool
```

##### update_command_tags

Обновление тегов команды.

```python
update_command_tags(command_name: str, tags: List[str]) -> bool
```

##### overwrite_command

Принудительная перезапись команды.

```python
overwrite_command(
    command_name: str,
    handler: Callable,
    expects_full_message: bool = False,
    metadata: Dict[str, Any] = None,
    efficiency: int = 0,
    tags: List[str] = None
) -> bool
```

##### get_stats

Получение статистики командного менеджера.

```python
get_stats() -> Dict[str, Any]
```

**Возвращает:** Словарь со статистикой:
- `process_name` - имя процесса
- `total_commands` - общее количество команд
- `commands` - список названий команд
- `dispatcher_strategy` - стратегия диспетчера

### CommandAdapter

Адаптер для упрощенной работы с командами.

#### Инициализация

```python
CommandAdapter(command_manager: CommandManager, process: Optional[Any] = None)
```

#### Основные методы

##### setup

Настройка адаптера и регистрация базовых команд.

```python
setup() -> bool
```

##### execute_via_message

**Уникальный метод адаптера** - выполнение команды через систему сообщений процесса.

Выполнение команды через систему сообщений.

```python
execute_via_message(
    command_name: str,
    args: Dict,
    targets: List[str],
    need_ack: bool = False
) -> bool
```

##### get_stats

Получение статистики адаптера.

```python
get_stats() -> Dict[str, Any]
```

## Примеры использования

### Пример 1: Базовое использование

```python
from src.Modules.Command_module import CommandManager

manager = CommandManager("app")

# Регистрация обработчиков
def add_handler(data):
    a = data.get("a", 0)
    b = data.get("b", 0)
    return a + b

def multiply_handler(data):
    a = data.get("a", 1)
    b = data.get("b", 1)
    return a * b

manager.register_command("add", add_handler, tags=["math"])
manager.register_command("multiply", multiply_handler, tags=["math"])

# Выполнение команд
result1 = manager.handle_command({"command": "add", "data": {"a": 5, "b": 3}})
print(result1)  # 8

result2 = manager.handle_command({"command": "multiply", "data": {"a": 4, "b": 7}})
print(result2)  # 28

# Получение команд по тегу
math_commands = manager.get_commands_by_tag("math")
print(len(math_commands))  # 2
```

### Пример 2: Работа с метаданными

```python
from src.Modules.Command_module import CommandManager

manager = CommandManager("app")

def process_handler(data):
    return {"processed": True, "data": data}

# Регистрация с метаданными
manager.register_command(
    "process",
    process_handler,
    metadata={
        "description": "Обработка данных",
        "version": "1.0",
        "author": "System"
    },
    tags=["processing", "data"]
)

# Получение информации
info = manager.get_command_info("process")
print(info["metadata"]["description"])  # "Обработка данных"

# Обновление метаданных
manager.update_command_metadata("process", {
    "version": "2.0",
    "updated": True
})
```

### Пример 3: Использование различных стратегий

```python
from src.Modules.Command_module import CommandManager
from src.Modules.Dispatch_module import DispatchStrategy

manager = CommandManager("app")

# EXACT_MATCH (по умолчанию)
def exact_handler(data):
    return "exact"

manager.register_command("test", exact_handler, strategy=DispatchStrategy.EXACT_MATCH)

# PATTERN_MATCH
def pattern_handler(data):
    return "pattern"

manager.register_command(
    r"test.*",
    pattern_handler,
    strategy=DispatchStrategy.PATTERN_MATCH
)

# FALLBACK_MATCH
def fallback_handler(data):
    return "fallback"

manager.register_command(
    "test",
    fallback_handler,
    strategy=DispatchStrategy.FALLBACK_MATCH,
    efficiency=10
)

# Выполнение с указанием стратегии
result1 = manager.handle_command({"command": "test", "data": {}})
# Используется EXACT_MATCH по умолчанию

result2 = manager.handle_command({
    "command": "test",
    "strategy": "fallback",
    "data": {}
})
# Используется FALLBACK_MATCH
```

### Пример 4: Работа со сценариями

```python
from src.Modules.Command_module import CommandManager

manager = CommandManager("app")

# Определение шагов сценария
def step1_handler(data):
    value = data.get("value", 0)
    return {"step": 1, "value": value + 1}

def step2_handler(data):
    value = data.get("value", 0)
    return {"step": 2, "value": value * 2}

def step3_handler(data):
    value = data.get("value", 0)
    return {"step": 3, "value": value - 1}

# Создание сценария
manager.dispatcher.create_scenario("process_data", "Обработка данных")
manager.dispatcher.add_handler_to_scenario("process_data", "step1", step1_handler, stage=1)
manager.dispatcher.add_handler_to_scenario("process_data", "step2", step2_handler, stage=2)
manager.dispatcher.add_handler_to_scenario("process_data", "step3", step3_handler, stage=3)

# Выполнение сценария
message = {
    "command": "process_data",
    "data": {"value": 5}
}
result = manager.handle_command(message)

# Результат содержит информацию о всех этапах
print(result["status"])  # "success"
print(len(result["stages"]))  # 3
print(result["stages"][2]["result"]["value"])  # 11 (после всех преобразований)
```

### Пример 5: Интеграция с ObservableMixin

```python
from src.Modules.Command_module import CommandManager

# Создание с менеджерами
manager = CommandManager(
    "app",
    managers={
        'logger': logger_manager,
        'statistics': stats_manager,
        'error': error_manager
    }
)

def risky_handler(data):
    if data.get("fail"):
        raise ValueError("Intentional error")
    return "success"

manager.register_command("risky", risky_handler)

# Временно отключаем логирование
with manager.context('logger', enabled=False):
    result = manager.handle_command({"command": "risky", "data": {"fail": False}})

# Включаем/выключаем менеджеры
manager.disable('statistics')
# Статистика не записывается

manager.enable('statistics')
# Статистика снова записывается

# Получение состояния
state = manager.get_state()
print(state["enabled_managers"])  # ['logger', 'statistics', 'error']
```

### Пример 6: Использование адаптера

```python
from src.Modules.Command_module import CommandManager, CommandAdapter

manager = CommandManager("app")
adapter = CommandAdapter(manager)
adapter.setup()

# Регистрация команд
def handler1(data):
    return "result1"

def handler2(data):
    return "result2"

adapter.register("cmd1", handler1)
adapter.register("cmd2", handler2, metadata={"description": "Command 2"})

# Выполнение
result1 = adapter.execute("cmd1", {})
result2 = adapter.execute("cmd2", {})

# Проверка наличия
assert adapter.has_command("cmd1")
assert adapter.has_command("cmd2")

# Получение информации
info = adapter.get_command_info("cmd2")
print(info["metadata"]["description"])

# Список команд
commands = adapter.list_commands()

# Статистика
stats = adapter.get_stats()
print(stats["total_commands"])

# Отмена регистрации
adapter.unregister("cmd1")
assert not adapter.has_command("cmd1")
```

### Пример 7: Обработчик с полным сообщением

```python
from src.Modules.Command_module import CommandManager

manager = CommandManager("app")

def full_message_handler(message):
    # Получаем полное сообщение, а не только data
    command = message.get("command")
    data = message.get("data", {})
    metadata = message.get("metadata", {})
    
    return {
        "command": command,
        "processed_data": data,
        "metadata": metadata,
        "timestamp": time.time()
    }

manager.register_command(
    "process_full",
    full_message_handler,
    expects_full_message=True
)

message = {
    "command": "process_full",
    "data": {"key": "value"},
    "metadata": {"source": "api"}
}
result = manager.handle_command(message)
```

## Интеграция с другими модулями

### Интеграция с Logger_module

```python
from src.Modules.Command_module import CommandManager
from src.Modules.Logger_module import LoggerManager

logger_manager = LoggerManager("app")
manager = CommandManager(
    "app",
    managers={'logger': logger_manager}
)

# Все команды автоматически логируются
manager.register_command("test", handler)
manager.handle_command({"command": "test", "data": {}})
```

### Интеграция с Process_module

```python
from src.Modules.Command_module import CommandAdapter
from src.Modules.Process_module import BaseProcess

class MyProcess(BaseProcess):
    def setup_managers(self):
        super().setup_managers()
        self.command_manager = CommandManager(self.process_name)
        self.command_adapter = CommandAdapter(self.command_manager, self)
        self.command_adapter.setup()
    
    def register_commands(self):
        # Используем менеджер для регистрации команд
        self.command_manager.register_command("process", self.process_handler)
    
    def process_handler(self, data):
        return {"processed": True}
```

## Тестирование

Модуль полностью покрыт тестами. Для запуска тестов:

```bash
# Все тесты модуля
pytest tests/Test_Command_module/

# Конкретный файл тестов
pytest tests/Test_Command_module/test_command_manager_pytest.py

# С покрытием кода
pytest tests/Test_Command_module/ --cov=src.Modules.Command_module --cov-report=html
```

### Структура тестов

- `test_command_manager_pytest.py` - полные тесты на pytest с покрытием всех сценариев
- `test_command_manager.py` - тесты на unittest (legacy)

### Покрытие тестами

- ✅ Инициализация и конфигурация
- ✅ Регистрация команд (все варианты)
- ✅ Выполнение команд (все стратегии)
- ✅ Управление метаданными и тегами
- ✅ Работа со сценариями
- ✅ Интеграция с ObservableMixin
- ✅ Обработка ошибок и граничных случаев
- ✅ CommandAdapter (все методы)
- ✅ Производительность (базовые проверки)

## Лучшие практики

1. **Именование команд**: Используйте понятные и уникальные имена команд
2. **Обработка ошибок**: Всегда обрабатывайте исключения в обработчиках
3. **Метаданные**: Добавляйте метаданные для документирования команд
4. **Теги**: Используйте теги для группировки связанных команд
5. **Логирование**: Используйте менеджеры для автоматического логирования
6. **Валидация**: Валидируйте входные данные в обработчиках

## Известные ограничения

1. `CommandAdapter.unregister()` удаляет команду только из локального реестра, но не из менеджера
2. При использовании `expects_full_message=True` обработчик должен корректно обрабатывать структуру сообщения

## История изменений

### Версия 1.0
- Базовая функциональность
- Поддержка всех стратегий диспетчеризации
- Интеграция с ObservableMixin
- CommandAdapter

