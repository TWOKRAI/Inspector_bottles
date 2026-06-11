"""Запуск РАБОЧЕГО REPL robot/universal3/pc_full.py против симулятора робота.

«Смоделировать universal3 как он рабочий»: поднимает in-process фейк-робота
(тот же `sim_core`, что используют новые сервисы) и направляет на него
ОТЛАЖЕННЫЙ консольный клиент из `robot/universal3/pc_full.py` — без железа.

Так можно вживую погонять проверенную программу (pos / <x> <y> / r 50 / vfd /
s / params / state) и убедиться, что симулятор ведёт себя как реальный робот.
Поскольку новые сервисы говорят с роботом байт-в-байт тем же протоколом
(см. Services/robot_comm/tests/test_parity_universal3.py), это же подтверждает
их пригодность.

Запуск из корня:
    python scripts/robot_ref_against_sim.py

Команды REPL (как на реальном роботе):
    pos              позиция X/Y
    <x> <y>          поставить CVT-задание (напр. 120.5 -40)
    enc | state | params | last
    r [Гц] | rev [Гц] | f <Гц> | s | reset | vfd     — частотник (лента)
    q                выход
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PC_FULL = _ROOT / "robot" / "universal3" / "pc_full.py"

SIM_HOST = "127.0.0.1"
SIM_PORT = 5021


def _load_reference():
    """Загрузить robot/universal3/pc_full.py по пути (он не пакет)."""
    if not _PC_FULL.exists():
        raise SystemExit(f"Не найден рабочий эталон: {_PC_FULL}")
    spec = importlib.util.spec_from_file_location("pc_full_ref", _PC_FULL)
    module = importlib.util.module_from_spec(spec)
    sys.modules["pc_full_ref"] = module  # нужно для @dataclass в модуле
    spec.loader.exec_module(module)
    return module


def main() -> None:
    """Поднять sim и запустить рабочий REPL, направленный на него."""
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

    from Services.robot_comm.server.sim_robot import SimRobotServer

    server = SimRobotServer(SIM_HOST, SIM_PORT)
    server.start()
    time.sleep(0.6)  # дать серверу подняться
    print(f"[sim] фейк-робот слушает {SIM_HOST}:{SIM_PORT} (карта universal3 + зеркало ПЧ)")

    ref = _load_reference()
    # Направить отлаженный клиент на симулятор вместо железа.
    ref.ROBOT_IP = SIM_HOST
    ref.ROBOT_PORT = SIM_PORT
    print(f"[ref] запускаю рабочий REPL pc_full.py против {SIM_HOST}:{SIM_PORT}\n")

    try:
        ref.console()  # интерактивный REPL рабочего клиента
    finally:
        server.stop()
        print("\n[sim] остановлен.")


if __name__ == "__main__":
    main()
