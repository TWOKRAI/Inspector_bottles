# Data Schema Module

Универсальная система работы с данными на основе Pydantic v2.

Этот модуль инкапсулирует всю логику для работы с дата-классами и схемами данных.
Использует гибридный подход: dict в ProcessData, Pydantic модели в коде.

## 🚀 Быстрый старт

**Минимальный путь** (схемы + создание экземпляров, без ProcessData):

```python
from multiprocess_framework.refactored.modules.data_schema_module import (
    SchemaManager, register_schema, ModelFactory
)

@register_schema("MyConfig")
class MyConfig(BaseModel):
    host: str = "localhost"
    port: int = 8080

obj = ModelFactory.create("MyConfig", {"host": "0.0.0.0"})
```

**С хранением в ProcessData:** добавьте `StorageManager(shared_resources)` и `storage.register_manager(...)` / `get_manager_model(...)`. Остальное (VersionManager, Tools, registers_io) — по необходимости.

## 📦 Основные возможности

- ✅ Создание схем из Pydantic моделей
- ✅ **FieldSchema** — создание полей по схеме-словарю (схему передаёт приложение, фреймворк только мержит и возвращает `Field`)
- ✅ **Автообнаружение по суффиксу** — `discover_registers_from_package(package, suffix)` и `register_package_schemas(package, suffix)` — универсально для *Registers и *Data (пакет → SchemaManager). См. [docs/DISCOVERY_AND_PACKAGES.md](docs/DISCOVERY_AND_PACKAGES.md) и [docs/examples/03_registers_and_data_packages.py](docs/examples/03_registers_and_data_packages.py).
- ✅ **registers_io** — универсальный ввод/вывод объектов с `model_dump_all`/`model_validate_all` (dict, JSON, YAML, flat_dict)
- ✅ Валидация данных через Pydantic v2
- ✅ Конвертация между форматами (JSON, YAML, dict, Pydantic model)
- ✅ Работа с дефолтными значениями
- ✅ Автоматическая синхронизация с ProcessData
- ✅ Версионирование схем
- ✅ ДНК компонентов (опционально)

## 📚 Структура модуля

```
data_schema_module/
├── __init__.py              # Экспорт основных классов
├── README.md                # Документация
├── core/                    # Ядро модуля
│   ├── interfaces.py        # Интерфейсы
│   ├── exceptions.py        # Исключения
│   └── metrics.py           # Метрики
├── models/                  # Модели данных
│   ├── base.py             # Базовые модели
│   ├── dna.py              # ДНК компонентов
│   └── types.py            # Типы
├── storage/                 # Хранилище
│   ├── storage_manager.py   # Менеджер хранения
│   └── process_data_container.py
├── registry/                # Реестр схем и автообнаружение
│   ├── schema_registry.py   # Реестр Pydantic схем
│   └── register_discovery.py  # discover_registers_from_package, register_package_registers
├── factory/                 # Фабрики
│   ├── model_factory.py
│   └── dna_factory.py
├── utils/                   # Утилиты
│   ├── converters.py        # Конвертеры (DataConverter)
│   ├── validators.py        # Валидаторы
│   ├── helpers.py           # Вспомогательные функции
│   ├── reference.py         # Ссылки
│   ├── migration.py         # Миграция
│   ├── field_schema.py      # FieldSchema — поля по схеме-словарю (схему передаёт приложение)
│   └── registers_io.py      # Универсальный ввод/вывод регистров (dict, json, yaml, flat_dict)
├── versioning/              # Версионирование
│   └── version_manager.py
├── api/                     # API
│   ├── manager_adapter.py
│   └── simple_api.py
├── tools/                   # Инструменты
│   ├── formatters.py
│   ├── schema_visualizer.py
│   └── schema_documentation_generator.py
├── tests/                   # Тесты
└── docs/                    # Документация
```

## 💡 Использование

### FieldSchema — поля по схеме-словарю

Схему (словарь метаданных) передаёт приложение; фреймворк только мержит её с переопределениями и возвращает `Field(...)`.

```python
from multiprocess_framework.refactored.modules.data_schema_module import FieldSchema

# В приложении задаёте словарь (например DEFAULT_FIELD_SCHEMA)
# Экземпляр вызываем как поле: field_from_schema(default_value, description='', **overrides)
field_from_schema = FieldSchema(DEFAULT_FIELD_SCHEMA)
dp: float = field_from_schema(1.4, description='Разрешение', min=0.1, max=20.0)
```

### Регистрация регистров пакета в SchemaManager

```python
from multiprocess_framework.refactored.modules.data_schema_module import register_package_registers

# Discovery классов *Registers в пакете + регистрация в SchemaManager
register_package_registers("App.Registers.models")
```

### Универсальный ввод/вывод регистров (registers_io)

```python
from multiprocess_framework.refactored.modules.data_schema_module import (
    registers_to_json, registers_from_json,
    registers_to_dict, registers_from_dict,
)

# Объект должен иметь model_dump_all() и model_validate_all(data); фабрика — callable без аргументов
json_str = registers_to_json(registers)
registers = registers_from_json(json_str, factory=RegistersManager)
```

### Создание схемы

```python
from pydantic import BaseModel
from multiprocess_framework.refactored.modules.data_schema_module import (
    SchemaManager,
    register_schema
)

class MyComponentConfig(BaseModel):
    name: str
    enabled: bool = True

# Регистрация схемы
@register_schema("MyComponent")
class MyComponentSchema(MyComponentConfig):
    pass
```

### Работа с данными

```python
from multiprocess_framework.refactored.modules.data_schema_module import StorageManager

storage = StorageManager(shared_resources=shared_resources)

# Сохранение данных компонента
storage.save_manager_data(
    process_name="MyProcess",
    manager_type="MyComponent",
    manager_name="instance1",
    data={"name": "test", "enabled": True}
)

# Получение данных
data = storage.get_manager_data(
    process_name="MyProcess",
    manager_type="MyComponent",
    manager_name="instance1"
)
```

## 🔗 Интеграция

Модуль интегрируется с:
- `shared_resources_module` - через SharedResourcesManager
- `process_module` - через ProcessData
- Другими модулями системы через StorageManager

## 📖 Документация

Подробная документация находится в папке `docs/`:
- [docs/README.md](docs/README.md) — обзор документации
- [docs/STRUCTURE.md](docs/STRUCTURE.md) — структура модуля
- [docs/DIAGRAMS.md](docs/DIAGRAMS.md) — **диаграммы классов и связей** (что с чем связано, для чего)
- [docs/EVALUATION.md](docs/EVALUATION.md) — оценка модуля (баллы, сильные стороны, рекомендации)
- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) — руководство пользователя
- [docs/TOOLS_GUIDE.md](docs/TOOLS_GUIDE.md) — визуализация и генерация документации схем
- [docs/EXTENDING_GUIDE.md](docs/EXTENDING_GUIDE.md) — расширение модуля
- [docs/DNA_USAGE_EXAMPLES.md](docs/DNA_USAGE_EXAMPLES.md) — примеры ДНК компонентов

## 🧪 Тестирование

В папке `tests/` — unit-тесты модуля, в том числе для **FieldSchema**, **registers_io**, **register_discovery**.

**Запуск** (из каталога `refactored/modules`):

```bash
cd multiprocess_framework/refactored/modules
pytest data_schema_module/tests/ -v
```

Подробнее: [tests/README.md](tests/README.md).

## 📝 Примечания

- Модуль вынесен из `Shared_resources_module` как отдельный модуль для переиспользования
- Поддерживается обратная совместимость со старым расположением
- Все зависимости опциональны и импортируются динамически

## 💬 Сложность модуля — советы

Модуль **не перегружен**: слои разделены (core → registry/storage → factory/api → utils/tools), циклов нет. Ощущение сложности чаще из-за **многообразия входов**, а не из-за запутанной архитектуры.

**Что иметь в голове:**
- **Ядро для большинства сценариев:** `SchemaManager` + `register_schema` (или `register_package_registers`) + `ModelFactory`. Остальное подключается по мере надобности.
- **Одна модель** (dict/json/yaml) → `DataConverter`. **Набор регистров** (model_dump_all/model_validate_all) → `registers_io`.
- **VersionManager, SchemaVisualizer, ДНК** — опционально; без них модуль остаётся полноценным.
- Везде один термин — **SchemaManager** (менеджер схем).

Если хочется упростить жизнь новым разработчикам: в README/доках явно выделить блок «минимальный путь» (как выше) и раздел «Когда что использовать» (см. [docs/DIAGRAMS.md](docs/DIAGRAMS.md), шпаргалка в конце).

## 🤖 Для AI и новых разработчиков

**Быстрая справка:** [docs/QUICK_REFERENCE.md](docs/QUICK_REFERENCE.md) — принципы работы, взаимосвязи компонентов, типичный workflow. Позволяет понять модуль без изучения всех файлов.

**Визуализация:** [docs/DIAGRAMS.md](docs/DIAGRAMS.md) — диаграммы классов и потоков данных.

**Детальная структура:** [docs/STRUCTURE.md](docs/STRUCTURE.md) — описание всех пакетов и файлов.

## 📄 Лицензия

См. основной файл лицензии проекта.

