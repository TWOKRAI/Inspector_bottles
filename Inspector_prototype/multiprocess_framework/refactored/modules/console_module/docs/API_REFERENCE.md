# Справочник API ConsoleModule

## ConsoleManager

### Класс ConsoleManager

Менеджер консольных окон с интеграцией всех модулей системы.

**Наследование:** `BaseManager`, `ObservableMixin`, `IConsoleManager`

#### Конструктор

```python
ConsoleManager(
    manager_name: str = "ConsoleManager",
    process: Optional["ProcessType"] = None,
    command_manager: Optional[Any] = None,
    router_manager: Optional[Any] = None,
    enabled: bool = False,
    interactive: bool = False,
    redirect_enabled: bool = False,
    managers: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    enable_logging: bool = True,
    enable_error_tracking: bool = True,
    enable_statistics: bool = True,
    **kwargs
)
```

**Параметры:**
- `manager_name` (str): Имя менеджера
- `process` (Optional[ProcessType]): Ссылка на родительский процесс
- `command_manager` (Optional[Any]): CommandManager для обработки команд
- `router_manager` (Optional[Any]): RouterManager для отправки сообщений
- `enabled` (bool): Включить консоль при инициализации
- `interactive` (bool): Включить интерактивный режим
- `redirect_enabled` (bool): Включить перенаправление stdout/stderr
- `managers` (Optional[Dict[str, Any]]): Словарь менеджеров для ObservableMixin
- `config` (Optional[Dict[str, Any]]): Конфигурация для ObservableMixin
- `enable_logging` (bool): Включить логирование
- `enable_error_tracking` (bool): Включить отслеживание ошибок
- `enable_statistics` (bool): Включить статистику

#### Методы жизненного цикла

##### `initialize() -> bool`

Инициализация ConsoleManager.

**Returns:**
- `bool`: True если инициализация успешна

##### `shutdown() -> bool`

Завершение работы ConsoleManager.

**Returns:**
- `bool`: True если завершение успешно

#### Основные методы

##### `enable_console(enabled: bool = True) -> bool`

Включить/выключить консоль в процессе.

**Параметры:**
- `enabled` (bool): Включить или выключить

**Returns:**
- `bool`: True если операция успешна

##### `is_console_enabled() -> bool`

Проверить включена ли консоль.

**Returns:**
- `bool`: True если консоль включена

##### `send_message(text: str, level: str = "INFO", **kwargs) -> bool`

Отправить сообщение в консоль.

**Параметры:**
- `text` (str): Текст сообщения
- `level` (str): Уровень логирования (INFO, WARNING, ERROR, DEBUG)
- `**kwargs`: Дополнительные параметры

**Returns:**
- `bool`: True если сообщение отправлено

##### `register_in_router(router_manager, prefix: str = "console") -> List[str]`

Зарегистрировать каналы консоли в RouterManager.

**Параметры:**
- `router_manager`: Экземпляр RouterManager
- `prefix` (str): Префикс для имен каналов

**Returns:**
- `List[str]`: Список зарегистрированных каналов

##### `setup_redirect(enabled: bool = True) -> bool`

Настроить перенаправление stdout/stderr.

**Параметры:**
- `enabled` (bool): Включить или выключить перенаправление

**Returns:**
- `bool`: True если операция успешна

##### `is_redirect_enabled() -> bool`

Проверить включено ли перенаправление stdout/stderr.

**Returns:**
- `bool`: True если перенаправление включено

##### `enable_interactive(enabled: bool = True) -> bool`

Включить/выключить интерактивный режим.

**Параметры:**
- `enabled` (bool): Включить или выключить

**Returns:**
- `bool`: True если операция успешна

##### `is_interactive() -> bool`

Проверить включен ли интерактивный режим.

**Returns:**
- `bool`: True если интерактивный режим включен

##### `create_debug_process(process_name: str, process_manager, router_manager, command_manager) -> bool`

Создать отдельный процесс для отладки через ProcessManager.

**Параметры:**
- `process_name` (str): Имя процесса
- `process_manager`: ProcessManagerCore для создания процесса
- `router_manager`: RouterManager для отправки сообщений
- `command_manager`: CommandManager для обработки команд

**Returns:**
- `bool`: True если процесс создан успешно

#### Вспомогательные методы

##### `get_output_queue() -> Optional[Queue]`

Получить очередь вывода (для использования в других компонентах).

**Returns:**
- `Optional[Queue]`: Очередь вывода или None

##### `get_input_queue() -> Optional[Queue]`

Получить очередь ввода (для интерактивного режима).

**Returns:**
- `Optional[Queue]`: Очередь ввода или None

## ConsoleChannel

### Класс ConsoleChannel

Канал для отправки сообщений в консольные окна через RouterManager.

**Наследование:** `MessageChannel`, `IConsoleChannel`

#### Конструктор

```python
ConsoleChannel(
    name: str,
    console_manager,
    target_process: Optional[str] = None,
    target_console: Optional[str] = None
)
```

**Параметры:**
- `name` (str): Имя канала (например, "console.ProcessName")
- `console_manager`: Экземпляр ConsoleManager
- `target_process` (Optional[str]): Имя процесса (для родной консоли)
- `target_console` (Optional[str]): Имя консоли (для конкретной консоли)

#### Свойства

##### `name: str`

Уникальное имя канала.

##### `channel_type: str`

Тип канала ("console").

#### Методы

##### `send(message: Dict[str, Any]) -> Dict[str, Any]`

Отправить сообщение в консоль.

**Формат сообщения:**
```python
{
    "text": "Текст сообщения",              # Обязательно
    "level": "INFO|WARNING|ERROR|DEBUG",    # Опционально
    "timestamp": True/False,                 # Опционально
    "process": "ProcessName",                # Опционально
    "console": "ConsoleName"                 # Опционально
}
```

**Параметры:**
- `message` (Dict[str, Any]): Сообщение для отправки

**Returns:**
- `Dict[str, Any]`: Результат отправки: `{"status": "success|error", "channel": name, ...}`

##### `poll(timeout: float = 0.0) -> List[Dict[str, Any]]`

Опрос канала для получения сообщений (для интерактивного режима).

**Параметры:**
- `timeout` (float): Таймаут опроса (0 = non-blocking)

**Returns:**
- `List[Dict[str, Any]]`: Список полученных сообщений

##### `get_info() -> Dict[str, Any]`

Получить информацию о канале.

**Returns:**
- `Dict[str, Any]`: Информация о канале

## ConsoleRedirector

### Класс ConsoleRedirector

Перенаправитель вывода процесса в консоль(и).

#### Конструктор

```python
ConsoleRedirector(
    output_queues: Union[Queue, List[Queue]],
    process_name: str
)
```

**Параметры:**
- `output_queues` (Union[Queue, List[Queue]]): Один Queue или список Queue для отправки данных
- `process_name` (str): Имя процесса для префикса

#### Методы

##### `write(data: str)`

Запись во все queues с префиксом имени процесса.

**Параметры:**
- `data` (str): Данные для записи

##### `flush()`

Сброс буфера во все очереди.

##### `close()`

Закрытие перенаправителя.

##### `restore() -> bool`

Восстановить оригинальные stdout/stderr.

**Returns:**
- `bool`: True если восстановлено успешно

## ConsoleWindowProcess

### Класс ConsoleWindowProcess

Процесс консольного окна, читает из queue и отображает в консоли.

#### Конструктор

```python
ConsoleWindowProcess(
    title: str,
    process_names: List[str],
    output_queue: Queue
)
```

**Параметры:**
- `title` (str): Заголовок окна консоли
- `process_names` (List[str]): Список имен процессов
- `output_queue` (Queue): Queue для получения данных

#### Методы

##### `run()`

Запуск процесса консоли.

## Интерфейсы

### IConsoleManager

Интерфейс для менеджера консоли.

**Наследование:** `IBaseManager`

**Методы:**
- `enable_console(enabled: bool = True) -> bool`
- `is_console_enabled() -> bool`
- `send_message(text: str, level: str = "INFO", **kwargs) -> bool`
- `register_in_router(router_manager, prefix: str = "console") -> List[str]`
- `setup_redirect(enabled: bool = True) -> bool`
- `create_debug_process(...) -> bool`

### IConsoleChannel

Интерфейс для канала консоли.

**Свойства:**
- `name: str`
- `channel_type: str`

**Методы:**
- `send(message: Dict[str, Any]) -> Dict[str, Any]`
- `poll(timeout: float = 0.0) -> List[Dict[str, Any]]`

