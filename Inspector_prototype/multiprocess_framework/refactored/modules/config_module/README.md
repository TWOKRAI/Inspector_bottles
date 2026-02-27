# Config Module (Refactored)

Модуль управления конфигурациями с интеграцией всех модулей системы.

## 🚀 Особенности

- ✅ **Интеграция с BaseManager** - единообразие со всеми менеджерами системы
- ✅ **Валидация через Pydantic** - опциональная валидация конфигураций через схемы
- ✅ **Конвертация форматов** - использование DataConverter из data_schema_module
- ✅ **Межпроцессное хранение** - хранение в ProcessData через SharedResourcesManager
- ✅ **Автоматическая синхронизация** - синхронизация изменений через EventManager
- ✅ **Ручная синхронизация** - возможность вручную синхронизировать конфигурации
- ✅ **Вложенные ключи** - поддержка вложенных ключей через точку
- ✅ **Работа с секциями** - удобная работа с частями конфигурации
- ✅ **Переменные окружения** - поддержка переменных окружения
- ✅ **Подписка на изменения** - callback-функции для отслеживания изменений

## 📦 Структура модуля

```
config_module/
├── __init__.py              # Экспорт основных классов
├── README.md                # Документация
├── core/                    # Основные классы
│   ├── base_config.py       # Базовый класс Config
│   └── config_manager.py    # ConfigManager
├── sections/                # Секции конфигурации
│   └── config_section.py    # ConfigSection
├── interfaces.py            # Интерфейсы IConfigManager, IConfig
├── docs/                    # Документация
└── tests/                   # Тесты
```

## 📋 Config vs ConfigManager

**Важно понимать разницу:**

### Config (base_config.py)
- **Контейнер данных** для ОДНОЙ конфигурации
- Работает с данными: get/set, файлы, валидация, секции
- **Не зависит от системы** - можно использовать отдельно
- Аналогия: как `ProcessData` - просто контейнер данных

### ConfigManager (config_manager.py)
- **Менеджер** для управления МНОЖЕСТВОМ конфигураций
- Управляет несколькими `Config` объектами
- **Интегрируется с системой**: BaseManager, ProcessData, EventManager
- Хранит конфигурации в ProcessData для межпроцессного доступа
- Синхронизирует изменения между процессами

**Когда использовать:**
- `Config` - если нужна одна простая конфигурация без интеграции с системой
- `ConfigManager` - если нужно управлять несколькими конфигурациями + интеграция с системой

## 💡 Быстрый старт

### Базовое использование Config (одна конфигурация)

```python
from multiprocess_framework.refactored.modules.config_module import Config

# Создание конфигурации
config = Config()
config.set('database.host', 'localhost')
config.set('database.port', 5432)

# Получение значений
host = config.get('database.host')  # 'localhost'
port = config.get('database.port', 5432)  # 5432 или значение по умолчанию
```

### Использование ConfigManager (несколько конфигураций + интеграция)

### Использование ConfigManager

```python
from multiprocess_framework.refactored.modules.config_module import ConfigManager
from multiprocess_framework.refactored.modules.shared_resources_module import SharedResourcesManager

# Создание ConfigManager с интеграцией
shared_resources = SharedResourcesManager()
config_manager = ConfigManager(
    manager_name="MyConfigManager",
    shared_resources=shared_resources,
    auto_sync=True
)

# Инициализация
config_manager.initialize()

# Создание конфигурации
app_config = config_manager.create_config(
    name='app',
    initial_data={'name': 'MyApp', 'version': '1.0.0'}
)

# Получение конфигурации
app_config = config_manager.get_config('app')

# Синхронизация (ручная)
config_manager.sync_config('app')

# Загрузка из ProcessData
config_manager.load_config_from_storage('app')
```

### Валидация через Pydantic

```python
from pydantic import BaseModel
from multiprocess_framework.refactored.modules.config_module import Config

# Определение схемы
class DatabaseConfig(BaseModel):
    host: str = "localhost"
    port: int = 5432
    name: str

# Создание конфигурации с валидацией
config = Config(
    validation_schema=DatabaseConfig,
    validate_on_set=True
)

# Валидация происходит автоматически при установке значений
config.set('host', 'localhost')
config.set('port', 5432)
config.set('name', 'mydb')
```

### Работа с файлами

```python
from multiprocess_framework.refactored.modules.config_module import Config

# Загрузка из файла
config = Config()
config.load('config/app.yaml')

# Сохранение в файл
config.save('config/app.yaml')

# Перезагрузка
config.reload()
```

### Работа с секциями

```python
from multiprocess_framework.refactored.modules.config_module import Config

config = Config()

# Получение секции
db_config = config.section('database')

# Работа с секцией
db_config.set('host', 'localhost')
db_config.set('port', 5432)
host = db_config.get('host')

# Все изменения отражаются в основном конфиге
assert config.get('database.host') == 'localhost'
```

### Подписка на изменения

```python
from multiprocess_framework.refactored.modules.config_module import Config

config = Config()

# Подписка на изменения конкретного ключа
@config.subscribe(key='database.host')
def on_db_host_change(key, old_value, new_value):
    print(f"Database host changed: {old_value} -> {new_value}")

# Подписка на все изменения
@config.subscribe()
def on_any_change(key, old_value, new_value):
    print(f"Config changed: {key} = {new_value}")

# Изменение значения вызовет callback
config.set('database.host', 'newhost')
```

## 🔗 Интеграция с другими модулями

### data_schema_module

- **DataConverter** - конвертация между форматами (JSON, YAML, dict, Pydantic model)
- **DataValidator** - валидация данных через Pydantic схемы
- **SchemaRegistry** - реестр схем для валидации

### shared_resources_module

- **SharedResourcesManager** - доступ к ProcessData для хранения конфигураций
- **EventManager** - синхронизация изменений между процессами
- **ProcessStateRegistry** - реестр состояний процессов

## 📖 Документация

Подробная документация находится в папке `docs/`:
- `README.md` - основная документация
- `USAGE_GUIDE.md` - руководство пользователя
- `ARCHITECTURE.md` - архитектура модуля
- `API_REFERENCE.md` - справочник API

## 🧪 Тестирование

Модуль включает unit тесты в папке `tests/`.

### Запуск тестов

```bash
# Все тесты модуля
pytest src/multiprocess_framework/refactored/modules/config_module/tests/ -v

# Конкретный тест
pytest src/multiprocess_framework/refactored/modules/config_module/tests/test_config.py -v
```

## 📝 Примечания

- Модуль полностью интегрирован с новой архитектурой системы
- Обратная совместимость со старым модулем не поддерживается
- Все конфигурации могут храниться в ProcessData для межпроцессного доступа
- Синхронизация происходит автоматически при изменениях (если включена)

## 📄 Лицензия

См. основной файл лицензии проекта.

