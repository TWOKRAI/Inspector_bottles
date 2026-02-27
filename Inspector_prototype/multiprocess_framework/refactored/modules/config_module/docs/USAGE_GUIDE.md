# Руководство пользователя ConfigModule

Подробное руководство по использованию модуля управления конфигурациями.

## Содержание

1. [Базовое использование](#базовое-использование)
2. [Работа с ConfigManager](#работа-с-configmanager)
3. [Валидация через Pydantic](#валидация-через-pydantic)
4. [Работа с файлами](#работа-с-файлами)
5. [Работа с секциями](#работа-с-секциями)
6. [Межпроцессное хранение](#межпроцессное-хранение)
7. [Синхронизация](#синхронизация)
8. [Подписка на изменения](#подписка-на-изменения)

## Базовое использование

### Создание конфигурации

```python
from multiprocess_framework.refactored.modules.config_module import Config

# Пустая конфигурация
config = Config()

# С начальными данными
config = Config(initial_data={
    'database': {
        'host': 'localhost',
        'port': 5432
    }
})
```

### Установка и получение значений

```python
# Установка значений
config.set('database.host', 'localhost')
config.set('database.port', 5432)

# Получение значений
host = config.get('database.host')  # 'localhost'
port = config.get('database.port', 5432)  # 5432 или значение по умолчанию

# Синтаксис словаря
config['database.host'] = 'localhost'
host = config['database.host']
```

### Проверка наличия ключей

```python
if config.has('database.host'):
    print("Database host configured")

# Через оператор 'in'
if 'database.host' in config:
    print("Database host configured")
```

### Удаление ключей

```python
config.remove('database.port')
# или
del config['database.port']
```

## Работа с ConfigManager

### Создание ConfigManager

```python
from multiprocess_framework.refactored.modules.config_module import ConfigManager
from multiprocess_framework.refactored.modules.shared_resources_module import SharedResourcesManager

# Создание с интеграцией
shared_resources = SharedResourcesManager()
config_manager = ConfigManager(
    manager_name="MyConfigManager",
    shared_resources=shared_resources,
    auto_sync=True  # Автоматическая синхронизация
)

# Инициализация
config_manager.initialize()
```

### Создание конфигураций

```python
# Простое создание
app_config = config_manager.create_config(
    name='app',
    initial_data={'name': 'MyApp', 'version': '1.0.0'}
)

# С файлом
db_config = config_manager.create_config(
    name='database',
    file_path='config/database.yaml'
)

# С валидацией
from pydantic import BaseModel

class AppConfig(BaseModel):
    name: str
    version: str = "1.0.0"

app_config = config_manager.create_config(
    name='app',
    validation_schema=AppConfig,
    validate_on_set=True
)
```

### Получение конфигураций

```python
# Получение конфигурации
app_config = config_manager.get_config('app')

# Список всех конфигураций
configs = config_manager.list_configs()  # ['app', 'database']

# Все конфигурации
all_configs = config_manager.get_all_configs()
```

### Удаление конфигураций

```python
config_manager.remove_config('app')
```

## Валидация через Pydantic

### Определение схемы

```python
from pydantic import BaseModel

class DatabaseConfig(BaseModel):
    host: str = "localhost"
    port: int = 5432
    name: str
    user: str = "admin"
    password: str
```

### Создание конфигурации с валидацией

```python
# С валидацией при установке
config = Config(
    validation_schema=DatabaseConfig,
    validate_on_set=True
)

# Установка значений (валидация происходит автоматически)
config.set('host', 'localhost')
config.set('port', 5432)
config.set('name', 'mydb')
config.set('user', 'admin')
config.set('password', 'secret')
```

### Конвертация в Pydantic модель

```python
# Конвертация конфигурации в модель
model = config.to_model(DatabaseConfig)
print(model.host)  # 'localhost'
print(model.port)  # 5432
```

### Загрузка из Pydantic модели

```python
# Создание модели
model = DatabaseConfig(
    host='localhost',
    port=5432,
    name='mydb',
    password='secret'
)

# Загрузка в конфигурацию
config = Config()
config.from_model(model)

# Использование
host = config.get('host')  # 'localhost'
```

## Работа с файлами

### Загрузка из файла

```python
# Загрузка JSON
config.load('config/app.json')

# Загрузка YAML
config.load('config/app.yaml')

# Загрузка с заменой существующих данных
config.load('config/app.yaml', merge=False)

# Загрузка с объединением (по умолчанию)
config.load('config/app.yaml', merge=True)
```

### Сохранение в файл

```python
# Сохранение в тот же файл
config.load('config/app.yaml')
config.set('key', 'value')
config.save()

# Сохранение в другой файл
config.save('config/backup.yaml')
```

### Перезагрузка

```python
config.load('config/app.yaml')
# ... изменения в файле извне ...
config.reload()  # Загружает изменения из файла
```

## Работа с секциями

### Получение секции

```python
# Получение секции database
db_config = config.section('database')
```

### Работа с секцией

```python
# Установка значений
db_config.set('host', 'localhost')
db_config.set('port', 5432)

# Получение значений
host = db_config.get('host')

# Все изменения отражаются в основном конфиге
assert config.get('database.host') == 'localhost'
```

### Обновление секции

```python
db_config.update({
    'host': 'localhost',
    'port': 5432,
    'name': 'mydb'
})
```

## Межпроцессное хранение

### Сохранение в ProcessData

```python
# Автоматическое сохранение при создании (если auto_sync=True)
config_manager.create_config(name='app', initial_data={'key': 'value'})

# Ручное сохранение
config_manager.sync_config('app')

# Сохранение в конкретный процесс
config_manager.sync_config('app', process_name='MyProcess')
```

### Загрузка из ProcessData

```python
# Загрузка конфигурации
config_manager.load_config_from_storage('app')

# Загрузка из конкретного процесса
config_manager.load_config_from_storage('app', process_name='MyProcess')
```

## Синхронизация

### Автоматическая синхронизация

```python
# Включение автоматической синхронизации при создании ConfigManager
config_manager = ConfigManager(auto_sync=True)

# Включение для конкретной конфигурации
config_manager.set_auto_sync('app', True)
```

### Ручная синхронизация

```python
# Синхронизация конфигурации
config_manager.sync_config('app')

# Синхронизация в конкретный процесс
config_manager.sync_config('app', process_name='MyProcess')
```

## Подписка на изменения

### Подписка на все изменения

```python
def on_change(key, old_value, new_value):
    print(f"Config changed: {key} = {new_value}")

config.subscribe(on_change)
```

### Подписка на конкретный ключ

```python
@config.subscribe(key='database.host')
def on_db_host_change(key, old_value, new_value):
    print(f"Database host changed: {old_value} -> {new_value}")
```

### Использование как декоратор

```python
@config.subscribe()
def on_any_change(key, old_value, new_value):
    print(f"Config changed: {key}")
```

### Отписка

```python
config.unsubscribe(on_change)
```

## Примеры использования

### Пример 1: Конфигурация приложения

```python
from multiprocess_framework.refactored.modules.config_module import ConfigManager

config_manager = ConfigManager()
config_manager.initialize()

# Создание конфигурации приложения
app_config = config_manager.create_config(
    name='app',
    initial_data={
        'name': 'MyApp',
        'version': '1.0.0',
        'debug': True
    }
)

# Использование
app_name = app_config.get('name')
app_version = app_config.get('version')
```

### Пример 2: Конфигурация базы данных с валидацией

```python
from pydantic import BaseModel
from multiprocess_framework.refactored.modules.config_module import ConfigManager

class DatabaseConfig(BaseModel):
    host: str
    port: int = 5432
    name: str
    user: str
    password: str

config_manager = ConfigManager()
config_manager.initialize()

db_config = config_manager.create_config(
    name='database',
    validation_schema=DatabaseConfig,
    validate_on_set=True
)

db_config.set('host', 'localhost')
db_config.set('port', 5432)
db_config.set('name', 'mydb')
db_config.set('user', 'admin')
db_config.set('password', 'secret')
```

### Пример 3: Межпроцессная синхронизация

```python
from multiprocess_framework.refactored.modules.config_module import ConfigManager
from multiprocess_framework.refactored.modules.shared_resources_module import SharedResourcesManager

shared_resources = SharedResourcesManager()
config_manager = ConfigManager(
    shared_resources=shared_resources,
    auto_sync=True
)
config_manager.initialize()

# Создание конфигурации (автоматически сохраняется в ProcessData)
app_config = config_manager.create_config(
    name='app',
    initial_data={'key': 'value'}
)

# Изменение конфигурации (автоматически синхронизируется)
app_config.set('key', 'new_value')

# Ручная синхронизация
config_manager.sync_config('app')
```

