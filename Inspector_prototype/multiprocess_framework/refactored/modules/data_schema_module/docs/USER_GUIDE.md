# Руководство пользователя: Модуль Data Schema

Полное руководство по использованию модуля `data_schema` для работы с данными компонентов системы.

> **Актуальный API:** в примерах ниже используются актуальные имена (`ModelFactory`, `StorageManager`, `SchemaManager`) и путь импорта `multiprocess_framework.refactored.modules.data_schema_module`. Краткий обзор — в [README.md](../README.md) и [STRUCTURE.md](STRUCTURE.md).

## 📋 Содержание

1. [Введение](#введение)
2. [Быстрый старт](#быстрый-старт)
3. [Основные компоненты](#основные-компоненты)
4. [Примеры использования](#примеры-использования)
5. [Лучшие практики](#лучшие-практики)
6. [API Reference](#api-reference)

---

## Введение

Модуль `data_schema` предоставляет унифицированный способ работы с данными компонентов системы на основе **Pydantic v2**. Модуль обеспечивает:

- ✅ **Валидацию данных** через Pydantic
- ✅ **Автоматическое заполнение дефолтных значений**
- ✅ **Конвертацию между форматами** (dict, JSON, YAML, Pydantic model)
- ✅ **Версионирование конфигураций**
- ✅ **Потокобезопасность** для многопроцессных приложений

---

## Быстрый старт

### Шаг 1: Определите схему данных

Создайте Pydantic модель для вашего компонента:

```python
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from multiprocess_framework.refactored.modules.data_schema_module import (
    BaseManagerModel,
    ComponentType
)

class LoggerManagerModel(BaseManagerModel):
    """Модель данных для LoggerManager."""
    
    # Кастомные поля
    log_level: str = Field(default="INFO", description="Уровень логирования")
    file_path: str = Field(default="logs/app.log", description="Путь к файлу")
    max_file_size: int = Field(default=10485760, description="Максимальный размер файла (байт)")
    rotation: bool = Field(default=True, description="Включить ротацию")
    format: str = Field(default="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    
    # Методы валидации (опционально)
    @field_validator('log_level')
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"log_level должен быть одним из {valid_levels}")
        return v.upper()
```

### Шаг 2: Зарегистрируйте схему

```python
from multiprocess_framework.refactored.modules.data_schema_module import (
    SchemaManager,
    register_schema
)

# Вариант 1: Использование декоратора (рекомендуется)
@register_schema("LoggerManager")
class LoggerManagerModel(BaseManagerModel):
    log_level: str = "INFO"
    file_path: str = "logs/app.log"
    # ... остальные поля

# Вариант 2: Ручная регистрация
registry = SchemaManager.get_instance()
registry.register("LoggerManager", LoggerManagerModel)
```

### Шаг 3: Создайте экземпляр модели

```python
from multiprocess_framework.refactored.modules.data_schema_module import ModelFactory

# Создание модели менеджера
manager_model = ModelFactory.create_manager(
    "LoggerManager",
    "main_logger",
    data={
        "log_level": "DEBUG",
        "file_path": "logs/debug.log"
    },
    auto_register=True,  # Автоматически зарегистрировать в ProcessData
    process_name="VisionProcess"
)

# Теперь модель доступна через ProcessData
print(manager_model.log_level)  # "DEBUG"
print(manager_model.file_path)   # "logs/debug.log"
```

---

## Основные компоненты

### 1. SchemaManager - Реестр схем

Центральный реестр для хранения и управления Pydantic моделями.

```python
from multiprocess_framework.refactored.modules.data_schema_module import SchemaManager

registry = SchemaManager.get_instance()

# Регистрация схемы
registry.register("MySchema", MyModel)

# Проверка существования
if registry.has_schema("MySchema"):
    schema = registry.get_schema("MySchema")

# Создание экземпляра с дефолтными значениями
instance = registry.create_instance("MySchema", {"field": "value"})

# Получение дефолтных значений
defaults = registry.get_defaults("MySchema")

# Валидация данных
is_valid, instance, error = registry.validate("MySchema", {"field": "value"})

# Список всех схем
schemas = registry.list_schemas()  # ['LoggerManager', 'DatabaseManager', ...]
```

### 2. ModelFactory - Фабрика моделей

Упрощает создание моделей менеджеров с автоматическим заполнением обязательных полей.

```python
from multiprocess_framework.refactored.modules.data_schema_module import ModelFactory

# Создание модели менеджера
model = ModelFactory.create_manager(
    "LoggerManager",
    "main_logger",
    data={"log_level": "DEBUG"},
    auto_register=True,
    process_name="VisionProcess"
)

# Создание из словаря
data = {
    "component_class": "LoggerManager",
    "name": "main_logger",
    "log_level": "DEBUG"
}
model = ModelFactory.from_dict(data)

# С указанием схемы
model = ModelFactory.from_dict(
    {"name": "main_logger", "log_level": "DEBUG"},
    schema_name="LoggerManager"
)
```

### 3. StorageManager - Хранение данных в ProcessData

Управляет данными компонентов в ProcessData (запись/чтение менеджеров).

```python
from multiprocess_framework.refactored.modules.data_schema_module import StorageManager

storage = StorageManager.get_instance(shared_resources=your_shared_resources)

# Регистрация менеджера
storage.register_manager(manager_model, process_name="VisionProcess")

# Получение модели менеджера
model = data_manager.get_manager_model(
    manager_name="main_logger",
    manager_type="LoggerManager",
    process_name="VisionProcess"
)

# Обновление модели
model.log_level = "ERROR"
data_manager.update_manager_model(model, process_name="VisionProcess")

# Получение конфигурации
log_level = data_manager.get_manager_config(
    manager_type="LoggerManager",
    manager_name="main_logger",
    key="log_level",
    default="INFO",
    process_name="VisionProcess"
)

# Список менеджеров
managers = data_manager.list_managers(
    process_name="VisionProcess",
    manager_type="LoggerManager"
)
```

### 4. VersionManager - Версионирование

Управляет версиями конфигураций менеджеров.

```python
from multiprocess_framework.refactored.modules.data_schema_module import VersionManager, StorageManager

storage = StorageManager.get_instance(shared_resources)  # shared_resources — из окружения процесса
version_manager = VersionManager(storage)

# Создание версии
version_id = version_manager.create_version(
    manager_model=manager_model,
    comment="Обновление уровня логирования",
    author="admin",
    tags=["production", "logging"],
    process_name="VisionProcess"
)

# Получение текущей версии
current_version = version_manager.get_current_version(
    manager_type="LoggerManager",
    manager_name="main_logger",
    process_name="VisionProcess"
)

# Получение конкретной версии
old_model = version_manager.get_version(
    manager_type="LoggerManager",
    manager_name="main_logger",
    version=1,
    process_name="VisionProcess"
)

# Откат к предыдущей версии
version_manager.rollback(
    manager_type="LoggerManager",
    manager_name="main_logger",
    target_version=1,
    process_name="VisionProcess",
    create_new_version=True,
    comment="Откат к стабильной версии"
)

# История версий
history = version_manager.get_version_history(
    manager_type="LoggerManager",
    manager_name="main_logger",
    process_name="VisionProcess"
)
# [
#     {
#         "version": 1,
#         "created_at": 1234567890.0,
#         "comment": "Первая версия",
#         "author": "admin"
#     },
#     ...
# ]

# Сравнение версий
diff = version_manager.compare_versions(
    manager_type="LoggerManager",
    manager_name="main_logger",
    version1=1,
    version2=2,
    process_name="VisionProcess"
)
```

### 5. DataConverter - Конвертация форматов

Конвертирует данные между различными форматами.

```python
from multiprocess_framework.refactored.modules.data_schema_module import (
    DataConverter,
    FormatType
)

# Pydantic Model -> Dict
model = LoggerManagerModel(log_level="DEBUG")
data_dict = DataConverter.model_to_dict(model)

# Dict -> Pydantic Model
model = DataConverter.dict_to_model(data_dict, LoggerManagerModel)

# Model -> JSON
json_str = DataConverter.model_to_json(model)

# JSON -> Model
model = DataConverter.json_to_model(json_str, LoggerManagerModel)

# Model -> YAML
yaml_str = DataConverter.model_to_yaml(model)

# YAML -> Model
model = DataConverter.yaml_to_model(yaml_str, LoggerManagerModel)

# Универсальная конвертация
json_str = DataConverter.convert(
    model,
    FormatType.MODEL,
    FormatType.JSON
)

model = DataConverter.convert(
    json_str,
    FormatType.JSON,
    FormatType.MODEL,
    model_class=LoggerManagerModel
)

# Работа с файлами
from pathlib import Path

# Сохранение
DataConverter.save_to_file(
    model,
    Path("config.yaml"),
    format_type=FormatType.YAML
)

# Загрузка
model = DataConverter.load_from_file(
    Path("config.yaml"),
    model_class=LoggerManagerModel
)
```

### 6. DataValidator - Валидация данных

Валидирует данные по Pydantic моделям.

```python
from multiprocess_framework.refactored.modules.data_schema_module import DataValidator

# Базовая валидация
is_valid, instance, error = DataValidator.validate(
    {"log_level": "DEBUG", "file_path": "logs/app.log"},
    LoggerManagerModel
)

if is_valid:
    print(f"Валидация успешна: {instance.log_level}")
else:
    print(f"Ошибка валидации: {error}")

# Проверка валидности без создания экземпляра
if DataValidator.is_valid(data, LoggerManagerModel):
    print("Данные валидны")

# Получение ошибок валидации
errors = DataValidator.get_validation_errors(
    {"log_level": "INVALID"},
    LoggerManagerModel
)
# [
#     {
#         "loc": ("log_level",),
#         "msg": "log_level должен быть одним из ['DEBUG', 'INFO', ...]",
#         "type": "value_error"
#     }
# ]

# Частичная валидация (заполняет дефолтами отсутствующие поля)
is_valid, partial_instance, error = DataValidator.validate_partial(
    {"log_level": "DEBUG"},
    LoggerManagerModel
)
# partial_instance.file_path будет иметь дефолтное значение

# Валидация вложенных структур
is_valid, nested_instance, error = DataValidator.validate_nested(
    {"config": {"log_level": "DEBUG"}},
    LoggerManagerModel,
    nested_path="config"
)
```

---

## Примеры использования

### Пример 1: Создание менеджера с конфигурацией

```python
from multiprocess_framework.refactored.modules.data_schema_module import (
    BaseManagerModel,
    ModelFactory,
    ComponentType
)
from pydantic import Field

# Определение модели
class DatabaseManagerModel(BaseManagerModel):
    host: str = Field(default="localhost")
    port: int = Field(default=5432)
    database: str = Field(default="mydb")
    username: str = Field(default="user")
    password: str = Field(default="")
    pool_size: int = Field(default=10)

# Регистрация (в __init__.py модуля)
from multiprocess_framework.refactored.modules.data_schema_module import register_schema

@register_schema("DatabaseManager")
class DatabaseManagerModel(BaseManagerModel):
    # ... поля

# Использование
manager_model = ModelFactory.create_manager(
    "DatabaseManager",
    "main_db",
    data={
        "host": "192.168.1.100",
        "port": 5432,
        "database": "production_db",
        "username": "admin",
        "password": "secret",
        "pool_size": 20
    },
    auto_register=True,
    process_name="DBProcess"
)

# Доступ к данным
print(f"Подключение к {manager_model.host}:{manager_model.port}")
```

### Пример 2: Работа с версиями

```python
from multiprocess_framework.refactored.modules.data_schema_module import VersionManager, StorageManager

storage = StorageManager.get_instance(shared_resources)
version_manager = VersionManager(storage)

# Создание начальной версии
version_1 = version_manager.create_version(
    manager_model=manager_model,
    comment="Начальная конфигурация",
    author="admin",
    process_name="DBProcess"
)

# Обновление конфигурации
manager_model.pool_size = 30
manager_model.host = "192.168.1.200"
version_2 = version_manager.create_version(
    manager_model=manager_model,
    comment="Увеличен pool_size, изменен host",
    author="admin",
    process_name="DBProcess"
)

# Откат к версии 1
version_manager.rollback(
    manager_type="DatabaseManager",
    manager_name="main_db",
    target_version=1,
    process_name="DBProcess",
    create_new_version=True,
    comment="Откат к стабильной конфигурации"
)

# Просмотр истории
history = version_manager.get_version_history(
    manager_type="DatabaseManager",
    manager_name="main_db",
    process_name="DBProcess"
)

for version_info in history:
    print(f"Версия {version_info['version']}: {version_info['comment']}")
```

### Пример 3: Загрузка конфигурации из файла

```python
from pathlib import Path
from multiprocess_framework.refactored.modules.data_schema_module import (
    DataConverter,
    FormatType,
    ModelFactory
)

# Загрузка из YAML файла
config_path = Path("configs/database.yaml")
model = DataConverter.load_from_file(
    config_path,
    model_class=DatabaseManagerModel
)

# Создание менеджера из загруженной конфигурации
manager_model = ModelFactory.from_dict(
    model.model_dump(),
    schema_name="DatabaseManager"
)

# Сохранение текущей конфигурации
DataConverter.save_to_file(
    manager_model,
    Path("configs/database_backup.yaml"),
    format_type=FormatType.YAML
)
```

### Пример 4: Валидация пользовательского ввода

```python
from multiprocess_framework.refactored.modules.data_schema_module import DataValidator

def update_logger_config(user_input: dict):
    """Обновить конфигурацию логгера с валидацией."""
    
    # Валидация данных
    is_valid, instance, error = DataValidator.validate(
        user_input,
        LoggerManagerModel
    )
    
    if not is_valid:
        return {
            "success": False,
            "error": error,
            "errors": DataValidator.get_validation_errors(user_input, LoggerManagerModel)
        }
    
    # Данные валидны, обновляем модель
    manager_model.log_level = instance.log_level
    manager_model.file_path = instance.file_path
    # ... обновление других полей
    
    return {
        "success": True,
        "model": manager_model
    }

# Использование
result = update_logger_config({
    "log_level": "DEBUG",
    "file_path": "logs/debug.log"
})

if result["success"]:
    print("Конфигурация обновлена")
else:
    print(f"Ошибка: {result['error']}")
```

---

## Лучшие практики

### 1. Используйте декоратор для регистрации схем

```python
# ✅ Хорошо
@register_schema("MyManager")
class MyManagerModel(BaseManagerModel):
    pass

# ❌ Плохо
class MyManagerModel(BaseManagerModel):
    pass

registry = SchemaManager.get_instance()
registry.register("MyManager", MyManagerModel)
```

### 2. Всегда указывайте дефолтные значения

```python
# ✅ Хорошо
class MyModel(BaseManagerModel):
    timeout: int = Field(default=30)
    retries: int = Field(default=3)

# ❌ Плохо
class MyModel(BaseManagerModel):
    timeout: int  # Обязательное поле без дефолта
```

### 3. Используйте валидаторы для проверки данных

```python
# ✅ Хорошо
class MyModel(BaseManagerModel):
    port: int = Field(default=8080)
    
    @field_validator('port')
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError("Порт должен быть в диапазоне 1-65535")
        return v
```

### 4. Создавайте версии при важных изменениях

```python
# ✅ Хорошо
manager_model.config["new_feature"] = True
version_manager.create_version(
    manager_model,
    comment="Добавлена новая функция",
    process_name="MyProcess"
)
```

### 5. Используйте ModelFactory для создания моделей

```python
# ✅ Хорошо
model = ModelFactory.create_manager(
    "MyManager",
    "my_instance",
    data={"field": "value"},
    auto_register=True
)

# ❌ Плохо
registry = SchemaManager.get_instance()
model = registry.create_instance("MyManager", {
    "component_class": "MyManager",
    "name": "my_instance",
    "component_type": ComponentType.MANAGER,
    "field": "value"
})
```

---

## API Reference

### SchemaManager

**Методы:**
- `register(schema_name: str, schema_class: Type[BaseModel]) -> bool` - Зарегистрировать схему
- `get_schema(schema_name: str) -> Optional[Type[BaseModel]]` - Получить схему
- `has_schema(schema_name: str) -> bool` - Проверить наличие схемы
- `create_instance(schema_name: str, data: Optional[Dict] = None, **kwargs) -> BaseModel` - Создать экземпляр
- `get_defaults(schema_name: str) -> Dict[str, Any]` - Получить дефолтные значения
- `validate(schema_name: str, data: Dict[str, Any]) -> Tuple[bool, Optional[BaseModel], Optional[str]]` - Валидировать данные
- `list_schemas() -> List[str]` - Список всех схем
- `unregister(schema_name: str) -> bool` - Удалить схему
- `clear()` - Очистить все схемы

### ModelFactory

**Методы:**
- `create_manager(manager_class: str, manager_name: str, data: Optional[Dict] = None, auto_register: bool = False, process_name: Optional[str] = None, shared_resources: Optional[Any] = None) -> BaseManagerModel` - Создать модель менеджера
- `from_dict(data: Dict[str, Any], schema_name: Optional[str] = None) -> BaseManagerModel` - Создать модель из словаря
- `create(schema_name: str, data: Dict[str, Any]) -> BaseManagerModel` - Создать экземпляр по имени схемы и данным

### StorageManager

**Методы:** (экземпляр через `get_instance(shared_resources)`)
- `register_manager(manager_model: BaseManagerModel, process_name: Optional[str] = None) -> bool` - Зарегистрировать менеджера
- `get_manager_model(manager_name: str, manager_type: str, process_name: Optional[str] = None) -> Optional[BaseManagerModel]` - Получить модель менеджера
- `update_manager_model(manager_model: BaseManagerModel, process_name: Optional[str] = None) -> bool` - Обновить модель
- `get_manager_config(manager_type: str, manager_name: str, key: str, default: Any = None, process_name: Optional[str] = None) -> Any` - Получить конфигурацию
- `update_manager_config(manager_type: str, manager_name: str, key: str, value: Any, process_name: Optional[str] = None) -> bool` - Обновить конфигурацию
- `remove_manager(manager_name: str, manager_type: Optional[str] = None, process_name: Optional[str] = None) -> bool` - Удалить менеджера
- `list_managers(process_name: Optional[str] = None, manager_type: Optional[str] = None) -> List[str]` - Список менеджеров

### VersionManager

**Методы:**
- `create_version(manager_model: BaseManagerModel, comment: Optional[str] = None, author: Optional[str] = None, tags: Optional[List[str]] = None, process_name: Optional[str] = None) -> int` - Создать версию
- `get_current_version(manager_type: str, manager_name: str, process_name: Optional[str] = None) -> int` - Получить текущую версию
- `get_version(manager_type: str, manager_name: str, version: int, process_name: Optional[str] = None) -> Optional[BaseManagerModel]` - Получить версию
- `rollback(manager_type: str, manager_name: str, target_version: int, process_name: Optional[str] = None, create_new_version: bool = True, comment: Optional[str] = None) -> bool` - Откатить версию
- `get_version_history(manager_type: str, manager_name: str, process_name: Optional[str] = None) -> List[Dict[str, Any]]` - История версий
- `compare_versions(manager_type: str, manager_name: str, version1: int, version2: int, process_name: Optional[str] = None) -> Dict[str, Any]` - Сравнить версии

### DataConverter

**Методы:**
- `model_to_dict(model: BaseModel, **kwargs) -> Dict[str, Any]` - Модель в словарь
- `dict_to_model(data: Dict[str, Any], model_class: Type[BaseModel], **kwargs) -> BaseModel` - Словарь в модель
- `model_to_json(model: BaseModel, **kwargs) -> str` - Модель в JSON
- `json_to_model(json_str: str, model_class: Type[BaseModel], **kwargs) -> BaseModel` - JSON в модель
- `model_to_yaml(model: BaseModel, **kwargs) -> str` - Модель в YAML
- `yaml_to_model(yaml_str: str, model_class: Type[BaseModel], **kwargs) -> BaseModel` - YAML в модель
- `convert(data: Any, from_format: FormatType, to_format: FormatType, **kwargs) -> Any` - Универсальная конвертация
- `save_to_file(model: BaseModel, file_path: Path, format_type: FormatType = FormatType.JSON)` - Сохранить в файл
- `load_from_file(file_path: Path, model_class: Type[BaseModel], **kwargs) -> BaseModel` - Загрузить из файла

### DataValidator

**Методы:**
- `validate(data: Dict[str, Any], model_class: Type[BaseModel], strict: bool = False) -> Tuple[bool, Optional[BaseModel], Optional[str]]` - Валидировать данные
- `is_valid(data: Dict[str, Any], model_class: Type[BaseModel], strict: bool = False) -> bool` - Проверить валидность
- `get_validation_errors(data: Dict[str, Any], model_class: Type[BaseModel], strict: bool = False) -> List[Dict[str, Any]]` - Получить ошибки
- `validate_partial(data: Dict[str, Any], model_class: Type[BaseModel], strict: bool = False) -> Tuple[bool, Optional[BaseModel], Optional[str]]` - Частичная валидация
- `validate_nested(data: Dict[str, Any], model_class: Type[BaseModel], nested_path: str, strict: bool = False) -> Tuple[bool, Optional[BaseModel], Optional[str]]` - Валидация вложенных структур

---

## Обработка ошибок

### Типичные ошибки и их решение

**1. Схема не найдена**
```python
from multiprocess_framework.refactored.modules.data_schema_module import SchemaNotFoundError

try:
    model = ModelFactory.from_dict(data, schema_name="NonExistent")
except SchemaNotFoundError as e:
    print(f"Схема не найдена: {e.schema_name}")
    # Зарегистрируйте схему перед использованием
```

**2. Ошибка валидации**
```python
is_valid, instance, error = DataValidator.validate(data, MyModel)
if not is_valid:
    errors = DataValidator.get_validation_errors(data, MyModel)
    for err in errors:
        print(f"Поле {err['loc']}: {err['msg']}")
```

**3. Отсутствие обязательных полей**
```python
# Используйте ModelFactory — он автоматически добавит обязательные поля
model = ModelFactory.create_manager(
    "MyManager",
    "my_instance",
    data={"custom_field": "value"}
)
```

---

## Заключение

Модуль `data_schema` предоставляет мощный и гибкий инструментарий для работы с данными компонентов системы. Используйте его для:

- ✅ Валидации конфигураций
- ✅ Управления версиями
- ✅ Конвертации форматов
- ✅ Работы с дефолтными значениями
- ✅ Упрощения работы с данными в многопроцессных приложениях

Для дополнительной информации см. исходный код модуля и тесты в `tests/test_data_schema_module/`.

