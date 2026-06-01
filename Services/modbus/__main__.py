"""CLI-smoke драйвера Modbus — ручная проверка против устройства/симулятора.

Примеры::

    # Прочитать 10 holding-регистров с TCP-устройства
    python -m Services.modbus --tcp 127.0.0.1:5020 read 0 10

    # Записать значение 42 в регистр 0
    python -m Services.modbus --tcp 127.0.0.1:5020 write 0 42

    # RS485 (RTU)
    python -m Services.modbus --rtu COM3:9600 read 0 5

Для поднятия локального тестового сервера: ``python -m pymodbus.server`` или
встроенный simulator pymodbus.
"""

from __future__ import annotations

import argparse
import sys

from Services.modbus.core.config import ModbusConfig, TransportType
from Services.modbus.core.device import ModbusDevice
from Services.modbus.sdk import MODBUS_AVAILABLE


def _build_config(args: argparse.Namespace) -> ModbusConfig:
    """Собрать ModbusConfig из аргументов --tcp/--rtu."""
    if args.tcp:
        host, _, port = args.tcp.partition(":")
        return ModbusConfig(
            transport=TransportType.TCP,
            host=host,
            port=int(port or 502),
            unit_id=args.unit,
        )
    serial_port, _, baud = args.rtu.partition(":")
    return ModbusConfig(
        transport=TransportType.RTU,
        serial_port=serial_port,
        baudrate=int(baud or 9600),
        unit_id=args.unit,
    )


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    parser = argparse.ArgumentParser(prog="python -m Services.modbus")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--tcp", metavar="HOST:PORT", help="Modbus-TCP адрес")
    target.add_argument("--rtu", metavar="PORT:BAUD", help="Modbus-RTU (RS485) порт")
    parser.add_argument("--unit", type=int, default=1, help="Unit/slave id (по умолчанию 1)")

    sub = parser.add_subparsers(dest="cmd", required=True)
    p_read = sub.add_parser("read", help="Читать holding-регистры")
    p_read.add_argument("address", type=int)
    p_read.add_argument("count", type=int, nargs="?", default=1)
    p_write = sub.add_parser("write", help="Записать holding-регистр")
    p_write.add_argument("address", type=int)
    p_write.add_argument("value", type=int)

    args = parser.parse_args(argv)

    if not MODBUS_AVAILABLE:
        print("ОШИБКА: pymodbus не установлен. Установите: pip install '.[modbus]'", file=sys.stderr)
        return 2

    config = _build_config(args)
    device = ModbusDevice(
        config,
        on_status=lambda s: print(f"[status] {s['state']} err={s['last_error']!r}"),
        on_error=lambda m: print(f"[error] {m}", file=sys.stderr),
    )

    print(f"Подключение к {config.describe()} ...")
    if not device.connect():
        print("Не удалось подключиться", file=sys.stderr)
        return 1

    try:
        if args.cmd == "read":
            values = device.read_holding(args.address, args.count)
            print(f"holding[{args.address}..{args.address + args.count - 1}] = {values}")
        else:
            device.write_register(args.address, args.value)
            print(f"write holding[{args.address}] = {args.value} OK")
    finally:
        print(f"Статус: {device.get_status()}")
        device.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
