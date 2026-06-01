"""ModbusRegisters — все параметры и телеметрия Modbus-плагина.

V3_MY_PURE: register = единый источник параметров + FieldMeta для авто-генерации
config-виджета в инспекторе Pipeline/Plugins. Плагин всегда работает через self._reg.

Поля делятся на:
- параметры подключения (transport/host/port/...) — редактируются из GUI;
- параметры опроса (poll_*) и записи (write_*);
- телеметрия (readonly=True) — состояние соединения, ошибки, счётчики, последние
  значения. Это и есть «полноценная система»: статусы/ошибки видны в GUI вживую.
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("ModbusRegistersV1")
class ModbusRegisters(SchemaBase):
    """Параметры и телеметрия драйвера Modbus."""

    # --- Подключение ---
    transport: Annotated[str, FieldMeta("Транспорт", info="tcp | rtu (RS485)")] = "tcp"
    host: Annotated[str, FieldMeta("Хост", info="IP/hostname (TCP)")] = "127.0.0.1"
    port: Annotated[int, FieldMeta("Порт", info="TCP-порт Modbus", min=1, max=65535)] = 502
    serial_port: Annotated[str, FieldMeta("COM-порт", info="Порт RS485 (RTU)")] = "COM1"
    baudrate: Annotated[int, FieldMeta("Скорость", info="Бод (RTU)", min=1200, max=921600)] = 9600
    unit_id: Annotated[int, FieldMeta("Unit ID", info="Адрес ведомого", min=0, max=247)] = 1
    timeout_sec: Annotated[float, FieldMeta("Таймаут", info="сек", unit="s", min=0.1, max=60.0)] = 3.0
    auto_connect: Annotated[bool, FieldMeta("Автоподключение", info="Подключаться при старте")] = True

    # --- Опрос (чтение → телеметрия/pipeline) ---
    poll_interval_ms: Annotated[int, FieldMeta("Период опроса", info="мс", unit="ms", min=10, max=60000)] = 200
    poll_kind: Annotated[str, FieldMeta("Тип регистров", info="holding|input|coils|discrete")] = "holding"
    poll_address: Annotated[int, FieldMeta("Адрес опроса", min=0, max=65535)] = 0
    poll_count: Annotated[int, FieldMeta("Кол-во регистров", min=1, max=125)] = 10

    # --- Запись (выход → PLC) ---
    write_enabled: Annotated[bool, FieldMeta("Запись в PLC", info="Писать поле результата в регистр")] = False
    write_address: Annotated[int, FieldMeta("Адрес записи", min=0, max=65535)] = 0
    write_field: Annotated[str, FieldMeta("Поле результата", info="Ключ item → значение регистра")] = "verdict"

    # --- Телеметрия (readonly) ---
    conn_state: Annotated[str, FieldMeta("Состояние", readonly=True)] = "disconnected"
    last_error: Annotated[str, FieldMeta("Последняя ошибка", readonly=True)] = ""
    reads_ok: Annotated[int, FieldMeta("Чтений OK", readonly=True)] = 0
    writes_ok: Annotated[int, FieldMeta("Записей OK", readonly=True)] = 0
    total_errors: Annotated[int, FieldMeta("Ошибок всего", readonly=True)] = 0
    last_values: Annotated[str, FieldMeta("Последние значения", readonly=True)] = ""
