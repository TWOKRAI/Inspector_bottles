# Быстрая справка для AI: data_schema_module

## Принцип работы модуля

**Цель:** Универсальная система работы с Pydantic-моделями (схемами данных) для любого процесса/приложения.

**Подход:** Гибридный — dict в ProcessData (для межпроцессного обмена), Pydantic модели в коде (для валидации и типизации).

## Основные компоненты и их роль

### 1. SchemaManager (registry/schema_registry.py)
**Что делает:** Единственная точка регистрации Pydantic-схем и создания экземпляров с дефолтами/валидацией.

**Как работает:**
- Singleton: `SchemaManager.get_instance()`
- Регистрация: `register(name, ModelClass)` или декоратор `@register_schema("name")`
- Создание: `create_instance("name", data={...})` — создаёт экземпляр с дефолтами из модели
- Валидация: `validate("name", data)` — проверяет данные по схеме

**Пример:**
```python
registry = SchemaManager.get_instance()
registry.register("Logger", LoggerModel)
obj = registry.create_instance("Logger", {"level": "DEBUG"})  # дефолты подставятся автоматически
```

### 2. FieldSchema (utils/field_schema.py)
**Что делает:** Создаёт Pydantic `Field` из словаря-схемы (метаданные: min, max, unit, info и т.д.).

**Как работает:**
- Приложение передаёт словарь схемы в `__init__`
- Экземпляр вызывается как поле: `field_from_schema(default_value, description='', **overrides)`
- Фреймворк мержит базовую схему с переопределениями и возвращает `Field(...)`

**Пример:**
```python
schema = {"min": 0, "max": 100, "unit": "px"}
fs = FieldSchema(schema)
width: int = fs(640, description="Ширина", min=320, max=1920)  # переопределили min/max
```

### 3. register_package_registers (registry/register_discovery.py)
**Что делает:** Автоматически находит классы `*Registers` в пакете и регистрирует их в SchemaManager.

**Как работает:**
- Сканирует пакет (например, `"App.Registers.models"`)
- Находит классы с суффиксом `Registers` (например, `DrawRegisters`)
- Преобразует имя: `DrawRegisters` → `"draw"`
- Регистрирует в SchemaManager: `registry.register("draw", DrawRegisters)`

**Пример:**
```python
register_package_registers("App.Registers.models")  # все *Registers зарегистрированы
```

### 4. registers_io (utils/registers_io.py)
**Что делает:** Универсальный ввод/вывод объектов с методами `model_dump_all()` и `model_validate_all(data)`.

**Как работает:**
- Работает с любым объектом, у которого есть эти два метода
- Форматы: dict, JSON, YAML, flat_dict (для рецептов)
- Для импорта нужна фабрика: `registers_from_json(json_str, factory=RegistersManager)`

**Пример:**
```python
json_str = registers_to_json(registers_manager)
loaded = registers_from_json(json_str, factory=RegistersManager)
```

### 5. ModelFactory (factory/model_factory.py)
**Что делает:** Создаёт экземпляры моделей менеджеров с автоматическим заполнением обязательных полей.

**Как работает:**
- Использует SchemaManager для получения схемы
- Автоматически добавляет `component_class`, `name`, `component_type` для BaseManagerModel
- Может автоматически регистрировать в StorageManager (ProcessData)

**Пример:**
```python
model = ModelFactory.create_manager("LoggerManager", "main_logger", data={"level": "DEBUG"})
```

## Взаимосвязи компонентов

```
┌─────────────────────────────────────────────────────────────┐
│                    Приложение (App)                         │
│  - Определяет модели *Registers (Pydantic BaseModel)        │
│  - Определяет DEFAULT_FIELD_SCHEMA (словарь метаданных)     │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              data_schema_module (фреймворк)                  │
│                                                              │
│  ┌──────────────┐      ┌──────────────┐                    │
│  │ FieldSchema  │      │register_     │                    │
│  │              │      │package_      │                    │
│  │ Принимает    │      │registers     │                    │
│  │ схему из App │      │              │                    │
│  │ → Field(...) │      │ Discovery +  │                    │
│  └──────────────┘      │ регистрация  │                    │
│                        └──────┬───────┘                    │
│                               │                             │
│                        ┌──────▼───────┐                    │
│                        │SchemaManager │                    │
│                        │              │                    │
│                        │ Реестр схем  │                    │
│                        │ Создание     │                    │
│                        │ экземпляров  │                    │
│                        └──────┬───────┘                    │
│                               │                             │
│  ┌──────────────┐      ┌──────▼───────┐                    │
│  │ registers_io │      │ ModelFactory  │                    │
│  │              │      │               │                    │
│  │ dict/json/   │      │ create_manager│                    │
│  │ yaml/flat    │      │ from_dict     │                    │
│  └──────────────┘      └───────────────┘                    │
└─────────────────────────────────────────────────────────────┘
```

## Типичный workflow

1. **Приложение определяет модели:**
   ```python
   # App/Registers/models/draw.py
   from multiprocess_framework.modules.data_schema_module import FieldSchema
   from App.Registers.models.data_schema.field_schema import DEFAULT_FIELD_SCHEMA
   
   field_from_schema = FieldSchema(DEFAULT_FIELD_SCHEMA)
   
   class DrawRegisters(BaseModel):
       dp: float = field_from_schema(1.4, description='Разрешение', min=0.1, max=20.0)
   ```

2. **Авторегистрация при старте:**
   ```python
   # App/Registers/__init__.py или при инициализации
   from multiprocess_framework.modules.data_schema_module import register_package_registers
   register_package_registers("App.Registers.models")  # все *Registers в SchemaManager
   ```

3. **Использование:**
   ```python
   # Создание через ModelFactory
   from multiprocess_framework.modules.data_schema_module import ModelFactory
   draw = ModelFactory.create("draw", {"dp": 2.0})
   
   # Или напрямую через SchemaManager
   from multiprocess_framework.modules.data_schema_module import SchemaManager
   registry = SchemaManager.get_instance()
   draw = registry.create_instance("draw", {"dp": 2.0})
   ```

## Ключевые принципы

1. **Фреймворк не знает про App** — приложение передаёт схемы и пакеты для discovery
2. **Один термин — SchemaManager** (не SchemaRegistry)
3. **registers_io универсален** — работает с любым объектом с `model_dump_all`/`model_validate_all`
4. **FieldSchema принимает схему из App** — фреймворк только мержит и возвращает Field
5. **Автообнаружение опционально** — можно регистрировать вручную через `@register_schema`

## Где что находится

- **Регистрация схем:** `registry/schema_registry.py` → `SchemaManager`
- **Автообнаружение:** `registry/register_discovery.py` → `register_package_registers`
- **Поля по схеме:** `utils/field_schema.py` → `FieldSchema`
- **Ввод/вывод регистров:** `utils/registers_io.py` → `registers_to_json`, `registers_from_json` и т.д.
- **Создание моделей:** `factory/model_factory.py` → `ModelFactory`
- **Хранение в ProcessData:** `storage/storage_manager.py` → `StorageManager`

## Для AI: как понять модуль без чтения всех файлов

1. **Начните с README.md** — там минимальный путь и основные возможности
2. **Посмотрите DIAGRAMS.md** — визуализация связей между компонентами
3. **Используйте QUICK_REFERENCE.md** (этот файл) — краткое описание принципов
4. **STRUCTURE.md** — детальная структура пакетов

**Главное:** Модуль разделён по слоям (core → registry/storage → factory/api → utils/tools), без циклических зависимостей. Приложение задаёт только схемы и пакеты; фреймворк предоставляет универсальные инструменты.
