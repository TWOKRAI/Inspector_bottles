# Руководство пользователя config_module

Подробное руководство по использованию модуля управления конфигурациями.

## Содержание

1. [Config — базовое использование](#config--базовое-использование)
2. [ConfigManager — управление несколькими конфигами](#configmanager--управление-несколькими-конфигами)
3. [Подписка на изменения](#подписка-на-изменения)
4. [Работа с секциями](#работа-с-секциями)
5. [Env-fallback](#env-fallback)
6. [Синхронизация через ConfigStore](#синхронизация-через-configstore)
7. [Примеры интеграции](#примеры-интеграции)

---

## Config — базовое использование

Config — простой контейнер для хранения данных конфигурации в памяти.

### Создание Config

```python
from config_module import Config

# Пустая конфигурация
cfg = Config()

# С начальными данными
cfg = Config(initial_data={
    "database": {
        "host": "localhost",
        "port": 5432,
        "name": "myapp"
    },
    "debug": True
})

# С env-fallback
cfg = Config(
    initial_data={"app_name": "MyApp"},
    env_prefix="APP"  # будет искать APP_APP_NAME
)
```

### Получение и установка значений

```python
# Dot-notation доступ (вложенные ключи)
host = cfg.get("database.host")      # "localhost"
port = cfg.get("database.port")      # 5432

# Со значением по умолчанию
timeout = cfg.get("database.timeout", default=30)

# Отключение env-fallback
value = cfg.get("some_key", env_fallback=False)

# Установка значений
cfg.set("database.host", "remote.host")
cfg.set("database.port", 3306)

# Dict-подобный синтаксис
cfg["debug"] = False
is_debug = cfg["debug"]
```

### Проверка и удаление

```python
# Проверка наличия ключа
if cfg.has("database.host"):
    print("Host configured")

# Через оператор 'in'
if "database.host" in cfg:
    print("Host configured")

# Удаление ключа
cfg.remove("database.timeout")
success = cfg.remove("non_existent")  # False

# Очистка всех данных
cfg.clear()
```

### Массовое обновление

```python
# Рекурсивное слияние (deep merge)
cfg.update({
    "database": {"name": "newdb"},  # merges with existing database config
    "new_section": {"key": "value"}
})

# После update:
# cfg.get("database.host") == "localhost"  (не перезаписано)
# cfg.get("database.name") == "newdb"      (обновлено)
# cfg.get("new_section.key") == "value"    (добавлено)

# Получить копию всех данных
all_data = cfg.data  # Dict[str, Any]
```

---

## ConfigManager — управление несколькими конфигами

ConfigManager управляет коллекцией Config объектов.

### Создание ConfigManager

```python
from config_module import ConfigManager

# Базовый
cm = ConfigManager()

# С именем менеджера
cm = ConfigManager(manager_name="AppConfigManager")

# С интеграцией ConfigStore (для cross-process синхронизации)
from shared_resources_module import SharedResourcesManager

sr = SharedResourcesManager()
cm = ConfigManager(shared_resources=sr)
```

### Создание и получение конфигураций

```python
# Создать новую конфигурацию
app_cfg = cm.create_config(
    name="app",
    initial_data={
        "name": "MyApplication",
        "version": "1.0.0",
        "debug": False
    }
)

# Работа с конфигом
app_cfg.set("debug", True)
version = app_cfg.get("version")  # "1.0.0"

# Получить существующий конфиг
cfg = cm.get_config("app")
if cfg:
    print(cfg.get("name"))

# Проверить наличие
if cm.has_config("app"):
    print("App config exists")

# Список всех конфигов
all_names = cm.list_configs()  # ["app", ...]
```

### Удаление конфигураций

```python
# Удалить конфиг
success = cm.remove_config("app")

# После удаления конфиг недоступен
cfg = cm.get_config("app")  # None
```

### Lifecycle

```python
# Инициализация (если используется)
cm.initialize()

# Закрытие (очистка ресурсов)
cm.shutdown()
```

---

## Подписка на изменения

Config поддерживает реактивные подписки на изменения.

### Подписка на конкретный ключ

```python
def on_debug_change(key, old_value, new_value):
    print(f"Debug mode changed: {old_value} → {new_value}")

# Подписаться
cfg.subscribe(callback=on_debug_change, key="debug")

# Теперь при cfg.set("debug", True) будет вызван callback
cfg.set("debug", True)
```

### Подписка на все ключи

```python
def on_any_change(key, old_value, new_value):
    print(f"{key} changed: {old_value} → {new_value}")

# Подписаться на все ("*")
cfg.subscribe(callback=on_any_change)

cfg.set("database.host", "newhost")  # сработает
cfg.set("debug", False)               # сработает
```

### Использование как декоратор

```python
@cfg.subscribe(key="database.port")
def on_port_change(key, old_value, new_value):
    print(f"Port changed to {new_value}")

cfg.set("database.port", 3306)  # на_port_change вызовется
```

### Отписка

```python
cfg.unsubscribe(callback=on_debug_change, key="debug")

# Теперь callback не вызовется
cfg.set("debug", True)
```

---

## Работа с секциями

ConfigSection — представление части конфигурации как отдельного объекта.

### Получение секции

```python
# Получить секцию
db_section = cfg.section("database")

# Работа с секцией использует тот же API что Config
db_section.get("host")      # "localhost"
db_section.get("port")      # 5432
```

### Изменения синхронизируются с основным конфигом

```python
cfg = Config(initial_data={"database": {"host": "localhost"}})
db_section = cfg.section("database")

# Изменение в секции
db_section.set("host", "remote.host")

# Отражается в основном конфиге
assert cfg.get("database.host") == "remote.host"

# И наоборот
cfg.set("database.port", 5432)
assert db_section.get("port") == 5432
```

### Глубокая работа с подсекциями

```python
cfg = Config(initial_data={
    "database": {
        "connection": {
            "host": "localhost",
            "port": 5432
        }
    }
})

# Секция может быть вложенной
db_section = cfg.section("database")
conn_section = db_section.section("connection")

conn_section.get("host")  # "localhost"

# Изменение в подсекции тоже синхронизируется с основным конфигом
conn_section.set("host", "newhost")
assert cfg.get("database.connection.host") == "newhost"
```

### Обновление секции

```python
db_section = cfg.section("database")

db_section.update({
    "host": "newhost",
    "port": 3306,
    "name": "newdb"
})

# Все изменения отражены в основном конфиге
assert cfg.get("database.host") == "newhost"
assert cfg.get("database.port") == 3306
```

---

## Env-fallback

Config может автоматически искать значения в переменных окружения.

### Как работает env-fallback

```python
import os

# Установить переменные окружения
os.environ["APP_DATABASE_HOST"] = "env.host"
os.environ["APP_DEBUG"] = "true"

# Создать конфиг с префиксом
cfg = Config(env_prefix="APP")

# Если ключа нет в конфиге, ищется в окружении
host = cfg.get("database.host")  # "env.host" (из APP_DATABASE_HOST)
debug = cfg.get("debug")          # "true" (из APP_DEBUG, строка!)

# Если есть начальные данные, они используются в приоритете
cfg = Config(
    initial_data={"database": {"host": "localhost"}},
    env_prefix="APP"
)

cfg.get("database.host")  # "localhost" (из initial_data)
cfg.get("debug")          # "true" (из APP_DEBUG)
```

### Отключение env-fallback

```python
cfg = Config(env_prefix="APP")

# Отключить для конкретного запроса
value = cfg.get("database.host", env_fallback=False)

# Если нет в конфиге, вернёт default, а не ищет в окружении
value = cfg.get("non_existent", default="default_val", env_fallback=False)
```

---

## Синхронизация через ConfigStore

ConfigStore — хранилище для cross-process синхронизации конфигураций (Dict at Boundary).

### Сохранение в ConfigStore

```python
from config_module import ConfigManager
from shared_resources_module import SharedResourcesManager

sr = SharedResourcesManager()
cm = ConfigManager(shared_resources=sr)

# Создать конфиг
cfg = cm.create_config("app", {"debug": False})

# Сохранить в ConfigStore (pickle-safe dict)
success = cm.sync_config("app")  # True если успешно

# После sync_config:
# - данные конфига сохранены в sr.config_store (dict)
# - доступны для других процессов
```

### Загрузка из ConfigStore

```python
# В другом процессе или потоке
sr2 = SharedResourcesManager()  # то же хранилище
cm2 = ConfigManager(shared_resources=sr2)

# Загрузить конфиг из ConfigStore
success = cm2.load_config_from_storage("app")  # True

# Теперь конфиг доступен в памяти
cfg = cm2.get_config("app")
debug = cfg.get("debug")  # False
```

### Полный цикл sync/load

```python
# === Процесс 1: создать и сохранить ===
sr1 = SharedResourcesManager()
cm1 = ConfigManager(shared_resources=sr1)

cfg1 = cm1.create_config("database", {
    "host": "localhost",
    "port": 5432
})

cm1.sync_config("database")  # → ConfigStore

# === Процесс 2: загрузить и использовать ===
sr2 = SharedResourcesManager()  # то же хранилище
cm2 = ConfigManager(shared_resources=sr2)

cm2.load_config_from_storage("database")  # ← ConfigStore
cfg2 = cm2.get_config("database")

host = cfg2.get("host")  # "localhost"
port = cfg2.get("port")  # 5432
```

---

## Примеры интеграции

### Пример 1: Конфигурация приложения

```python
from config_module import ConfigManager

cm = ConfigManager()

# Создать конфиг приложения
app_cfg = cm.create_config(
    name="app",
    initial_data={
        "name": "MyApp",
        "version": "1.0.0",
        "debug": False,
        "log_level": "INFO"
    }
)

# Использовать в коде
def main():
    app_name = app_cfg.get("name")
    debug = app_cfg.get("debug")
    
    print(f"Running {app_name} (debug={debug})")
    
    if debug:
        app_cfg.set("log_level", "DEBUG")

main()
```

### Пример 2: Конфигурация с env-fallback

```python
import os
from config_module import Config

os.environ["DB_HOST"] = "prod.db.example.com"
os.environ["DB_PORT"] = "5432"
os.environ["DB_NAME"] = "production"

# Конфиг с env-fallback
db_cfg = Config(env_prefix="DB")

# Используются значения из окружения
host = db_cfg.get("host")        # "prod.db.example.com"
port = db_cfg.get("port")        # "5432"
name = db_cfg.get("name")        # "production"

# Локальное значение можно переопределить
db_cfg.set("host", "localhost")
host = db_cfg.get("host")        # "localhost"
```

### Пример 3: Реактивные подписки

```python
from config_module import Config

cfg = Config(initial_data={
    "server": {
        "host": "localhost",
        "port": 8000
    }
})

# Подписаться на изменение порта
@cfg.subscribe(key="server.port")
def on_port_change(key, old_value, new_value):
    print(f"Restarting server on new port {new_value}")
    restart_server(new_value)

# При изменении порта callback сработает автоматически
cfg.set("server.port", 9000)
# Output: Restarting server on new port 9000
```

### Пример 4: Работа с секциями

```python
from config_module import Config

cfg = Config(initial_data={
    "api": {
        "endpoints": {
            "users": "/api/v1/users",
            "posts": "/api/v1/posts"
        },
        "timeout": 30,
        "retries": 3
    },
    "database": {
        "host": "localhost",
        "port": 5432
    }
})

# Работа через секции
api_cfg = cfg.section("api")
endpoints = api_cfg.section("endpoints")

users_url = endpoints.get("users")    # "/api/v1/users"
timeout = api_cfg.get("timeout")      # 30

# Изменение через секцию
endpoints.set("v2_users", "/api/v2/users")
assert cfg.get("api.endpoints.v2_users") == "/api/v2/users"
```

### Пример 5: Cross-process синхронизация

```python
from config_module import ConfigManager
from shared_resources_module import SharedResourcesManager

# === Главный процесс ===
def main_process():
    sr = SharedResourcesManager()
    cm = ConfigManager(shared_resources=sr)
    
    # Создать конфиг приложения
    app_cfg = cm.create_config("app", {
        "features": {
            "feature_a": True,
            "feature_b": False
        }
    })
    
    # Сохранить для других процессов
    cm.sync_config("app")
    
    # Главный процесс запускает рабочие
    spawn_worker_process()

# === Рабочий процесс ===
def worker_process():
    sr = SharedResourcesManager()  # то же хранилище
    cm = ConfigManager(shared_resources=sr)
    
    # Загрузить конфиг приложения
    cm.load_config_from_storage("app")
    app_cfg = cm.get_config("app")
    
    # Использовать конфиг
    if app_cfg.get("features.feature_a"):
        do_feature_a()
```

---

*Документ проверен на актуальность: 2026-04-09 (план рефакторинга модуля #6; содержание без функциональных изменений).*
