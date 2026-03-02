# data_schema_module

Универсальная система работы с данными на основе Pydantic v2.

---

## Архитектура

```
data_schema_module/
├── fields/                  # Ядро: FieldMeta + FieldRouting + RegisterBase
│   ├── field_meta.py        # FieldMeta — Annotated-дескриптор метаданных поля
│   ├── field_routing.py     # FieldRouting — типизированная маршрутизация
│   ├── field_types.py       # Готовые type aliases (Percent, HsvHue, Pixels, ...)
│   ├── register_mixin.py    # RegisterMixin — 5 секций методов (с кэшированием)
│   └── register_base.py     # RegisterBase = RegisterMixin + BaseModel
│
├── utils/
│   └── registers_container.py  # RegistersContainer — контейнер + IO + diff
│
├── registry/                # Реестр схем и авто-дискавери
│   ├── schema_registry.py   # SchemaManager Singleton + @register_schema
│   └── register_discovery.py  # discover_registers_from_package
│
├── storage/
│   ├── storage_manager.py   # StorageManager — хранение в ProcessData
│   └── file_storage.py      # FileStorage — JSON (реализует IRegisterStorage)
│
├── versioning/
│   └── version_manager.py   # VersionManager — история + откат конфигов
│
├── models/                  # Базовые модели компонентов
│   ├── base.py              # BaseComponentModel, BaseManagerModel
│   └── dna.py               # ComponentDNA — полное описание компонента
│
├── core/
│   ├── interfaces.py        # ABC + IRegisterStorage + IAsyncRegisterStorage (TODO)
│   └── exceptions.py        # Иерархия исключений
│
└── docs/examples/
    ├── 00_quickstart.py     # ← Начни здесь: весь стек за 5 минут
    ├── 01_basic_usage.py    # SchemaManager + ModelFactory
    ├── 04_field_meta_registers.py  # FieldMeta, RegisterBase, FileStorage
```

---

## Три типа моделей

| Тип | Базовый класс | Назначение |
|-----|--------------|------------|
| Регистры / конфиги | `RegisterBase` | Параметры с метаданными: UI, валидация, маршрутизация |
| Контейнеры данных | `BaseModel` | Вложенные структуры без UI-метаданных |
| Компоненты / ДНК | `BaseComponentModel` | Живые компоненты системы (для воссоздания) |

---

## Быстрый старт

```python
from typing import Annotated
from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta, FieldRouting, RegisterBase, RegistersContainer, FileStorage,
    # Готовые type aliases:
    Percent, HsvHue, HsvChannel, Pixels, Seconds, NormalizedFloat,
)

# FieldRouting: один объект — без повтора routing={"channel": "..."} в каждом поле
DRAW = FieldRouting(channel="control_draw")

class DrawRegisters(RegisterBase):
    dp: Annotated[float, FieldMeta(
        "Разрешение", min=0.1, max=20.0, routing=DRAW,
    )] = 1.4

class ProcessingRegisters(RegisterBase):
    hl: HsvHue = 0          # Annotated[int, FieldMeta("Hue", min=0, max=179)]
    hm: HsvHue = 179
    crop_top: Pixels = 0    # Annotated[int, FieldMeta("Пиксели", min=0, max=10000)]
    threshold: NormalizedFloat = 0.5

# Работа с полями
r = DrawRegisters()
r.dp                              # → 1.4  (plain float)
r.model_dump()                    # → {"dp": 1.4, "enabled": True}
r.update_field("dp", 2.0)        # → (True, None)
r.update_field("dp", 999.0)      # → (False, "Значение 999.0 больше максимального 20.0")

# Метаданные
DrawRegisters.get_field_meta("dp").max   # → 20.0
r.get_routing_channels()                  # → {"control_draw"}
r.get_fields_for_channel("control_draw") # → ["dp"]
```

---

## FieldMeta: все параметры

```python
FieldMeta(
    description="Краткое описание (UI-лейбл)",
    info="Подробное описание (UI-подсказка)",
    unit="px",                               # единица измерения
    min=0.0, max=100.0,                      # диапазон для числовых полей
    transfer_k=1.0,                          # шаг слайдера = 1/transfer_k
    round_k=2,                               # знаков после запятой
    routing=FieldRouting(channel="ctrl"),    # типизированная маршрутизация
    # routing={"channel": "ctrl"},           # или plain dict (обратная совместимость)
    access_level=0,
    readonly=False,
    hidden=False,
    description_i18n={"ru": "...", "en": "...", "de": "..."},
    info_i18n={"ru": "...", "en": "..."},
    examples=[1.0, 2.0, 5.0],
)
```

---

## FieldRouting: DRY маршрутизация

```python
# Без FieldRouting — повтор routing=dict в каждом поле:
dp: Annotated[float, FieldMeta("...", routing={"channel": "control_draw"})] = 1.4
minDist: Annotated[float, FieldMeta("...", routing={"channel": "control_draw"})] = 50.0

# С FieldRouting — один объект для всего регистра:
DRAW = FieldRouting(channel="control_draw", priority=1)

dp: Annotated[float, FieldMeta("...", routing=DRAW)] = 1.4
minDist: Annotated[float, FieldMeta("...", routing=DRAW)] = 50.0
```

---

## Готовые type aliases

```python
# Вместо повторного Annotated[int, FieldMeta("Hue", min=0, max=179)] — просто:
hl: HsvHue = 0

# Полный список:
Percent          # float, unit="%", min=0..100
NormalizedFloat  # float, min=0..1
Scale            # float, min=0.01..100
Milliseconds     # float, unit="мс"
Seconds          # float, unit="с"
Pixels           # int, unit="px", min=0..10000
ImageScale       # float, min=0.1..4.0 (для UI)
HsvHue           # int, min=0..179
HsvChannel       # int, min=0..255
NetworkPort      # int, min=1..65535
FpsLimit         # int, unit="кадр/с", min=0..480
```

---

## RegisterMixin: 5 секций методов (с кэшированием O(1))

```
1. Метаданные  — get_field_meta*, get_all_fields_meta*, get_field_metadata,
                 get_all_metadata, get_field_description, get_field_descriptions
2. Валидация   — validate_field, get_safe_value
3. Доступ      — can_modify_field, get_visible_fields, get_editable_fields,
                 get_fields_for_access_level
4. Маршрутизация — get_routing_channels, get_fields_for_channel
5. Значения    — update_field, values_dict

* — результат кэшируется per class / per (class, field) — O(1) после первого вызова
```

---

## RegistersContainer: единое состояние + дандеры + diff

```python
container = RegistersContainer({"draw": DrawRegisters, "processing": ProcessingRegisters})

# Атрибутный и индексный доступ (единый источник правды — _registers)
container.draw          # DrawRegisters instance
container["draw"]       # то же самое

# Коллекционные операции
"draw" in container     # True
len(container)          # 2
for name, reg in container: ...

# diff: узнать что изменилось (для эффективной синхронизации с Router)
snap = container.snapshot()
container.draw.update_field("dp", 5.0)
container.diff(snap)    # → {"draw": {"dp": 5.0}}

# IO
container.to_json()     # → JSON
container.from_json(s)  # загрузить in-place
container.to_yaml()     # → YAML (требует pyyaml)
```

---

## Персистентность через IRegisterStorage

```python
# Готово: FileStorage (JSON)
storage = FileStorage("data/registers")
container.save(storage, "main_process")
container.load(storage, "main_process")

# Будущие реализации (TODO: async_save/async_load для Redis, PostgreSQL):
class SQLiteStorage:
    def load(self, name: str) -> dict: ...
    def save(self, name: str, data: dict) -> None: ...
    def exists(self, name: str) -> bool: ...
    def delete(self, name: str) -> bool: ...
```

---

## Тестирование

```bash
# Тесты App/Registers (29 тестов)
cd Inspector_prototype
pytest App/Registers/tests/ -v

# Тесты фреймворка
cd multiprocess_framework/refactored/modules
pytest data_schema_module/tests/ -v

# Только новые тесты FieldMeta/RegisterMixin
pytest data_schema_module/tests/test_field_meta.py -v
```

---

## Примеры

- `docs/examples/00_quickstart.py` — **начни здесь**: весь стек за 5 минут
- `docs/examples/04_field_meta_registers.py` — детальный walkthrough FieldMeta
- `docs/examples/01_basic_usage.py` — SchemaManager, ModelFactory
