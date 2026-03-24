# Структура модуля data_schema

## Обзор

Модуль `data_schema` предоставляет универсальную систему работы с данными на основе Pydantic v2. Использует гибридный подход: dict в ProcessData, Pydantic модели в коде.

## Финальная структура

```
data_schema/
├── __init__.py                 # Главный файл модуля с экспортами
│
├── core/                       # Базовые компоненты
│   ├── __init__.py
│   ├── interfaces.py          # Интерфейсы для всех компонентов
│   ├── exceptions.py           # Исключения модуля
│   └── metrics.py              # Метрики и мониторинг
│
├── registry/                   # Реестр схем и автообнаружение
│   ├── __init__.py
│   ├── schema_registry.py     # Реестр Pydantic схем (Singleton)
│   └── register_discovery.py  # discover_registers_from_package, register_package_registers
│
├── storage/                     # Хранение данных
│   ├── __init__.py
│   ├── storage_manager.py     # Менеджер хранения данных компонентов
│   └── process_data_container.py  # Контейнер для ДНК компонентов
│
├── versioning/                  # Версионирование
│   ├── __init__.py
│   └── version_manager.py     # Менеджер версий моделей
│
├── factory/                     # Фабрики моделей
│   ├── __init__.py
│   ├── model_factory.py       # Фабрика для создания моделей
│   └── dna_factory.py         # Фабрика ДНК компонентов
│
├── api/                        # API адаптеры
│   ├── __init__.py
│   ├── manager_adapter.py    # Адаптер для работы с данными менеджера
│   └── simple_api.py          # Упрощенный API для простых случаев
│
├── models/                      # Модели данных
│   ├── __init__.py
│   ├── base.py                # Базовые модели (BaseManagerModel, BaseComponentModel)
│   ├── dna.py                 # Модели ДНК компонентов
│   └── types.py               # Типы компонентов
│
├── utils/                       # Утилиты
│   ├── __init__.py
│   ├── converters.py          # Конвертеры данных (DataConverter: JSON, YAML, dict)
│   ├── validators.py          # Валидаторы данных
│   ├── helpers.py             # Вспомогательные функции
│   ├── reference.py           # Работа со ссылками
│   ├── migration.py           # Хелперы для миграции
│   ├── field_schema.py        # FieldSchema — создание полей Pydantic по схеме-словарю (схему передаёт приложение)
│   └── registers_io.py        # Универсальный ввод/вывод регистров (to_dict, from_dict, to_json, from_json, to_yaml, from_yaml, to_flat_dict, from_flat_dict)
│
├── tools/                       # Инструменты для работы со схемами
│   ├── __init__.py
│   ├── schema_visualizer.py   # Визуализатор схем
│   └── schema_documentation_generator.py  # Генератор документации
│
└── docs/                       # Документация
    ├── examples/               # Примеры использования
    │   └── example.py
    ├── README.md
    ├── USER_GUIDE.md
    ├── STRUCTURE.md           # Этот файл
    └── ...                     # Остальная документация
```

## Основные компоненты

### core/
**Базовые компоненты модуля:**
- `interfaces.py` - Интерфейсы для всех компонентов (ISchemaManager, IStorageManager, IVersionManager, IDataConverter, IDataValidator)
- `exceptions.py` - Иерархия исключений модуля
- `metrics.py` - Система метрик и мониторинга

### registry/
**Реестр Pydantic схем и автообнаружение:**
- `schema_registry.py` — реестр для регистрации и создания экземпляров моделей с дефолтными значениями (Singleton); декоратор `register_schema`
- `register_discovery.py` — `discover_registers_from_package(package_name)` (поиск классов *Registers в пакете), `register_package_registers(package_name, schema_registry)` (универсальный мост: discovery + регистрация в SchemaManager)

### storage/
**Хранение данных:**
- `storage_manager.py` - Менеджер хранения данных компонентов в ProcessData
- `process_data_container.py` - Контейнер для ДНК компонентов

### versioning/
**Версионирование:**
- `version_manager.py` - Менеджер версий моделей с историей изменений и откатом

### factory/
**Фабрики моделей:**
- `model_factory.py` - Единая фабрика для создания любых моделей
- `dna_factory.py` - Фабрика для работы с ДНК компонентов

### api/
**API адаптеры:**
- `manager_adapter.py` - Адаптер для удобной работы с данными менеджера
- `simple_api.py` - Упрощенный API для простых случаев использования

### models/
**Модели данных:**
- `base.py` - Базовые модели (BaseManagerModel, BaseComponentModel)
- `dna.py` - Модели ДНК компонентов
- `types.py` - Типы компонентов

### utils/
**Утилиты:**
- `converters.py` — конвертеры между форматами (DataConverter: JSON, YAML, dict, Pydantic model)
- `validators.py` — валидаторы данных на основе Pydantic v2
- `helpers.py` — вспомогательные функции (точечная нотация, объединение данных)
- `reference.py` — работа со ссылками на другие модели/ресурсы
- `migration.py` — хелперы для миграции из старых форматов
- `field_schema.py` — **FieldSchema**: класс для создания полей Pydantic по схеме-словарю. Схему передают в `__init__(field_schema)`; экземпляр вызываем как поле: `inst(default_value, description='', **overrides)`. Статический метод `FieldSchema.deep_merge(base, overrides)`. Схему (словарь) задаёт приложение; фреймворк не содержит дефолтной схемы.
- `registers_io.py` — универсальные функции ввода/вывода для объектов с `model_dump_all()` и `model_validate_all(data)`: `registers_to_dict`, `registers_from_dict`, `registers_to_json`, `registers_from_json`, `registers_to_yaml`, `registers_from_yaml`, `registers_to_flat_dict`, `registers_from_flat_dict`. При from_* передаётся фабрика экземпляра (callable без аргументов).

### tools/
**Инструменты для работы со схемами:**
- `schema_visualizer.py` - Визуализатор схем (текст, JSON, HTML, Mermaid)
- `schema_documentation_generator.py` - Генератор документации (Markdown, RST, HTML)

## Принципы организации

1. **Четкое разделение ответственности**: Каждая папка отвечает за свою область функциональности
2. **Интерфейсы в core**: Все интерфейсы определены в `core/interfaces.py`
3. **Нет дубликатов**: Каждый компонент существует только в одном месте
4. **Документация в docs**: Вся документация собрана в папке `docs`
5. **Чистые импорты**: Все импорты используют правильные пути к модулям
6. **Логичная группировка**: Связанные файлы сгруппированы по папкам

## Использование

```python
from multiprocess_framework.modules.Shared_resources_module.data_schema import (
    SchemaManager,
    StorageManager,
    ModelFactory,
    ManagerDataAdapter,
    VersionManager,
    DataConverter,
    DataValidator
)

# Регистрация схемы
registry = SchemaManager.get_instance()
registry.register("MyModel", MyModel)

# Создание модели
model = ModelFactory.create("MyModel", {"field": "value"})

# Работа с хранилищем
storage = StorageManager.get_instance(shared_resources)
storage.register_manager(manager_model)

# Версионирование
version_manager = VersionManager(storage)
version = version_manager.create_version(manager_model)

# Конвертация
converter = DataConverter()
json_str = converter.model_to_json(model)

# Валидация
validator = DataValidator()
success, instance, error = validator.validate(data, MyModel)
```
