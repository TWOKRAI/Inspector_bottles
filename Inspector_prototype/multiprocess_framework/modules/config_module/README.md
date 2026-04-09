# config_module

Runtime-управление конфигурациями в multiprocess-фреймворке.

**Статус:** 8/8 · Рефакторинг завершён · 49 тестов ✅

---

## Назначение

config_module предоставляет runtime-API для работы с конфигурациями:
- Dot-notation доступ: `config.get("database.host")`
- Реактивные подписки на изменения
- Работа с секциями конфигурации
- Environment fallback: автоматический поиск в переменных окружения
- Cross-process синхронизация через ConfigStore (Dict at Boundary)

**Ключевая идея:** config_module — это NOT валидация, NOT сериализация, NOT файловый I/O.
Это только **runtime доступ и подписки**. Валидация делегируется `data_schema_module`.

---

## Роль в архитектуре

```
data_schema_module          ← ЧТО: схемы, валидация, сериализация
       ↓
config_module               ← КАК: runtime доступ, подписки, секции
       ↓
ConfigStore (SRM)           ← ГДЕ: pickle-safe хранение между процессами
```

---

## Dict at Boundary

**ConfigStore** оперирует снимками конфигурации как **`dict`**, а не как экземплярами `Config`.

| Слой | Формат |
|------|--------|
| **Граница (между процессами / ConfigStore)** | `dict` (pickle-safe, предсказуемая сериализация) |
| **Внутри процесса** | объекты **`Config`** (подписки, блокировки, dot-notation) |
| **Конфигурация самого менеджера** | **`ConfigManagerConfig`** (`SchemaBase`, Pydantic v2) — описывает настройки менеджера, **не** заменяет payload в хранилище |

`ConfigManager.sync_config(name)` сохраняет **`config.data`** (копия внутреннего дерева в виде dict).  
`load_config_from_storage(name)` читает dict из store и создаёт или обновляет **`Config`** локально.

Подробнее: [`DECISIONS.md`](DECISIONS.md) (ADR-143), главный [`../../DECISIONS.md`](../../DECISIONS.md) (ADR-023).

---

## Структура модуля

```
config_module/
├── __init__.py              # Публичный API: Config, ConfigManager, ConfigSection
├── interfaces.py            # IConfig, IConfigManager, IConfigObserver
├── configs/
│   ├── config_manager_config.py  # ConfigManagerConfig (SchemaBase) — схема модуля
│   └── __init__.py
├── core/
│   ├── config.py            # Config — runtime контейнер (dot-notation, подписки)
│   └── config_manager.py    # ConfigManager — менеджер множества Config
├── sections/
│   └── config_section.py    # ConfigSection — view на часть Config
├── adapters/
│   └── schema_adapter.py    # ConfigSchemaAdapter — адаптер SchemaBase
├── docs/
│   ├── ARCHITECTURE.md      # Архитектура модуля
│   └── USAGE_GUIDE.md       # Подробное руководство с примерами
├── DECISIONS.md             # Локальные ADR (ADR-143…146 + ссылка на глобальный ADR-023)
├── tests/
│   ├── conftest.py
│   ├── test_config.py       # 21 тест
│   ├── test_config_manager.py # 18 тестов
│   └── test_config_section.py # 10 тестов
└── README.md               # Этот файл
```

---

## Быстрый старт

### Простое использование

```python
from config_module import Config

# Создать конфиг
cfg = Config(initial_data={"database": {"host": "localhost"}})

# Получить значение
host = cfg.get("database.host")  # "localhost"

# Установить значение
cfg.set("database.port", 5432)

# Работать как словарь
cfg["debug"] = True
```

### С менеджером и синхронизацией

```python
from config_module import ConfigManager
from shared_resources_module import SharedResourcesManager

# Создать менеджер
sr = SharedResourcesManager()
cm = ConfigManager(shared_resources=sr)

# Создать конфиг
cfg = cm.create_config("app", {"debug": False})

# Сохранить в ConfigStore (для других процессов)
cm.sync_config("app")

# В другом процессе загрузить
cm2 = ConfigManager(shared_resources=sr)
cm2.load_config_from_storage("app")
cfg2 = cm2.get_config("app")
```

### С подписками

```python
cfg = Config(initial_data={"port": 8000})

# Подписаться на изменение
@cfg.subscribe(key="port")
def on_port_change(key, old_value, new_value):
    print(f"Port changed: {old_value} → {new_value}")

# При изменении callback сработает
cfg.set("port", 9000)  # Output: Port changed: 8000 → 9000
```

---

## Основные компоненты

### Config

**Ответственность:** runtime-контейнер одной конфигурации.

**Интерфейс:**
- `get(key, default, env_fallback)` — dot-notation доступ
- `set(key, value, notify)` — установка с уведомлением
- `update(data)` — рекурсивное слияние
- `has(key)`, `remove(key)`, `clear()` — проверка/удаление
- `section(key)` — работа с подсекциями
- `subscribe(callback, key)` / `unsubscribe()` — подписки
- `data` property — копия всех данных

**Особенности:**
- Потокобезопасность через RLock
- Env-fallback: если нет ключа, ищет в `{env_prefix}_{KEY}`
- Dict-подобный интерфейс: `config["key"]`, `"key" in config`

### ConfigManager

**Ответственность:** менеджер множества Config объектов.

**Интерфейс:**
- `create_config(name, initial_data, ...)` → Config
- `get_config(name)` → Optional[Config]
- `remove_config(name)` → bool
- `list_configs()` → List[str]
- `sync_config(name)` → bool — в ConfigStore (dict)
- `load_config_from_storage(name)` → bool — из ConfigStore
- `initialize()` / `shutdown()` — lifecycle

**Синхронизация:** через `shared_resources.config_store` (Dict[str, dict])

### ConfigSection

Представление части конфигурации как отдельного объекта.

```python
cfg = Config(initial_data={"database": {"host": "localhost"}})
db = cfg.section("database")
db.get("host")  # "localhost"
db.set("port", 5432)  # отражается в cfg
```

---

## Документация

- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** — детальная архитектура модуля
- **[USAGE_GUIDE.md](docs/USAGE_GUIDE.md)** — полное руководство с примерами
- **[DECISIONS.md](DECISIONS.md)** — локальные архитектурные решения (ADR-143…146)

---

## Публичный API

| Метод | Описание |
|-------|----------|
| `Config(initial_data, env_prefix)` | Создать контейнер |
| `config.get(key, default, env_fallback)` | Получить значение (dot-notation) |
| `config.set(key, value, notify)` | Установить значение |
| `config.update(data)` | Рекурсивно слить словарь |
| `config.section(key)` | Вернуть ConfigSection |
| `config.subscribe(callback, key)` | Подписаться на изменения |
| `config.unsubscribe(callback, key)` | Отписаться |
| `config.data` | Копия всех данных |
| `ConfigManager(manager_name, shared_resources)` | Создать менеджер |
| `cm.create_config(name, initial_data, ...)` | Создать конфиг |
| `cm.get_config(name)` | Получить конфиг |
| `cm.sync_config(name)` | Сохранить в ConfigStore |
| `cm.load_config_from_storage(name)` | Загрузить из ConfigStore |

---

## Зависимости модуля

| Модуль | Что используется |
|--------|-----------------|
| `data_schema_module` | `merge_with_defaults`, `SchemaBase`, `FieldMeta`, `register_schema` |
| `base_manager` | `BaseManager`, `ObservableMixin` |
| `shared_resources_module` | `ConfigStore` (опционально) |

---

## Запуск тестов

```bash
pytest modules/config_module/tests/ -v
```

---

## Дизайн-решения

- **Dict at Boundary:** ConfigStore хранит `Dict[str, dict]`, не объекты `Config` (см. раздел выше и [ADR-143](DECISIONS.md))
- **No file I/O:** загрузка файлов — ответственность DataConverter / прикладного кода ([ADR-144](DECISIONS.md))
- **No validation в Config:** произвольные dict; валидация — через `data_schema_module` при необходимости
- **Env-fallback opt-in:** только если задан `env_prefix` ([ADR-146](DECISIONS.md))

---

## ADR

- **ADR-023** (глобальный): тонкая обёртка над `data_schema_module` — [главный DECISIONS.md](../../DECISIONS.md) (поиск по заголовку ADR-023)
- **ADR-143…146** (модуль): [DECISIONS.md](DECISIONS.md)
