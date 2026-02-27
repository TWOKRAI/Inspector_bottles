# Диаграммы модуля data_schema_module

Назначение классов, связи и потоки данных. Рендер: любой просмотрщик Markdown с поддержкой Mermaid (GitHub, VS Code, и т.д.).

---

## 1. Обзор пакетов и ролей

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        data_schema_module                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│  core/          Интерфейсы (ISchemaManager, IStorageManager, …),           │
│                 исключения, метрики                                          │
│  models/        Базовые Pydantic-модели (BaseManagerModel, BaseComponentModel)│
│  registry/      Реестр схем + автообнаружение регистров                      │
│  storage/       Хранение данных в ProcessData                                │
│  versioning/    Версионирование конфигов                                     │
│  factory/       Создание экземпляров по имени схемы                          │
│  api/           Адаптеры и упрощённый API                                   │
│  utils/         Конвертеры, валидаторы, FieldSchema, registers_io           │
│  tools/         Визуализация и генерация документации схем                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Ядро: интерфейсы и реализации

```mermaid
classDiagram
    direction TB

    class ISchemaManager {
        <<interface>>
        +register(name, schema_class)
        +get_schema(name)
        +has_schema(name)
        +create_instance(name, data)
        +get_defaults(name)
        +validate(name, data)
        +list_schemas()
        +unregister(name)
        +clear()
    }

    class IStorageManager {
        <<interface>>
        +register_manager(manager_model)
        +get_manager_model(name, type)
        +update_manager_model(manager_model)
        +get_manager_config(type, name, key)
        +update_manager_config(...)
        +remove_manager(name)
        +list_managers()
    }

    class IVersionManager {
        <<interface>>
        +create_version(manager_model)
        +get_current_version(type, name)
        +get_version(type, name, version)
        +rollback(type, name, target_version)
        +get_version_history(type, name)
        +compare_versions(...)
    }

    class IDataConverter {
        <<interface>>
        +model_to_dict(model)
        +dict_to_model(data, model_class)
        +model_to_json(model)
        +json_to_model(json_str, model_class)
    }

    class IDataValidator {
        <<interface>>
        +validate(data, model_class)
        +is_valid(data, model_class)
        +get_validation_errors(data, model_class)
    }

    class SchemaManager {
        -_schemas: Dict
        -_instance: Singleton
        +get_instance()
        +register()
        +create_instance()
        +validate()
        ...
    }

    class StorageManager {
        -shared_resources
        -schema_registry
        +get_instance(shared_resources)
        +register_manager()
        +get_manager_model()
        +_get_process_data()
        ...
    }

    class VersionManager {
        -storage: IStorageManager
        +create_version()
        +rollback()
        ...
    }

    class DataConverter {
        +model_to_dict()
        +model_to_json()
        +model_to_yaml()
        +dict_to_model()
        +convert(from_type, to_type)
        ...
    }

    class DataValidator {
        +validate()
        +is_valid()
        +get_validation_errors()
    }

    ISchemaManager <|.. SchemaManager
    IStorageManager <|.. StorageManager
    IVersionManager <|.. VersionManager
    IDataConverter <|.. DataConverter
    IDataValidator <|.. DataValidator

    StorageManager --> SchemaManager : использует
    VersionManager --> IStorageManager : использует
```

**Назначение:**
- **SchemaManager** — единственная точка регистрации Pydantic-схем и создания экземпляров с дефолтами/валидацией.
- **StorageManager** — запись/чтение данных менеджеров в ProcessData; опирается на SchemaManager для моделей.
- **VersionManager** — версии и откат конфигов; работает поверх любого IStorageManager.
- **DataConverter** / **DataValidator** — преобразование и проверка одной модели (dict/json/yaml ↔ Pydantic).

---

## 3. Модели и фабрика

```mermaid
classDiagram
    direction TB

    BaseModel <|-- BaseComponentModel : Pydantic
    BaseModel <|-- BaseManagerModel : Pydantic
    BaseManagerModel <|-- UserConfigModel : пример приложения

    class BaseModel {
        <<pydantic>>
    }

    class BaseComponentModel {
        component_type
        component_class
        name, status
        metadata
        version, created_at
    }

    class BaseManagerModel {
        name
        config: Dict
        +model_dump()
        +model_validate()
    }

    class ModelFactory {
        <<static>>
        +create(schema_name, data)
        +create_manager(schema_name, manager_name, data)
        +from_dict(schema_name, data)
    }

    class register_schema {
        <<декоратор>>
        @register_schema("Name")
        class MyModel(BaseModel)
    }

    SchemaManager ..> BaseManagerModel : создаёт экземпляры
    ModelFactory --> SchemaManager : использует
    register_schema --> SchemaManager : регистрирует класс
```

**Назначение:**
- **BaseComponentModel** — базовая модель «компонента» (ДНК, тип, имя, метаданные).
- **BaseManagerModel** — базовая модель конфига менеджера (name, config).
- **ModelFactory** — создание экземпляров по имени схемы через SchemaManager.
- **register_schema** — декоратор для регистрации класса в SchemaManager.

---

## 4. Реестр и автообнаружение регистров

```mermaid
classDiagram
    direction LR

    class SchemaManager {
        _schemas: Dict~name, class~
        +register(name, model_class)
        +get_schema(name)
        +create_instance(name, data)
    }

    class register_schema {
        <<function>>
        декоратор для одного класса
    }

    class discover_registers_from_package {
        <<function>>
        +discover_registers_from_package(package_name)
        возвращает Dict~register_name, ModelClass~
    }

    class register_package_registers {
        <<function>>
        +register_package_registers(package_name, schema_registry?)
        discovery + регистрация в SchemaManager
    }

    register_schema --> SchemaManager : добавляет 1 схему
    discover_registers_from_package ..> SchemaManager : не вызывает
    register_package_registers --> discover_registers_from_package : вызывает
    register_package_registers --> SchemaManager : регистрирует все *Registers
```

**Назначение:**
- **register_schema** — ручная регистрация одной схемы (декоратор).
- **discover_registers_from_package** — сканирование пакета, поиск классов с суффиксом `*Registers`, возврат словаря имя → класс.
- **register_package_registers** — «мост»: discovery + массовая регистрация в SchemaManager (универсально для любого пакета/процесса).

---

## 5. Схема полей (FieldSchema) и ввод/вывод регистров (registers_io)

```mermaid
classDiagram
    direction TB

    class FieldSchema {
        -_schema: Dict
        +__init__(field_schema: Dict)
        +__call__(default_value, description, **overrides)
        +deep_merge(base, overrides)$
    }

    class PydanticField {
        <<pydantic Field>>
        default, description
        json_schema_extra
    }

    class registers_io {
        <<module functions>>
        +registers_to_dict(registers)
        +registers_from_dict(data, factory)
        +registers_to_json(registers)
        +registers_from_json(json_str, factory)
        +registers_to_yaml(...)
        +registers_from_yaml(...)
        +registers_to_flat_dict(registers, prefix)
        +registers_from_flat_dict(flat_dict, factory, prefix)
    }

    FieldSchema ..> PydanticField : возвращает
```

*Приложение передаёт словарь метаданных в `FieldSchema(dict)`; фреймворк не хранит дефолтную схему.*

**Назначение:**
- **FieldSchema** — приложение передаёт словарь метаданных (схему поля); экземпляр вызывается как `field_from_schema(default_value, description='', **overrides)` и возвращает `Field(..., json_schema_extra=merge(schema, overrides))`. Схема не зашита во фреймворк.
- **registers_io** — универсальные функции для объектов с `model_dump_all()` / `model_validate_all(data)`; фабрика создаёт новый экземпляр для from_*.

---

## 6. Storage, API и версионирование

```mermaid
flowchart LR
    subgraph App
        A[Process / SharedResources]
    end

    subgraph data_schema_module
        SM[StorageManager]
        VA[VersionManager]
        MA[ManagerDataAdapter]
        SR[SchemaManager]
        PD[(ProcessData)]
    end

    A -->|shared_resources| SM
    SM -->|get_instance(shared_resources)| SM
    SM -->|read/write| PD
    SM --> SR
    VA -->|использует IStorageManager| SM
    MA -->|StorageManager.get_instance()| SM
    MA -->|model read/write| SM
```

**Назначение:**
- **StorageManager** — единственная точка доступа к данным менеджеров в ProcessData; при необходимости использует SchemaManager для работы с моделями.
- **VersionManager** — версии и откат поверх StorageManager (опционально).
- **ManagerDataAdapter** — удобный доступ к данным одного менеджера (кэш модели, синхронизация с ProcessData через StorageManager).

---

## 7. Инструменты визуализации и документации

```mermaid
classDiagram
    direction TB

    class ISchemaVisualizer {
        <<interface>>
        +visualize_schema(name, format)
        +register_formatter(formatter)
        +list_formats()
    }

    class IVisualizationFormatter {
        <<interface>>
        +format(schema_name, schema_info)
        format_name
    }

    class SchemaVisualizer {
        -registry: SchemaManager
        -formatters: Dict
        +visualize_schema(name, format)
        +visualize_all_schemas()
        +register_formatter(IVisualizationFormatter)
    }

    class ISchemaDocumentationGenerator {
        <<interface>>
        +generate_documentation(name?, format)
        +register_formatter(formatter)
    }

    class IDocumentationFormatter {
        <<interface>>
        +format_schema(name, schema_info)
        +format_api_reference(schemas, schema_infos)
        format_name
    }

    class SchemaDocumentationGenerator {
        -registry: SchemaManager
        -formatters: Dict
        +generate_documentation()
        +register_formatter(IDocumentationFormatter)
    }

    ISchemaVisualizer <|.. SchemaVisualizer
    ISchemaDocumentationGenerator <|.. SchemaDocumentationGenerator
    SchemaVisualizer --> SchemaManager : читает схемы
    SchemaDocumentationGenerator --> SchemaManager : читает схемы
    SchemaVisualizer o-- IVisualizationFormatter : Strategy
    SchemaDocumentationGenerator o-- IDocumentationFormatter : Strategy
```

**Назначение:**
- **SchemaVisualizer** — визуализация одной или всех схем (text, json, html, mermaid и др.) через зарегистрированные форматеры (Strategy).
- **SchemaDocumentationGenerator** — генерация документации (markdown, rst, html и др.) через зарегистрированные форматеры.

---

## 8. Общий поток: от регистрации схем до использования

```mermaid
sequenceDiagram
    participant App
    participant register_schema
    participant register_package_registers
    participant SchemaManager
    participant ModelFactory
    participant StorageManager
    participant ProcessData

    App->>register_schema: @register_schema("Logger")\nclass LoggerModel(BaseModel)
    register_schema->>SchemaManager: register("Logger", LoggerModel)

    App->>register_package_registers: register_package_registers("App.Registers.models")
    register_package_registers->>SchemaManager: register("draw", DrawRegisters)\nregister("camera", CameraRegisters)...

    App->>ModelFactory: create("Logger", data)
    ModelFactory->>SchemaManager: create_instance("Logger", data)
    SchemaManager-->>App: instance

    App->>StorageManager: register_manager(manager_model)
    StorageManager->>ProcessData: save dict
    App->>StorageManager: get_manager_model(name, type)
    StorageManager->>ProcessData: read dict
    StorageManager->>SchemaManager: get_schema(type)
    SchemaManager-->>StorageManager: ModelClass
    StorageManager-->>App: BaseManagerModel
```

---

## 9. Где что лежит (краткая шпаргалка)

| Нужно | Класс/функция | Пакет |
|-------|----------------|--------|
| Зарегистрировать одну схему | `register_schema` (декоратор) | registry |
| Зарегистрировать все *Registers пакета | `register_package_registers(package_name)` | registry |
| Найти классы *Registers в пакете | `discover_registers_from_package(package_name)` | registry |
| Хранить и получать схемы, создавать экземпляры | `SchemaManager` | registry |
| Создать экземпляр по имени схемы | `ModelFactory.create(name, data)` | factory |
| Поля по схеме-словарю | `FieldSchema(schema_dict)(default_value, description, **overrides)` | utils.field_schema |
| Ввод/вывод набора регистров (dict/json/yaml/flat) | `registers_to_dict`, `registers_from_dict`, … | utils.registers_io |
| Конвертация одной модели (dict/json/yaml) | `DataConverter` | utils.converters |
| Валидация данных по модели | `DataValidator` | utils.validators |
| Хранение данных в ProcessData | `StorageManager` | storage |
| Версии и откат конфигов | `VersionManager` | versioning |
| Удобный доступ к данным менеджера | `ManagerDataAdapter` | api |
| Простое создание конфига без ProcessData | `create_config`, `create_manager_config` | api.simple_api |
| Визуализация схем | `SchemaVisualizer` | tools |
| Генерация документации схем | `SchemaDocumentationGenerator` | tools |

Модуль разделён по слоям (core → registry/storage/versioning → factory/api → utils/tools), без циклических зависимостей между пакетами; приложение задаёт только схемы (словари и пакеты для discovery) и использует единую точку входа — SchemaManager и фабрики/адаптеры поверх него.
