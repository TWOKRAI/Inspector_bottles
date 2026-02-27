# Component Data Module

Универсальная система данных компонентов - "ДНК" каждого компонента системы.

## Концепция

Каждый компонент (процесс, менеджер, модуль) имеет свой `ComponentData` - структурированный объект, который хранит:
- Все параметры и конфигурацию компонента
- Состояние и статус
- Метаданные
- Связи с другими компонентами
- Временные метки для версионности

**Все данные хранятся в ProcessData.custom** - один файл на процесс, который хранит всю информацию о процессе и его менеджерах.

## Основные возможности

✅ **Единая структура** - все данные компонента в одном месте  
✅ **Автоматическая регистрация** - при создании менеджера автоматически регистрируется в ProcessData  
✅ **Дефолтные схемы** - автоматическое заполнение недостающих полей  
✅ **Интеграция с ProcessData** - тесная интеграция с SharedResourcesModule  
✅ **Публичный API** - четкое разделение публичных и приватных методов  
✅ **Удобный доступ** - через `process.component_data` в менеджерах  
✅ **Сериализация** - YAML как основной формат, также JSON, dict  
✅ **Гибкие методы** - чтение, изменение, удаление определенных участков данных  

## Архитектура

### Структура хранения

```
ProcessData (SharedResourcesModule)
└── custom.component_managers
    ├── LoggerManager/
    │   ├── logger_main: BaseManagerData
    │   └── logger_backup: BaseManagerData
    ├── CommandManager/
    │   └── command_handler: BaseManagerData
    └── RouterManager/
        └── router_main: BaseManagerData
```

### Компоненты модуля

1. **ComponentDataManager** - главный менеджер, единая точка доступа
2. **ProcessDataAdapter** - адаптер для доступа из менеджеров через `process`
3. **ComponentDataFactory** - фабрика для создания с автоматической регистрацией
4. **DefaultSchemaProvider** - хранение дефолтных схем
5. **Интерфейсы** - публичный API с четким разделением методов

## Использование

### 1. Регистрация дефолтной схемы

```python
from multiprocess_framework.modules.Component_data_module import DefaultSchemaProvider

# Регистрируем схему для LoggerManager
DefaultSchemaProvider.register_schema(
    "LoggerManager",
    {
        "config": {
            "log_level": "INFO",
            "file_path": "logs/app.log",
            "max_file_size": 10485760
        },
        "stats": {
            "messages_logged": 0
        }
    }
)
```

### 2. Создание менеджера с автоматической регистрацией

```python
from multiprocess_framework.modules.Component_data_module import create_manager_data

# В __init__ менеджера
class LoggerManager(BaseManager):
    def __init__(self, process=None, ...):
        super().__init__("LoggerManager", process)
        
        # Создаем и автоматически регистрируем данные менеджера
        self.manager_data = create_manager_data(
            manager_class="LoggerManager",
            manager_name="logger_main",
            data={
                "config": {
                    "log_level": "DEBUG"  # Переопределяет дефолт
                }
            },
            process_name=process.name if process else None,
            auto_register=True
        )
        
        # Инициализируем адаптер для удобного доступа
        if process:
            from multiprocess_framework.modules.Component_data_module import ProcessDataAdapter
            from multiprocess_framework.modules.Shared_resources_module import SharedResourcesManager
            
            shared_resources = getattr(process, 'shared_resources', None)
            self.component_data = ProcessDataAdapter(process, shared_resources)
```

### 3. Доступ к данным из менеджера

```python
# В методах менеджера

# Получить свою конфигурацию
log_level = self.component_data.get_manager_config(
    "LoggerManager",
    "logger_main",
    "log_level"
)

# Получить конфигурацию процесса
db_host = self.component_data.get_process_config("database.host")

# Получить конфигурацию другого менеджера
command_config = self.component_data.get_manager_config(
    "CommandManager",
    "command_handler",
    "enable_logging"
)

# Обновить свою конфигурацию
self.component_data.update_manager_config(
    "LoggerManager",
    "logger_main",
    "log_level",
    "ERROR"
)

# Получить полные данные менеджера
manager_data = self.component_data.get_manager_data("logger_main", "LoggerManager")

# Получить статус менеджера
status = self.component_data.get_manager_status("logger_main", "LoggerManager")

# Установить статус
self.component_data.set_manager_status("logger_main", "running", "LoggerManager")
```

### 4. Доступ из главного процесса

```python
from multiprocess_framework.modules.Component_data_module import get_component_data_manager
from multiprocess_framework.modules.Shared_resources_module import SharedResourcesManager

shared_resources = SharedResourcesManager()
component_data_manager = get_component_data_manager(shared_resources)

# Получить данные менеджера
manager_data = component_data_manager.get_manager_data(
    "logger_main",
    manager_type="LoggerManager",
    process_name="VisionProcess"
)

# Получить список всех менеджеров процесса
managers = component_data_manager.list_managers(process_name="VisionProcess")

# Удалить менеджер
component_data_manager.remove_manager(
    "logger_main",
    manager_type="LoggerManager",
    process_name="VisionProcess"
)

# Удалить все менеджеры определенного типа
count = component_data_manager.remove_managers_by_type(
    "LoggerManager",
    process_name="VisionProcess"
)
```

### 5. Сериализация в YAML

```python
from pathlib import Path
from multiprocess_framework.modules.Component_data_module import ComponentDataManager

component_data_manager = ComponentDataManager.get_instance()

# Получить данные процесса
process_data = component_data_manager.get_process_data("VisionProcess")

# Сериализовать в YAML файл
component_data_manager.to_yaml(process_data, Path("data/vision_process.yaml"))

# Или получить YAML строку
yaml_str = component_data_manager.to_yaml(process_data)

# Загрузить из YAML
loaded_data = component_data_manager.from_yaml(Path("data/vision_process.yaml"))
```

### 6. Работа с дефолтными значениями

```python
from multiprocess_framework.modules.Component_data_module import (
    DefaultSchemaProvider,
    ComponentDataFactory
)

# Регистрация схемы
DefaultSchemaProvider.register_schema(
    "MyManager",
    {
        "config": {
            "param1": "default1",
            "param2": "default2"
        }
    }
)

# Создание с частичными данными (недостающие поля берутся из схемы)
manager_data = ComponentDataFactory.create_manager_data(
    "MyManager",
    "my_manager",
    data={
        "config": {
            "param1": "custom1"  # param2 будет взят из схемы
        }
    }
)
```

## Интеграция с BaseManager

Для упрощения интеграции можно добавить в BaseManager:

```python
# В BaseManager.__init__
from multiprocess_framework.modules.Component_data_module import ProcessDataAdapter

def __init__(self, manager_name, process=None):
    # ... существующий код ...
    
    # Инициализируем адаптер для доступа к ComponentData
    if process:
        shared_resources = getattr(process, 'shared_resources', None)
        self.component_data = ProcessDataAdapter(process, shared_resources)
    else:
        self.component_data = None
```

## Публичный API

### ComponentDataManager

Главный менеджер для работы с данными компонентов:

- `register_manager()` - регистрация менеджера
- `get_manager_data()` - получение данных менеджера
- `remove_manager()` - удаление менеджера
- `list_managers()` - список менеджеров
- `get_manager_config()` - получение конфигурации
- `update_manager_config()` - обновление конфигурации
- `to_yaml()` / `from_yaml()` - сериализация

### ProcessDataAdapter

Адаптер для доступа из менеджеров:

- `get_manager_config()` - получить конфигурацию менеджера
- `get_process_config()` - получить конфигурацию процесса
- `update_manager_config()` - обновить конфигурацию
- `get_manager_data()` - получить полные данные
- `list_managers()` - список менеджеров
- `get_manager_status()` / `set_manager_status()` - работа со статусом

## Интерфейсы

Модуль использует интерфейсы для четкого разделения публичного и приватного API:

- `IComponentDataAccess` - доступ к данным
- `IComponentDataRegistry` - регистрация компонентов
- `IComponentDataSerializer` - сериализация

Это упрощает тестирование и позволяет создавать моки.

## Преимущества

✅ **Один файл на процесс** - все данные процесса в ProcessData  
✅ **Автоматическая регистрация** - менеджеры регистрируются автоматически  
✅ **Удобный доступ** - через `process.component_data` в менеджерах  
✅ **Дефолтные значения** - схемы предотвращают ошибки  
✅ **Гибкость** - методы для чтения, изменения, удаления  
✅ **Типобезопасность** - dataclass обеспечивает проверку типов  
✅ **Сериализация** - YAML как основной формат  
✅ **Тестируемость** - интерфейсы упрощают создание моков  

## Миграция

При создании нового менеджера:

1. Зарегистрируйте дефолтную схему (опционально)
2. Создайте ManagerData через `create_manager_data()` в `__init__`
3. Инициализируйте `ProcessDataAdapter` для доступа к данным
4. Используйте `self.component_data` для доступа к конфигурациям
