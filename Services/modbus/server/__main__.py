"""CLI тестового Modbus-slave — запуск приёмника в отдельном терминале.

Примеры::

    # Поднять TCP-slave на 127.0.0.1:5020 (порт 5020, не 502 — без admin)
    python -m Services.modbus.server --tcp 127.0.0.1:5020

    # С другим unit id и размером блока регистров
    python -m Services.modbus.server --tcp 0.0.0.0:5020 --unit 2 --size 512

После запуска при каждой записи мастера в holding-регистры в терминал печатается
строка вида ``[16:21:07] recv holding[100..102] = [640, 480, 1234]``.
"""

from __future__ import annotations

import argparse
import sys

from Services.modbus.server.sim_server import MODBUS_AVAILABLE, run_test_server


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    parser = argparse.ArgumentParser(prog="python -m Services.modbus.server")
    parser.add_argument(
        "--tcp",
        metavar="HOST:PORT",
        default="127.0.0.1:5020",
        help="адрес прослушивания (по умолчанию 127.0.0.1:5020)",
    )
    parser.add_argument("--unit", type=int, default=1, help="unit/slave id (по умолчанию 1)")
    parser.add_argument("--size", type=int, default=256, help="размер блока holding-регистров")
    args = parser.parse_args(argv)

    if not MODBUS_AVAILABLE:
        print("ОШИБКА: pymodbus не установлен. Установите: pip install '.[modbus]'", file=sys.stderr)
        return 2

    host, _, port = args.tcp.partition(":")
    run_test_server(host=host, port=int(port or 5020), unit_id=args.unit, size=args.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
