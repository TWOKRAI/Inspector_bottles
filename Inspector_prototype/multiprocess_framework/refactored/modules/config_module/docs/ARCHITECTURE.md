# Архитектура config_module

## Концепция: три слоя конфигурации

```
┌──────────────────────────────────────────────────────────────┐
│ data_schema_module (ЧТО: схемы, валидация, сериализация)    │
├──────────────────────────────────────────────────────────────┤
│              ↓ merge_with_defaults, SchemaBase ↓             │
├──────────────────────────────────────────────────────────────┤
│ config_module (КАК: runtime доступ, подписки, секции)       │
├──────────────────────────────────────────────────────────────┤
│         ↓ sync/load (dict) ↓                                 │
├──────────────────────────────────────────────────────────────┤
│ ConfigStore в shared_resources_module                        │
│ (ГДЕ: Dict at Boundary для cross-process хранения)          │
└──────────────────────────────────────────────────────────────┘
```

## Основные компоненты

### Config (~160 строк)

**Ответственность:** runtime-контейнер одной конфигурации.

**Интерфейс:**
- `get(key, default, env_fallback)` — dot-notation доступ
- `set(key, value, notify)` — установка с уведомлением подписчиков
- `update(data)` — рекурсивное слияние словаря
- `section(key)` → ConfigSection — работа с подсекциями
- `subscribe(callback, key)` / `unsubscribe()` — управление подписками
- `has(key)`, `remove(key)`, `clear()` — проверка/удаление
- `data` property — копия всех данных

**Особенности:**
- Dot-notation: `config.get("database.host")`
- Потокобезопасность через `RLock`
- Env-fallback: если ключ не найден, ищет `{env_prefix}_{KEY}` в переменных окружения
- Подписки на конкретные ключи или все ("*")
- Dict-подобный интерфейс: `config["key"]`, `"key" in config`

**НЕ входит в ответственность Config:**
- Загрузка/сохранение файлов (JSON/YAML) — делегируется `DataConverter` снаружи
- Валидация схем — делегируется `DataValidator` при необходимости
- Конвертация в/из Pydantic моделей — делегируется `DataConverter`

### ConfigManager (~215 строк)

**Ответственность:** менеджер множества Config объектов.

**Наследование:**
- `BaseManager` — единообразие со всеми менеджерами
- `ObservableMixin` — логирование и метрики
- `IConfigManager` — публичный контракт

**Интерфейс:**
- `create_config(name, initial_data, ...)` → Config
- `get_config(name)` → Optional[Config]
- `remove_config(name)` → bool
- `list_configs()` → List[str]
- `has_config(name)` → bool
- `sync_config(name)` → bool — сохранить в ConfigStore (pickle-safe dict)
- `load_config_from_storage(name)` → bool — загрузить из ConfigStore
- `initialize()` / `shutdown()` — lifecycle

**Синхронизация с ConfigStore:**
```python
# Сохранить в ConfigStore (Dict at Boundary)
if self._shared_resources:
    self._shared_resources.config_store.store(name, config.data)

# Загрузить из ConfigStore
data = self._shared_resources.config_store.get(name)
if data:
    self.create_config(name, initial_data=data)
```

**НЕ входит в ответственность ConfigManager:**
- StorageManager (удалён в рефакторинге) — заменён прямым доступом к ConfigStore
- EventManager (удалён в рефакторинге) — события остаются за вызывающим кодом
- Метаданные конфигураций — убрана сложная система сохранения метаданных

### ConfigSection

**Ответственность:** представление части конфигурации как отдельного объекта.

**Особенности:**
- Все изменения в ConfigSection автоматически отражаются в родительском Config
- Тот же API что и Config
- Делегирует все операции родительскому Config через префикс

**Пример:**
```python
config = Config(initial_data={"database": {"host": "localhost"}})
db_section = config.section("database")
db_section.get("host")   # "localhost"
db_section.set("port", 5432)  # config.get("database.port") == 5432
```

### ConfigSchemaAdapter

**Ответственность:** адаптация SchemaBase в параметры для Config.

Преобразует Pydantic/SchemaBase в dict параметров конфига.
Реализует `ISchemaAdapter` из `data_schema_module`.

## Интеграция с другими модулями

### data_schema_module

- **merge_with_defaults()** — рекурсивное слияние, используется в `Config.update()`
- **SchemaBase** — базовый класс для схем
- **FieldMeta**, **register_schema** — для ConfigManagerConfig

### shared_resources_module

- **ConfigStore** (Dict[str, dict]) — хранилище конфигов между процессами (Dict at Boundary)
- Опциональное; если нет `shared_resources` → ConfigManager работает только локально

### base_manager

- **BaseManager** — базовый класс менеджера
- **ObservableMixin** — логирование, метрики

## Дизайн-решения

1. **Config ≠ ConfigManager**
   - Config — простой контейнер (160 строк), НЕ управляет другими конфигами
   - ConfigManager — коллекция Config объектов с синхронизацией

2. **Нет файловой I/O в модуле**
   - Загрузка JSON/YAML/TOML — ответственность DataConverter (из data_schema_module)
   - Config принимает dict, возвращает dict — максимальная гибкость

3. **Нет собственной валидации**
   - Config хранит любые данные
   - Валидация (если нужна) — через DataValidator снаружи
   - Сохраняет простоту и производительность

4. **Dict at Boundary**
   - ConfigStore хранит Dict[str, dict], не объекты Config
   - Обеспечивает безопасность при cross-process сериализации

5. **Env-fallback в Config**
   - Если `env_prefix="APP"` и ключа нет, ищет переменную `APP_KEY` (с заменой точек на `_`)
   - Опциональное и отключаемое

## Поток использования

### Локальное использование

```python
config = Config(initial_data={"db_host": "localhost"})
config.get("db_host")
config.set("db_host", "remote.host")
```

### С менеджером и ConfigStore

```python
cm = ConfigManager(shared_resources=sr)
cfg = cm.create_config("app", {"debug": False})
cm.sync_config("app")  # → ConfigStore (dict)
```

### В другом процессе (загрузка)

```python
cm2 = ConfigManager(shared_resources=sr)
cm2.load_config_from_storage("app")  # ← ConfigStore (dict)
cfg = cm2.get_config("app")  # Config объект в памяти
```

## Производительность

- **Кэширование в памяти:** Config объекты хранятся в `_configs` (O(1) доступ)
- **Глубокая копия только на get:** property `data` возвращает копию для изоляции
- **RLock для thread-safety:** минимальные блокировки, отпускаются сразу
- **Ленивая загрузка:** конфиги загружаются из ConfigStore только при явном запросе
