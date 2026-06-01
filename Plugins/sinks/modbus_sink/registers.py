"""ModbusSinkRegisters — параметры и телеметрия плагина modbus_sink.

register = единый источник runtime-параметров + FieldMeta для авто-генерации
config-виджета в инспекторе Pipeline/Plugins. Плагин всегда работает через self._reg.

Универсальный пакет: поле ``payload`` (list[dict]) описывает, какие значения из item
и в каком порядке писать в holding-регистры. Любые данные, любое количество.
Каждая запись payload:
    source: ключ item (например "width", "frame_id", "detections")
    reduce: для списков — "count" | "sum" | "max" | "min" (без reduce → скаляр)
    field:  ключ внутри элементов списка для sum/max/min (по умолчанию "area")
    dtype:  "u16" (1 регистр, деф.) | "u32" (2 регистра)
"""

from __future__ import annotations

from typing import Annotated, Any

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)

# Дефолтный пакет: размер кадра + id + метрики блобов (count / суммарная и макс. площадь).
# Адреса base..base+2 = width/height/frame_id (совместимо с прежним фикс-форматом).
_DEFAULT_PAYLOAD: list[dict[str, Any]] = [
    {"source": "width"},
    {"source": "height"},
    {"source": "frame_id"},
    {"source": "detections", "reduce": "count"},
    {"source": "detections", "reduce": "sum", "field": "area", "dtype": "u32"},
    {"source": "detections", "reduce": "max", "field": "area", "dtype": "u32"},
]


@register_schema("ModbusSinkRegistersV2")
class ModbusSinkRegisters(SchemaBase):
    """Параметры и телеметрия sink-плагина Modbus (универсальный вывод по payload)."""

    # --- Подключение ---
    transport: Annotated[str, FieldMeta("Транспорт", info="tcp | rtu (RS485)")] = "tcp"
    host: Annotated[str, FieldMeta("Хост", info="IP/hostname приёмника (TCP)")] = "127.0.0.1"
    port: Annotated[int, FieldMeta("Порт", info="TCP-порт Modbus", min=1, max=65535)] = 5020
    serial_port: Annotated[str, FieldMeta("COM-порт", info="Порт RS485 (RTU)")] = "COM1"
    baudrate: Annotated[int, FieldMeta("Скорость", info="Бод (RTU)", min=1200, max=921600)] = 9600
    unit_id: Annotated[int, FieldMeta("Unit ID", info="Адрес ведомого", min=0, max=247)] = 1
    timeout_sec: Annotated[float, FieldMeta("Таймаут", info="сек", unit="s", min=0.1, max=60.0)] = 3.0
    auto_connect: Annotated[bool, FieldMeta("Автоподключение", info="Подключаться при старте")] = True

    # --- Что и как писать ---
    base_address: Annotated[
        int,
        FieldMeta("Базовый адрес", info="Старт holding-регистров для пакета", min=0, max=65532),
    ] = 100
    word_order: Annotated[str, FieldMeta("Порядок слов u32", info="big (Modbus-стандарт) | little")] = "big"
    write_every_n: Annotated[int, FieldMeta("Писать каждый N-й кадр", info="1 = каждый кадр", min=1, max=10000)] = 1
    payload: Annotated[
        list[dict],
        FieldMeta(
            "Пакет (payload)",
            info="Список значений: source/reduce/field/dtype → регистры по порядку",
        ),
    ] = _DEFAULT_PAYLOAD

    # --- Телеметрия (readonly) ---
    conn_state: Annotated[str, FieldMeta("Состояние", readonly=True)] = "disconnected"
    last_error: Annotated[str, FieldMeta("Последняя ошибка", readonly=True)] = ""
    frames_seen: Annotated[int, FieldMeta("Кадров получено", readonly=True)] = 0
    writes_ok: Annotated[int, FieldMeta("Записей OK", readonly=True)] = 0
    last_written: Annotated[str, FieldMeta("Последние регистры", readonly=True)] = ""
