"""Задержка ответа ``fault.delay_ms`` — нижняя граница по точным часам (раунд 3, sim-win).

Инъектор неисправности обязан задержать ответ НЕ меньше заказанного. Цикл asyncio на Windows
живёт на грубых часах (15.625 мс) и в часто просыпающемся цикле будит ``asyncio.sleep`` раньше
срока — тест гонит настоящий биндер в таком цикле и меряет ``perf_counter``.
Тонкая поломка (дедлайн добора на ``time.monotonic``) ловится в 10 прогонах из 10 (см. фазовую паузу).
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from Services.robot_comm.core.registers import REG_SPACE_SIZE
from Services.robot_comm.server import sim_robot
from Services.robot_comm.server.sim_core import RobotSimCore

pytestmark = pytest.mark.skipif(not sim_robot.MODBUS_AVAILABLE, reason="pymodbus не установлен")

_DELAY_S = 0.03
_SAMPLES = 120


async def _measure_binder_delays() -> list[float]:
    binder = sim_robot._make_register_binder(RobotSimCore(), threading.Event(), delay_source=lambda: _DELAY_S)
    registers = [0] * REG_SPACE_SIZE
    stop = asyncio.Event()

    async def ticker() -> None:  # цикл просыпается каждую миллисекунду, как у занятого сервера
        while not stop.is_set():
            await asyncio.sleep(0.001)

    ticking = asyncio.create_task(ticker())
    elapsed: list[float] = []
    for _ in range(_SAMPLES):
        started = time.perf_counter()
        await binder(3, 0, 0, 1, registers, None)
        elapsed.append(time.perf_counter() - started)
        # Сбиваем фазу относительно сетки тиков часов: без паузы каждый замер стартует в ту же
        # долю тика, и тонкая поломка (дедлайн на time.monotonic) видна лишь в единичных замерах.
        await asyncio.sleep(0.0007)
    stop.set()
    await ticking
    return elapsed


def test_binder_delay_is_never_shorter_than_configured_in_a_busy_loop() -> None:
    result: dict[str, list[float]] = {}
    errors: list[BaseException] = []

    def _run() -> None:
        try:
            result["elapsed"] = asyncio.run(asyncio.wait_for(_measure_binder_delays(), timeout=30))
        except BaseException as exc:  # noqa: BLE001 — показать любую причину, а не повесить прогон
            errors.append(exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=40)
    assert not thread.is_alive(), "замер задержки не завершился за 40 с"
    assert not errors, errors
    short = [round(x, 4) for x in result["elapsed"] if x < _DELAY_S]
    assert short == [], f"задержка короче заказанной {_DELAY_S} с: {len(short)} из {_SAMPLES}, {short[:5]}"
