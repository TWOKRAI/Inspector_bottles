"""ModbusSinkRegisters — параметры и телеметрия плагина modbus_sink.

register = единый источник runtime-параметров + FieldMeta для авто-генерации
config-виджета в инспекторе Pipeline/Plugins. Плагин всегда работает через self._reg.

Поля: подключение (transport/host/port/...), что и куда писать (base_address,
write_every_n) и телеметрия (readonly) — состояние, ошибки, счётчики.
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("ModbusSinkRegistersV1")
class ModbusSinkRegisters(SchemaBase):
    """Параметры и телеметрия sink-плагина Modbus (вывод метаданных кадра)."""

    # --- Подключение ---
    transport: Annotated[str, FieldMeta("Транспорт", info="tcp | rtu (RS485)")] = "tcp"
    host: Annotated[str, FieldMeta("Хост", info="IP/hostname приёмника (TCP)")] = "127.0.0.1"
    port: Annotated[int, FieldMeta("Порт", info="TCP-порт Modbus", min=1, max=65535)] = 5020
    serial_port: Annotated[str, FieldMeta("COM-порт", info="Порт RS485 (RTU)")] = "COM1"
    baudrate: Annotated[int, FieldMeta("Скорость", info="Бод (RTU)", min=1200, max=921600)] = 9600
    unit_id: Annotated[int, FieldMeta("Unit ID", info="Адрес ведомого", min=0, max=247)] = 1
    timeout_sec: Annotated[float, FieldMeta("Таймаут", info="сек", unit="s", min=0.1, max=60.0)] = 3.0
    auto_connect: Annotated[bool, FieldMeta("Автоподключение", info="Подключаться при старте")] = True

    # --- Что писать ---
    base_address: Annotated[
        int,
        FieldMeta("Базовый адрес", info="holding[base..base+2] = [width, height, frame_id]", min=0, max=65532),
    ] = 100
    write_every_n: Annotated[
        int,
        FieldMeta("Писать каждый N-й кадр", info="1 = каждый кадр", min=1, max=10000),
    ] = 1

    # --- Телеметрия (readonly) ---
    conn_state: Annotated[str, FieldMeta("Состояние", readonly=True)] = "disconnected"
    last_error: Annotated[str, FieldMeta("Последняя ошибка", readonly=True)] = ""
    frames_seen: Annotated[int, FieldMeta("Кадров получено", readonly=True)] = 0
    writes_ok: Annotated[int, FieldMeta("Записей OK", readonly=True)] = 0
    last_written: Annotated[str, FieldMeta("Последняя запись", readonly=True)] = ""
