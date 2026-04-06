# Модуль registers_module

## Назначение

Рантайм-контейнер **именованных регистров** (экземпляры Pydantic/`SchemaBase` из приложения): чтение/запись полей, метаданные для UI, экспорт `model_dump_all`, доставка изменений в бэкенд (`register_update`), построение карт маршрутизации и `connection_map`.

## Импорты

Используйте только публичный API пакета:

```python
from registers_module import (
    RegistersManager,
    build_connection_map_from_registers,
    build_routing_map,
    get_routing_for_message,
    send_register_message,
    IRegistersManager,
)
```

## Точки входа

| Символ | Описание |
|--------|----------|
| `RegistersManager` | Словарь имя → экземпляр регистра; подписки, `set_field_value`, `model_dump_all` / `model_validate_all` |
| `build_connection_map_from_registers` | `{register_name: process_name}` из `register_dispatch` на классах |
| `build_routing_map` / `get_routing_for_message` / `send_register_message` | Карта (register, field) → channel и отправка через роутер |

## Зависимости

- **Зависит от:** типов моделей не импортирует; использует duck typing (`model_dump`, `model_fields`, опционально `register_dispatch`, `FieldMeta` через приложение).
- **Используется в:** `frontend_module`, прототипах Inspector.

## Структура

```
registers_module/
├── __init__.py
├── interfaces.py
├── README.md
├── STATUS.md
├── core/
│   ├── manager.py
│   ├── connection_map_builder.py
│   └── routing_map.py
└── tests/
```

## Примечания

- Миграции снимков legacy YAML — на границе приложения, не в этом модуле.
