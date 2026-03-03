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
├── registry/                   # Реестр схем
│   ├── __init__.py
│   └── schema_registry.py     # Реестр Pydantic схем
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
│   ├── converters.py          # Конвертеры данных (JSON, YAML, dict)
│   ├── validators.py          # Валидаторы данных
│   ├── helpers.py             # Вспомогательные функции
│   ├── reference.py           # Работа со ссылками
│   └── migration.py            # Хелперы для миграции
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
- `interfaces.py` - Интерфейсы для всех компонентов (ISchemaRegistry, IStorageManager, IVersionManager, IDataConverter, IDataValidator)
- `exceptions.py` - Иерархия исключений модуля
- `metrics.py` - Система метрик и мониторинга

### registry/
**Реестр Pydantic схем:**
- `schema_registry.py` - Реестр для регистрации и создания экземпляров моделей с дефолтными значениями

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
- `converters.py` - Конвертеры между форматами (JSON, YAML, dict, Pydantic model)
- `validators.py` - Валидаторы данных на основе Pydantic v2
- `helpers.py` - Вспомогательные функции (точечная нотация, объединение данных)
- `reference.py` - Работа со ссылками на другие модели/ресурсы
- `migration.py` - Хелперы для миграции из старых форматов

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
    SchemaRegistry,
    StorageManager,
    ModelFactory,
    ManagerDataAdapter,
    VersionManager,
    DataConverter,
    DataValidator
)

# Регистрация схемы
registry = SchemaRegistry.get_instance()
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
