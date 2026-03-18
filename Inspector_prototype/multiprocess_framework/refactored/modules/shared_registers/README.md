# shared_registers — Общие регистры

## Назначение

Единая папка со схемами регистров для backend и frontend. Оба слоя импортируют регистры отсюда — один источник истины для параметров, аннотаций и маршрутизации.

## Импорты

```python
from shared_registers import DrawRegisters
from shared_registers.draw import DrawRegisters, DRAW_ROUTING
```

## Использование

**Backend (Processor, Renderer):**
- RegistersManager/RegistersContainer с экземплярами DrawRegisters
- routing_map.build_routing_map() использует FieldMeta.routing для маршрутизации

**Frontend (frontend_module):**
- Виджеты привязываются к (register_name="draw", field_name="dp")
- get_field_metadata() для UI (label, min, max, unit)

## Структура

```
shared_registers/
├── __init__.py    # Экспорт всех регистров
├── README.md
├── draw.py        # DrawRegisters (HoughCircles)
├── camera.py      # (планируется)
├── processing.py  # (планируется)
└── ...
```

## Зависимости

- **Зависит от:** `data_schema_module` (SchemaBase, FieldMeta, FieldRouting)
- **Используется в:** `registers_module`, `frontend_module`, `multiprocess_prototype`
