"""CLI: поднять TCP-симулятор робота.

Примеры::

    python -m Services.robot_comm.server
    python -m Services.robot_comm.server --host 0.0.0.0 --port 502
"""

from __future__ import annotations

import argparse

from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.server.sim_robot import DEFAULT_HOST, DEFAULT_PORT, run_sim_robot


def main() -> None:
    """Точка входа CLI симулятора."""
    parser = argparse.ArgumentParser(description="Фейк-робот Delta (Modbus-TCP slave, карта universal3)")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--unit", type=int, default=ROBOT_UNIT_ID)
    args = parser.parse_args()
    run_sim_robot(args.host, args.port, args.unit)


if __name__ == "__main__":
    main()
