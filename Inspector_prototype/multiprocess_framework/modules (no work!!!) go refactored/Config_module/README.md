# Модуль конфигурации (Config_module)

Универсальный модуль для работы с конфигурацией во всех модулях проекта. Предоставляет простой, мощный и потокобезопасный API для управления конфигурацией.

> 📋 **Оценка модуля**: ⭐⭐⭐⭐⭐ (5/5) - Отличное качество кода, продуманная архитектура и широкий функционал.  
> Подробный обзор: [CONFIG_MODULE_REVIEW.md](../../docs/CONFIG_MODULE_REVIEW.md)

## Статус

- ✅ **Готов к использованию**: Модуль полностью протестирован и готов к продакшену
- ✅ **Покрытие тестами**: Все основные функции покрыты тестами (pytest)
- ✅ **Документация**: Полная документация с примерами использования
- ✅ **Потокобезопасность**: Все операции защищены блокировками

## Особенности

- ✅ **Вложенные ключи через точку**: `config.get('database.host')`
- ✅ **Потокобезопасность**: Все операции защищены блокировками (RLock)
- ✅ **Поддержка форматов**: JSON и YAML файлы
- ✅ **Работа с секциями**: Удобный доступ к частям конфигурации
- ✅ **Переменные окружения**: Автоматическая поддержка переменных окружения
- ✅ **Подписка на изменения**: Callback-функции для отслеживания изменений
- ✅ **Singleton паттерн**: Глобальный доступ через ConfigManager
- ✅ **Простой API**: Интуитивно понятный интерфейс
- ✅ **Автоматическое определение класса**: Определение класса конфига из метаданных файла
- ✅ **Дефолтные и временные файлы**: Поддержка приоритетов загрузки (temp > default)
- ✅ **Массовая загрузка**: Загрузка всех конфигов из директории одной командой

## Установка

Модуль использует следующие зависимости:
- `PyYAML` - для работы с YAML файлами (опционально, но рекомендуется)

```bash
pip install PyYAML
```

## Быстрый старт

### Базовое использование

```python
from src.Modules.Config_module import Config

# Создание конфигурации
config = Config()

# Установка значений
config.set('database.host', 'localhost')
config.set('database.port', 5432)
config.set('database.name', 'mydb')

# Получение значений
host = config.get('database.host')  # 'localhost'
port = config.get('database.port', 5432)  # 5432 или значение по умолчанию

# Работа через синтаксис словаря
config['database.user'] = 'admin'
user = config['database.user']

# Проверка наличия ключа
if 'database.host' in config:
    print("Database host configured")

# Удаление ключа
del config['database.port']
```

### Работа с файлами

```python
from src.Modules.Config_module import Config

# Загрузка из файла
config = Config()
config.load('config/app.yaml')

# Сохранение в файл
config.save('config/app.yaml')

# Перезагрузка из файла
config.reload()

# Загрузка с автоматическим созданием
config = Config(file_path='config/app.yaml')
```

### Работа с секциями

```python
from src.Modules.Config_module import Config

config = Config()

# Получение секции
db_config = config.section('database')

# Работа с секцией как с отдельным конфигом
db_config.set('host', 'localhost')
db_config.set('port', 5432)
host = db_config.get('host')

# Все изменения отражаются в основном конфиге
assert config.get('database.host') == 'localhost'

# Массовое обновление секции
db_config.update({
    'host': 'localhost',
    'port': 5432,
    'name': 'mydb'
})
```

### Использование ConfigManager (Singleton)

```python
from src.Modules.Config_module import ConfigManager, get_config

# Получение глобального экземпляра
config = ConfigManager.get_instance()
config.set('app.name', 'MyApp')

# Создание именованной конфигурации
app_config = ConfigManager.get_instance('app')
app_config.load('config/app.yaml')

db_config = ConfigManager.get_instance('database')
db_config.load('config/database.yaml')

# Удобная функция
config = get_config('app')

# Список всех конфигураций
names = ConfigManager.list_instances()  # ['default', 'app', 'database']
```

### Переменные окружения

```python
from src.Modules.Config_module import Config

# Создание конфигурации с префиксом для переменных окружения
config = Config(env_prefix='APP')

# Если APP_DATABASE_HOST установлена в окружении, она будет использована
host = config.get('database.host', env_fallback=True)

# Пример переменных окружения:
# APP_DATABASE_HOST=localhost
# APP_DATABASE_PORT=5432
```

### Подписка на изменения

```python
from src.Modules.Config_module import Config

config = Config()

# Использование как декоратор
@config.subscribe(key='database.host')
def on_db_host_change(key, old_value, new_value):
    print(f"Database host changed: {old_value} -> {new_value}")

# Прямой вызов
def on_any_change(key, old_value, new_value):
    print(f"Config changed: {key}")

config.subscribe(on_any_change)  # Подписка на все изменения

# Изменение значения вызовет callback
config.set('database.host', 'newhost')
```

## API Справка

### Класс Config

#### Методы

##### `get(key: str, default: Any = None, env_fallback: bool = True) -> Any`
Получить значение по ключу.

**Параметры:**
- `key`: Ключ в формате 'section.subsection.key'
- `default`: Значение по умолчанию
- `env_fallback`: Искать в переменных окружения

**Возвращает:** Значение конфигурации или default

##### `set(key: str, value: Any, notify: bool = True) -> Config`
Установить значение по ключу.

**Параметры:**
- `key`: Ключ в формате 'section.subsection.key'
- `value`: Значение для установки
- `notify`: Отправлять уведомления об изменении

**Возвращает:** self (для цепочки вызовов)

##### `update(data: Dict[str, Any], prefix: str = "") -> Config`
Обновить конфигурацию из словаря.

**Параметры:**
- `data`: Словарь с новыми значениями
- `prefix`: Префикс для ключей

**Возвращает:** self (для цепочки вызовов)

##### `has(key: str) -> bool`
Проверить наличие ключа в конфигурации.

**Параметры:**
- `key`: Ключ для проверки

**Возвращает:** True если ключ существует

##### `remove(key: str) -> bool`
Удалить ключ из конфигурации.

**Параметры:**
- `key`: Ключ для удаления

**Возвращает:** True если ключ был удален

##### `clear() -> Config`
Очистить всю конфигурацию.

**Возвращает:** self (для цепочки вызовов)

##### `load(file_path: Union[str, Path], merge: bool = True) -> Config`
Загрузить конфигурацию из файла.

**Параметры:**
- `file_path`: Путь к файлу конфигурации
- `merge`: Объединять с существующими данными или заменять

**Возвращает:** self (для цепочки вызовов)

**Исключения:**
- `FileNotFoundError`: Если файл не найден
- `ImportError`: Если требуется PyYAML но не установлен

##### `save(file_path: Optional[Union[str, Path]] = None) -> Config`
Сохранить конфигурацию в файл.

**Параметры:**
- `file_path`: Путь для сохранения (если None, использует путь загрузки)

**Возвращает:** self (для цепочки вызовов)

**Исключения:**
- `ValueError`: Если путь не указан

##### `reload() -> Config`
Перезагрузить конфигурацию из того же файла.

**Возвращает:** self (для цепочки вызовов)

**Исключения:**
- `ValueError`: Если конфигурация не была загружена из файла

##### `section(section_key: str) -> ConfigSection`
Получить доступ к секции конфигурации.

**Параметры:**
- `section_key`: Ключ секции (например, 'database')

**Возвращает:** ConfigSection - объект для работы с секцией

##### `subscribe(callback: Optional[Callable] = None, key: str = "*") -> Union[None, Callable]`
Подписаться на изменения конфигурации.

**Параметры:**
- `callback`: Функция обратного вызова (key, old_value, new_value) или None для использования как декоратор
- `key`: Ключ для отслеживания или "*" для всех изменений (по умолчанию "*")

**Возвращает:** Декоратор если callback не указан, иначе None

#### Свойства

##### `data: Dict[str, Any]`
Получить копию всех данных конфигурации.

##### `file_path: Optional[Path]`
Получить путь к файлу конфигурации.

#### Магические методы

- `config[key]` - получить значение (аналог `get()`)
- `config[key] = value` - установить значение (аналог `set()`)
- `key in config` - проверить наличие ключа (аналог `has()`)
- `del config[key]` - удалить ключ (аналог `remove()`)
- `len(config)` - количество ключей верхнего уровня
- `repr(config)` - строковое представление

### Класс ConfigSection

Представление секции конфигурации. Предоставляет те же методы что и `Config`, но работает только с указанной секцией.

#### Методы

- `get(key: str, default: Any = None) -> Any`
- `set(key: str, value: Any) -> ConfigSection`
- `update(data: Dict[str, Any]) -> ConfigSection`
- `has(key: str) -> bool`
- `remove(key: str) -> bool`

#### Свойства

- `data: Dict[str, Any]` - все данные секции как словарь

### Класс ConfigManager

Менеджер для управления несколькими экземплярами конфигураций.

#### Методы класса

##### `get_instance(name: str = "default", env_prefix: Optional[str] = None, file_path: Optional[Union[str, Path]] = None) -> Config`
Получить или создать экземпляр конфигурации (Singleton).

**Параметры:**
- `name`: Уникальное имя конфигурации
- `env_prefix`: Префикс для переменных окружения
- `file_path`: Путь к файлу конфигурации

**Возвращает:** Экземпляр Config

##### `create_instance(name: str, env_prefix: Optional[str] = None, file_path: Optional[Union[str, Path]] = None, initial_data: Optional[Dict] = None) -> Config`
Создать новый экземпляр конфигурации.

**Параметры:**
- `name`: Уникальное имя конфигурации
- `env_prefix`: Префикс для переменных окружения
- `file_path`: Путь к файлу конфигурации
- `initial_data`: Начальные данные конфигурации

**Возвращает:** Новый экземпляр Config

##### `remove_instance(name: str) -> bool`
Удалить экземпляр конфигурации.

**Параметры:**
- `name`: Имя конфигурации для удаления

**Возвращает:** True если конфигурация была удалена

##### `clear_all() -> None`
Очистить все экземпляры конфигураций.

##### `has_instance(name: str) -> bool`
Проверить существование экземпляра конфигурации.

**Параметры:**
- `name`: Имя конфигурации

**Возвращает:** True если конфигурация существует

##### `list_instances() -> list`
Получить список всех именованных конфигураций.

**Возвращает:** Список имен конфигураций

##### `get_all_instances() -> Dict[str, Config]`
Получить словарь всех экземпляров конфигураций.

**Возвращает:** Словарь {имя: экземпляр Config}

##### `load_config(name: str, default_path: Optional[Union[str, Path]] = None, temp_path: Optional[Union[str, Path]] = None, config_class: Optional[Union[str, Type]] = None, env_prefix: Optional[str] = None) -> Config`
Загрузить конфигурацию с поддержкой дефолтных и временных файлов.

**Параметры:**
- `name`: Имя конфигурации
- `default_path`: Путь к дефолтному файлу конфигурации
- `temp_path`: Путь к временному файлу конфигурации (имеет приоритет над default_path)
- `config_class`: Класс конфига (строка вида 'module.Class' или класс). Если не указан, автоматически определяется из метаданных файла (`_meta.config_class` или `config_class`)
- `env_prefix`: Префикс для переменных окружения

**Возвращает:** Экземпляр Config (или указанного класса)

**Приоритет загрузки:**
1. Временный файл (если существует)
2. Дефолтный файл (если существует)
3. Пустая конфигурация

##### `load_all_configs(config_dir: Union[str, Path] = "config", temp_dir: Optional[Union[str, Path]] = None, config_mapping: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Config]`
Загрузить все конфиги из указанной директории.

**Параметры:**
- `config_dir`: Директория с дефолтными конфигами
- `temp_dir`: Директория с временными конфигами (опционально)
- `config_mapping`: Маппинг конфигов {name: {default_path, temp_path, config_class, env_prefix}}

**Возвращает:** Словарь загруженных конфигов

##### `reset_to_default(name: str) -> bool`
Сбросить конфигурацию к дефолтным значениям.

**Параметры:**
- `name`: Имя конфигурации

**Возвращает:** True если сброс выполнен успешно

##### `save_temp(name: str) -> bool`
Сохранить конфигурацию во временный файл.

**Параметры:**
- `name`: Имя конфигурации

**Возвращает:** True если сохранение выполнено успешно

##### `get_default_path(name: str) -> Optional[Path]`
Получить путь к дефолтному файлу конфигурации.

**Параметры:**
- `name`: Имя конфигурации

**Возвращает:** Путь к файлу или None

##### `get_temp_path(name: str) -> Optional[Path]`
Получить путь к временному файлу конфигурации.

**Параметры:**
- `name`: Имя конфигурации

**Возвращает:** Путь к файлу или None

##### `load_file_as_dict(file_path: Union[str, Path], output_format: str = 'dict') -> Union[Dict[str, Any], str]`
Загрузить файл конфигурации и вернуть данные в указанном формате.

**Параметры:**
- `file_path`: Путь к файлу конфигурации
- `output_format`: Формат вывода ('dict', 'yaml', 'json')

**Возвращает:** Данные конфигурации в указанном формате

## Примеры использования

### Пример 1: Базовая конфигурация приложения

```python
from src.Modules.Config_module import Config

# Создание и настройка конфигурации
config = Config()

# Настройка базы данных
config.set('database.host', 'localhost')
config.set('database.port', 5432)
config.set('database.name', 'myapp')
config.set('database.user', 'admin')
config.set('database.password', 'secret')

# Настройка API
config.set('api.host', '0.0.0.0')
config.set('api.port', 8000)
config.set('api.debug', True)

# Сохранение в файл
config.save('config/app.yaml')

# Использование
db_host = config.get('database.host')
api_port = config.get('api.port')
```

### Пример 2: Загрузка из файла

```yaml
# config/app.yaml
database:
  host: localhost
  port: 5432
  name: myapp
  user: admin
  password: secret

api:
  host: 0.0.0.0
  port: 8000
  debug: true

logging:
  level: INFO
  file: logs/app.log
```

```python
from src.Modules.Config_module import Config

# Загрузка конфигурации
config = Config()
config.load('config/app.yaml')

# Использование
db_config = config.section('database')
db_host = db_config.get('host')
db_port = db_config.get('port')
```

### Пример 3: Использование ConfigManager

```python
from src.Modules.Config_module import ConfigManager

# Создание нескольких конфигураций
app_config = ConfigManager.get_instance('app')
app_config.load('config/app.yaml')

db_config = ConfigManager.get_instance('database')
db_config.load('config/database.yaml')

api_config = ConfigManager.get_instance('api')
api_config.load('config/api.yaml')

# Использование
app_name = app_config.get('name')
db_host = db_config.get('host')
api_port = api_config.get('port')
```

### Пример 4: Подписка на изменения

```python
from src.Modules.Config_module import Config

config = Config()

# Подписка на изменения конкретного ключа
@config.subscribe(key='database.host')
def on_db_host_change(key, old_value, new_value):
    print(f"Database host changed from {old_value} to {new_value}")
    # Переподключение к базе данных
    reconnect_database(new_value)

# Подписка на все изменения
@config.subscribe()
def on_any_change(key, old_value, new_value):
    print(f"Config changed: {key} = {new_value}")

# Изменение значения вызовет callback
config.set('database.host', 'newhost')
```

### Пример 5: Переменные окружения

```bash
# Установка переменных окружения
export APP_DATABASE_HOST=localhost
export APP_DATABASE_PORT=5432
export APP_API_DEBUG=true
```

```python
from src.Modules.Config_module import Config

# Создание конфигурации с префиксом
config = Config(env_prefix='APP')

# Значения будут взяты из переменных окружения
db_host = config.get('database.host')  # 'localhost'
db_port = config.get('database.port')  # 5432
api_debug = config.get('api.debug')  # True
```

### Пример 6: Загрузка конфигурации с дефолтными и временными файлами

```python
from src.Modules.Config_module import ConfigManager

# Загрузка конфигурации с поддержкой дефолтных и временных файлов
config = ConfigManager.load_config(
    name='processes',
    default_path='config/processes.yaml',
    temp_path='config/temp/processes.yaml'
)

# Временный файл имеет приоритет над дефолтным
# Если temp файл существует, загрузится он, иначе - default

# Сброс к дефолтным значениям
ConfigManager.reset_to_default('processes')

# Сохранение текущей конфигурации во временный файл
ConfigManager.save_temp('processes')
```

### Пример 7: Автоматическое определение класса из метаданных

```python
from src.Modules.Config_module import ConfigManager

# В файле config/processes.yaml:
# _meta:
#   config_class: 'src.Modules.Process_manager_module.process_config.ProcessConfig'
# processes:
#   ...

# Класс автоматически определится из метаданных
config = ConfigManager.load_config(
    name='processes',
    default_path='config/processes.yaml'
)

# config будет экземпляром ProcessConfig, а не базового Config
```

### Пример 8: Загрузка всех конфигов из директории

```python
from src.Modules.Config_module import ConfigManager

# Автоматическая загрузка всех конфигов из директории
configs = ConfigManager.load_all_configs(
    config_dir='config',
    temp_dir='config/temp'
)

# configs будет словарем: {'app': Config, 'database': Config, ...}

# Использование
app_config = configs['app']
db_config = configs['database']
```

### Пример 9: Загрузка конфигов с маппингом

```python
from src.Modules.Config_module import ConfigManager

# Загрузка с указанием маппинга
configs = ConfigManager.load_all_configs(
    config_dir='config',
    config_mapping={
        'processes': {
            'default_path': 'config/processes.yaml',
            'temp_path': 'config/temp/processes.yaml',
            'config_class': 'src.Modules.Process_manager_module.process_config.ProcessConfig',
            'env_prefix': 'PROCESSES'
        },
        'app': {
            'default_path': 'config/app.yaml'
        }
    }
)
```

### Пример 10: Загрузка файла как словаря

```python
from src.Modules.Config_module import ConfigManager

# Загрузка файла как словарь Python
data = ConfigManager.load_file_as_dict('config/app.yaml')
# data - это dict

# Загрузка как YAML строка
yaml_str = ConfigManager.load_file_as_dict('config/app.yaml', output_format='yaml')

# Загрузка как JSON строка
json_str = ConfigManager.load_file_as_dict('config/app.json', output_format='json')
```

### Пример 11: Интеграция с другими модулями

```python
from src.Modules.Config_module import ConfigManager
from src.Modules.Logger_module import LoggerManager

# Получение конфигурации
config = ConfigManager.get_instance('app')
config.load('config/app.yaml')

# Использование в других модулях
logger_config = config.section('logging')
logger = LoggerManager(config=logger_config.data)

# Подписка на изменения конфигурации логирования
@config.subscribe(key='logging')
def on_logging_change(key, old_value, new_value):
    logger.reload_config(new_value)
```

## Форматы файлов

Модуль поддерживает два формата конфигурационных файлов: **JSON** и **YAML**. Формат определяется автоматически по расширению файла (`.json`, `.yaml`, `.yml`).

### JSON

JSON файлы идеально подходят для машинной обработки и автоматической генерации конфигураций.

**Пример конфигурации (config.json):**

```json
{
  "app": {
    "name": "MyApp",
    "version": "1.0.0",
    "debug": true
  },
  "database": {
    "host": "localhost",
    "port": 5432,
    "name": "myapp",
    "credentials": {
      "user": "admin",
      "password": "secret"
    }
  },
  "api": {
    "host": "0.0.0.0",
    "port": 8000,
    "endpoints": ["/api/v1", "/api/v2"]
  }
}
```

**Использование:**

```python
from src.Modules.Config_module import Config

# Загрузка из JSON файла
config = Config()
config.load('config/app.json')

# Доступ к значениям
app_name = config.get('app.name')  # 'MyApp'
db_host = config.get('database.host')  # 'localhost'
db_user = config.get('database.credentials.user')  # 'admin'
api_endpoints = config.get('api.endpoints')  # ['/api/v1', '/api/v2']
```

### YAML

YAML файлы более читаемы для человека и удобны для ручного редактирования конфигураций.

**Пример конфигурации (config.yaml):**

```yaml
app:
  name: MyApp
  version: 1.0.0
  debug: true

database:
  host: localhost
  port: 5432
  name: myapp
  credentials:
    user: admin
    password: secret

api:
  host: 0.0.0.0
  port: 8000
  endpoints:
    - /api/v1
    - /api/v2
```

**Использование:**

```python
from src.Modules.Config_module import Config

# Загрузка из YAML файла
config = Config()
config.load('config/app.yaml')

# Доступ к значениям
app_name = config.get('app.name')  # 'MyApp'
db_host = config.get('database.host')  # 'localhost'
api_endpoints = config.get('api.endpoints')  # ['/api/v1', '/api/v2']
```

### Чтение конфигураций из файлов

#### Базовое чтение

```python
from src.Modules.Config_module import Config

# Создание и загрузка конфигурации
config = Config()
config.load('config/app.json')  # или 'config/app.yaml'

# Использование значений
db_host = config.get('database.host')
api_port = config.get('api.port')
```

#### Автоматическая загрузка при создании

```python
from src.Modules.Config_module import Config

# Конфигурация автоматически загрузится из файла
config = Config(file_path='config/app.yaml')

# Значения сразу доступны
db_host = config.get('database.host')
```

#### Чтение через ConfigManager

```python
from src.Modules.Config_module import ConfigManager

# Создание именованной конфигурации с автоматической загрузкой
app_config = ConfigManager.get_instance('app', file_path='config/app.json')
db_config = ConfigManager.get_instance('database', file_path='config/database.yaml')

# Использование
app_name = app_config.get('app.name')
db_host = db_config.get('database.host')
```

#### Чтение нескольких конфигураций

```python
from src.Modules.Config_module import ConfigManager

# Загрузка нескольких конфигураций
app_config = ConfigManager.get_instance('app', file_path='config/app.json')
database_config = ConfigManager.get_instance('database', file_path='config/database.yaml')
api_config = ConfigManager.get_instance('api', file_path='config/api.yaml')

# Каждая конфигурация независима
app_name = app_config.get('app.name')
db_host = database_config.get('database.host')
api_port = api_config.get('api.port')
```

#### Работа с секциями после загрузки из файла

```python
from src.Modules.Config_module import Config

config = Config()
config.load('config/app.yaml')

# Получаем секцию database
db_section = config.section('database')

# Работаем с секцией
db_host = db_section.get('host')
db_port = db_section.get('port')

# Изменяем значения через секцию
db_section.set('host', 'newhost')
db_section.set('port', 3306)

# Изменения отражаются в основном конфиге
assert config.get('database.host') == 'newhost'
```

#### Объединение конфигураций при загрузке

```python
from src.Modules.Config_module import Config

config = Config()

# Устанавливаем начальные значения
config.set('app.name', 'MyApp')
config.set('app.version', '1.0.0')

# Загружаем из файла с объединением (merge=True по умолчанию)
config.load('config/app.yaml', merge=True)

# Старые значения сохраняются, новые добавляются
# Если в файле есть app.name, оно перезапишет существующее значение
```

#### Замена конфигурации при загрузке

```python
from src.Modules.Config_module import Config

config = Config()
config.set('old_key', 'old_value')

# Загружаем с заменой (merge=False)
config.load('config/app.yaml', merge=False)

# Все старые значения удалены, остались только из файла
```

#### Перезагрузка конфигурации

```python
from src.Modules.Config_module import Config

config = Config()
config.load('config/app.yaml')

# Изменяем значение в памяти
config.set('database.host', 'newhost')

# Если файл был изменен извне, перезагружаем
config.reload()  # Загрузит актуальные данные из файла
```

### Поддерживаемые типы данных

Модуль корректно обрабатывает все стандартные типы данных Python:

- **Строки**: `"text"` или `'text'`
- **Целые числа**: `42`
- **Вещественные числа**: `3.14`
- **Булевы значения**: `true` / `false` (YAML) или `true` / `false` (JSON)
- **None/null**: `null` (JSON) или `null` / `~` (YAML)
- **Списки**: `[1, 2, 3]` (JSON) или `- item1` (YAML)
- **Словари**: `{"key": "value"}` (JSON) или `key: value` (YAML)
- **Вложенные структуры**: Любая комбинация вышеперечисленных типов

**Пример сложной конфигурации:**

```yaml
app:
  name: MyApp
  version: 1.0.0
  debug: true
  features:
    enabled:
      - feature1
      - feature2
    disabled: []
  settings:
    timeout: 30.5
    retries: 3
    options:
      cache: true
      compression: false
```

```python
config = Config()
config.load('config/app.yaml')

# Все типы данных корректно обрабатываются
app_name = config.get('app.name')  # str: 'MyApp'
app_version = config.get('app.version')  # str: '1.0.0'
debug = config.get('app.debug')  # bool: True
features = config.get('app.features.enabled')  # list: ['feature1', 'feature2']
timeout = config.get('app.settings.timeout')  # float: 30.5
retries = config.get('app.settings.retries')  # int: 3
cache = config.get('app.settings.options.cache')  # bool: True
```

### Unicode и специальные символы

Модуль полностью поддерживает Unicode символы и специальные символы в конфигурационных файлах:

```yaml
app:
  name: МоеПриложение
  description: Описание с русскими символами
  author: Автор © 2024
  emoji: 🚀
```

```python
config = Config()
config.load('config/app.yaml')

name = config.get('app.name')  # 'МоеПриложение'
description = config.get('app.description')  # 'Описание с русскими символами'
```

### Обработка ошибок при чтении файлов

```python
from src.Modules.Config_module import Config

config = Config()

try:
    config.load('config/app.json')
except FileNotFoundError:
    print("Файл конфигурации не найден")
except ImportError as e:
    print(f"Требуется PyYAML для YAML файлов: {e}")
except Exception as e:
    print(f"Ошибка при загрузке конфигурации: {e}")
```

## Потокобезопасность

Все операции с конфигурацией потокобезопасны благодаря использованию `RLock`. Можно безопасно использовать один экземпляр `Config` из нескольких потоков одновременно.

```python
import threading
from src.Modules.Config_module import Config

config = Config()

def worker(thread_id):
    for i in range(10):
        config.set(f'thread_{thread_id}.value', i)
        value = config.get(f'thread_{thread_id}.value')

# Безопасное использование из нескольких потоков
threads = []
for i in range(5):
    t = threading.Thread(target=worker, args=(i,))
    threads.append(t)
    t.start()

for t in threads:
    t.join()
```

## Производительность

- Операции чтения/записи оптимизированы для частого использования
- Используется `RLock` для минимизации блокировок
- Глубокая копия данных выполняется только при необходимости
- Кэширование не используется для обеспечения актуальности данных

## Обработка ошибок

Модуль обрабатывает следующие ошибки:

- `FileNotFoundError`: Файл конфигурации не найден
- `ImportError`: Требуется PyYAML но не установлен
- `ValueError`: Некорректные параметры
- `KeyError`: Ключ не найден (при использовании `[]`)

Все ошибки логируются, но не прерывают выполнение программы (кроме критических случаев).

## Тестирование

Модуль полностью покрыт тестами с использованием pytest. Все тесты находятся в `tests/Test_Config_module/`.

### Запуск тестов

```bash
# Запуск всех тестов модуля
pytest tests/Test_Config_module/

# Запуск конкретного теста
pytest tests/Test_Config_module/test_base_config.py

# Запуск с подробным выводом
pytest tests/Test_Config_module/ -v

# Запуск с покрытием кода
pytest tests/Test_Config_module/ --cov=src.Modules.Config_module
```

### Структура тестов

- `test_base_config.py` - Тесты базового класса Config
- `test_config_manager.py` - Тесты ConfigManager (Singleton)
- `test_config_manager_extended.py` - Расширенные тесты ConfigManager
- `test_advanced_features.py` - Тесты продвинутых функций (env vars, callbacks)
- `test_config_file_reading.py` - Тесты чтения из файлов
- `test_file_operations.py` - Тесты операций с файлами
- `conftest.py` - Общие фикстуры для всех тестов

### Покрытие

Модуль имеет высокое покрытие тестами:
- ✅ Базовые операции (get, set, has, remove)
- ✅ Работа с вложенными ключами
- ✅ Работа с секциями
- ✅ Потокобезопасность
- ✅ Переменные окружения
- ✅ Подписка на изменения
- ✅ Работа с файлами (JSON/YAML)
- ✅ ConfigManager (Singleton)

## Лучшие практики

1. **Используйте секции** для организации конфигурации
2. **Используйте ConfigManager** для глобального доступа
3. **Сохраняйте конфигурацию** после изменений если нужно
4. **Используйте переменные окружения** для секретных данных
5. **Подписывайтесь на изменения** для динамической конфигурации
6. **Используйте значения по умолчанию** для опциональных параметров

## Миграция со старых версий

Если вы использовали старые классы `BaseConfig` и `ConfigManager` из `Base_manager_module`, миграция проста:

```python

# Новый код
from src.Modules.Config_module import Config, ConfigManager

# API остался совместимым!
```

## Лицензия

Модуль является частью проекта Bottle Inspector и следует его лицензии.

