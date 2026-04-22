# Registers — Архитектура

## Ответственность
**Единственный источник истины о состоянии системы.** Все регистры — это Pydantic-модели с rich-metadata (описание, min/max, уровень доступа, маршрут IPC). Данные моделей (камеры, регионы, цепочки) — тоже Pydantic, но без UI-metadata.

Никакого UI-кода, никаких Qt-объектов, никаких побочных эффектов при создании модели.

---

## Структура

```
Registers/
├── __init__.py               # Экспортирует всё: модели регистров, данных, RegistersManager
├── manager.py                # RegistersManager — наблюдатель + IPC-хуки поверх RegistersContainer
├── README.md                 # Инструкция по использованию
├── ARCHITECTURE.md           # (этот файл)
├── models/
│   ├── registers/            # Регистры состояния: поля с FieldMeta (UI/IPC-metadata)
│   │   ├── draw.py           # DrawRegisters — параметры HoughCircles
│   │   ├── camera.py         # CameraRegisters — источник, запись видео, режимы
│   │   ├── processing.py     # ProcessingRegisters — HSV, обрезка, регионы
│   │   ├── post_processing.py# PostProcessingRegisters — регионы, цепочки, режим просмотра
│   │   ├── visual.py         # VisualRegisters — масштаб изображения
│   │   ├── robot.py          # RobotRegisters — параметры робота
│   │   ├── neuroun.py        # NeurounRegisters — параметры нейросети
│   │   ├── hikvision.py      # HikvisionRegisters — IP, порт, авторизация
│   │   ├── conveyor.py       # ConveyorRegisters — конвейер
│   │   └── frame_process.py  # FrameProcessRegisters — FPS-лимит
│   └── data/                 # Структуры данных: чистые Pydantic BaseModel (без FieldMeta)
│       ├── camera.py         # CameraData — имя камеры, регионы, параметры Hikvision
│       ├── region.py         # RegionData — координаты ROI, цепочки обработки
│       └── chain.py          # ChainStepData — шаг цепочки: processor_id + params
└── tests/
    └── test_registers.py     # Smoke-тесты: создание RegistersManager, metadata
```

---

## Два типа моделей

### Регистры (`models/registers/`)
Поля типа `Annotated[T, FieldMeta(...)]` — несут UI-metadata и маршрут IPC.

```python
class DrawRegisters(RegisterBase):
    dp: Annotated[float, FieldMeta(
        description="Разрешение аккумулятора",
        min_value=1.0, max_value=5.0,
        access_level=0,
        routing=FieldRouting(channel="control_draw"),
    )] = 1.2
```

### Данные (`models/data/`)
Чистые `BaseModel` — структуры для хранения, без UI-metadata.

```python
class CameraData(BaseModel):
    name: str
    regions: Dict[str, RegionData] = {}
    hikvision_params: Dict[str, Any] = {}
```

---

## RegistersManager

| Возможность | Описание |
|-------------|----------|
| `subscribe(reg, field, cb)` | Подписка на изменение конкретного поля |
| `subscribe_all(cb)` | Подписка на все изменения |
| `set_field_value(reg, field, val)` | Запись значения + уведомление наблюдателей |
| `get_field_metadata(reg, field)` | Получить `FieldInfo` с metadata |
| `get_field_description(reg, field)` | Получить текстовое описание поля |
| `notify_field_changed(reg, field)` | Принудительное уведомление (для IPC-синхронизации) |

---

## Правила

- **Никакого UI** в Registers. Если нужна реакция UI — подпишитесь через `subscribe()`.
- **Никакой логики** в моделях. Модель — только структура данных + валидация Pydantic.
- `RegistersManager` — единственный объект, через который читают/пишут регистры.
- `DataManager` управляет `CameraData`/`RegionData` — это другой уровень (структуры данных, не регистры состояния).
