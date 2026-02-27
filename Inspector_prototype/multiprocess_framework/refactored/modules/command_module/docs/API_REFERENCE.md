# Справочник API CommandModule

## CommandManager

### Инициализация

```python
CommandManager(
    manager_name: str,
    process: Optional[Process] = None,
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
    enable_statistics: bool = True,
    **kwargs
)
```

### Методы жизненного цикла

#### initialize

Инициализация менеджера команд.

```python
initialize() -> bool
```

#### shutdown

Завершение работы менеджера команд.

```python
shutdown() -> bool
```

### Методы работы с командами

#### register_command

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

#### handle_command

Обработка командного сообщения.

```python
handle_command(message: Dict) -> Any
```

#### get_commands

Получение списка всех зарегистрированных команд.

```python
get_commands() -> List[Dict]
```

#### get_command_info

Получение информации о конкретной команде.

```python
get_command_info(command_name: str) -> Optional[Dict]
```

#### get_commands_by_tag

Получение команд по тегу.

```python
get_commands_by_tag(tag: str) -> List[Dict]
```

#### update_command_metadata

Обновление метаданных команды.

```python
update_command_metadata(command_name: str, metadata: Dict[str, Any]) -> bool
```

#### update_command_tags

Обновление тегов команды.

```python
update_command_tags(command_name: str, tags: List[str]) -> bool
```

#### overwrite_command

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

#### get_stats

Получение статистики командного менеджера.

```python
get_stats() -> Dict[str, Any]
```

## BaseCommandManager

### Инициализация

```python
BaseCommandManager(process_name: str)
```

### Абстрактные методы

#### register_command

```python
@abstractmethod
register_command(command_name: str, handler: Callable, **kwargs) -> bool
```

#### handle_command

```python
@abstractmethod
handle_command(message: Dict) -> Any
```

#### get_commands

```python
@abstractmethod
get_commands() -> List[Dict]
```

## CommandAdapter

### Инициализация

```python
CommandAdapter(command_manager: CommandManager, process: Optional[Any] = None)
```

### Методы

#### setup

Настройка адаптера команд.

```python
setup() -> bool
```

#### execute_via_message

Выполнение команды через систему сообщений.

```python
execute_via_message(
    command_name: str,
    args: Dict,
    targets: List[str],
    need_ack: bool = False
) -> bool
```

#### get_stats

Получение статистики адаптера.

```python
get_stats() -> Dict[str, Any]
```

## Интерфейсы

### ICommandManager

Интерфейс для командных менеджеров.

```python
class ICommandManager(IBaseManager, ABC):
    @abstractmethod
    def register_command(...) -> bool:
        pass
    
    @abstractmethod
    def handle_command(...) -> Any:
        pass
    
    @abstractmethod
    def get_commands(...) -> List[Dict]:
        pass
    
    # ... другие методы ...
```

## Дополнительные ресурсы

- [USAGE_GUIDE.md](USAGE_GUIDE.md) - Руководство по использованию
- [ARCHITECTURE.md](ARCHITECTURE.md) - Архитектура модуля

