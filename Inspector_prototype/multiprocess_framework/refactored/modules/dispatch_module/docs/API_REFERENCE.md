# Справочник API DispatchModule

## Dispatcher

### Инициализация

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

### Методы регистрации

#### register_handler

Регистрация обработчика.

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

#### overwrite_handler

Принудительная перезапись обработчика.

```python
overwrite_handler(
    key: str,
    handler: Callable,
    expects_full_message: bool = False,
    metadata: Dict[str, Any] = None,
    efficiency: int = 0,
    tags: List[str] = None
) -> bool
```

### Методы диспетчеризации

#### dispatch

Диспетчеризация сообщения.

```python
dispatch(
    message: Dict[str, Any],
    key_field: str = "command",
    data_field: str = "data"
) -> Any
```

#### dispatch_scenario

Выполнение сценария.

```python
dispatch_scenario(
    scenario_name: str,
    message: Dict[str, Any],
    data_field: str = "data",
    stop_on_error: bool = True
) -> Dict[str, Any]
```

### Методы получения информации

#### get_handler_info

Получение информации об обработчике.

```python
get_handler_info(key: str) -> Optional[Dict]
```

#### get_all_handlers

Получение всех обработчиков.

```python
get_all_handlers() -> List[Dict]
```

#### get_handlers_by_tag

Получение обработчиков по тегу.

```python
get_handlers_by_tag(tag: str) -> List[Dict]
```

### Методы обновления

#### update_handler_efficiency

Обновление эффективности обработчика.

```python
update_handler_efficiency(key: str, new_efficiency: int) -> bool
```

#### update_handler_metadata

Обновление метаданных обработчика.

```python
update_handler_metadata(key: str, new_metadata: Dict[str, Any]) -> bool
```

#### update_handler_tags

Обновление тегов обработчика.

```python
update_handler_tags(key: str, new_tags: List[str]) -> bool
```

#### update_handler_function

Обновление функции обработчика.

```python
update_handler_function(key: str, new_handler: Callable) -> bool
```

#### update_expects_full_message

Обновление флага expects_full_message.

```python
update_expects_full_message(key: str, expects_full: bool) -> bool
```

### Методы работы со сценариями

#### create_scenario

Создание сценария.

```python
create_scenario(
    name: str,
    description: str = "",
    metadata: Dict[str, Any] = None
) -> bool
```

#### delete_scenario

Удаление сценария.

```python
delete_scenario(name: str) -> bool
```

#### get_scenario_info

Получение информации о сценарии.

```python
get_scenario_info(name: str) -> Optional[Dict[str, Any]]
```

#### get_all_scenarios

Получение всех сценариев.

```python
get_all_scenarios() -> List[Dict[str, Any]]
```

#### add_handler_to_scenario

Добавление обработчика в сценарий.

```python
add_handler_to_scenario(
    scenario_name: str,
    handler_key: str,
    handler: Callable,
    stage: int,
    expects_full_message: bool = False,
    metadata: Dict[str, Any] = None,
    tags: List[str] = None
) -> bool
```

#### remove_handler_from_scenario

Удаление обработчика из сценария.

```python
remove_handler_from_scenario(scenario_name: str, handler_key: str) -> bool
```

#### reorder_handler_in_scenario

Изменение порядка обработчика в сценарии.

```python
reorder_handler_in_scenario(
    scenario_name: str,
    handler_key: str,
    new_stage: int
) -> bool
```

#### update_scenario_metadata

Обновление метаданных сценария.

```python
update_scenario_metadata(
    scenario_name: str,
    metadata: Dict[str, Any]
) -> bool
```

#### update_scenario_description

Обновление описания сценария.

```python
update_scenario_description(
    scenario_name: str,
    description: str
) -> bool
```

## ScenarioBuilder

### Инициализация

```python
ScenarioBuilder(dispatcher: Dispatcher)
```

### Методы

#### create

Создание сценария.

```python
create(
    name: str,
    description: str = "",
    metadata: Dict[str, Any] = None
) -> bool
```

#### delete

Удаление сценария.

```python
delete(name: str) -> bool
```

#### add_handler

Добавление обработчика в сценарий.

```python
add_handler(
    scenario_name: str,
    handler_key: str,
    handler: Callable,
    stage: int,
    expects_full_message: bool = False,
    metadata: Dict[str, Any] = None,
    tags: List[str] = None
) -> bool
```

#### remove_handler

Удаление обработчика из сценария.

```python
remove_handler(scenario_name: str, handler_key: str) -> bool
```

#### reorder

Изменение порядка обработчика.

```python
reorder(
    scenario_name: str,
    handler_key: str,
    new_stage: int
) -> bool
```

#### update_metadata

Обновление метаданных сценария.

```python
update_metadata(
    scenario_name: str,
    metadata: Dict[str, Any]
) -> bool
```

#### update_description

Обновление описания сценария.

```python
update_description(
    scenario_name: str,
    description: str
) -> bool
```

#### get_info

Получение информации о сценарии.

```python
get_info(scenario_name: str) -> Optional[Dict[str, Any]]
```

#### list_all

Получение всех сценариев.

```python
list_all() -> List[Dict[str, Any]]
```

#### exists

Проверка существования сценария.

```python
exists(scenario_name: str) -> bool
```

## Типы данных

### DispatchStrategy

Enum со стратегиями диспетчеризации:

- `EXACT_MATCH` - Точное совпадение
- `PATTERN_MATCH` - Паттерн-матчинг
- `FALLBACK_MATCH` - Fallback стратегия
- `CHAIN_MATCH` - Цепочки выполнения

### HandlerInfo

Информация об обработчике:

```python
@dataclass
class HandlerInfo:
    key: str
    handler: Callable
    expects_full_message: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    efficiency: int = 0
    tags: Set[str] = field(default_factory=set)
    stage: int = 0
```

### Scenario

Сценарий выполнения:

```python
@dataclass
class Scenario:
    name: str
    handlers: List[HandlerInfo] = field(default_factory=list)
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
```

## Интерфейсы

### IDispatcher

Интерфейс для диспетчера сообщений.

```python
class IDispatcher(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass
    
    @abstractmethod
    def register_handler(...) -> bool:
        pass
    
    @abstractmethod
    def dispatch(...) -> Any:
        pass
    
    @abstractmethod
    def get_handler_info(...) -> Optional[Dict]:
        pass
    
    @abstractmethod
    def get_all_handlers(...) -> List[Dict]:
        pass
    
    @abstractmethod
    def get_handlers_by_tag(...) -> List[Dict]:
        pass
```

## Дополнительные ресурсы

- [USAGE_GUIDE.md](USAGE_GUIDE.md) - Руководство по использованию
- [ARCHITECTURE.md](ARCHITECTURE.md) - Архитектура модуля
- [STRATEGIES_GUIDE.md](STRATEGIES_GUIDE.md) - Руководство по стратегиям
- [SCENARIOS_GUIDE.md](SCENARIOS_GUIDE.md) - Руководство по сценариям

