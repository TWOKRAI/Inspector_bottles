# -*- coding: utf-8 -*-
"""T3.8 (фикс 1): частота ``sim.robot.state`` на реальных часах Windows.

``time.monotonic`` там — GetTickCount64 с шагом 1/64 с, к нему добавляется дрожание ``sleep``
воркера. Слепой ``test_rate_key`` берёт идеальные часы и этого не ловит: допуск ``1e-9`` на
таких часах терял каждый второй цикл (20 Гц при 50 мс давали 10). Здесь часы фейковые, но
квантованы и с дрожанием; ожидания — литералы. Также: неверные значения ключа (включая
``10**400``, ``nan``, ``inf``) — ровно один отказ в health, публикации нет, энкодер работает.
"""

from __future__ import annotations

import math
import random
from typing import Any

import pytest

from Plugins.sim.robot_host.tests.host_harness import HOST, ThreadWorkerManager, free_port
from Plugins.sim.robot_host.plugin import SimRobotHostPlugin
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Services.robot_comm import ROBOT_AVAILABLE
from Services.robot_comm.core.registers import ROBOT_UNIT_ID

pytestmark = pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен")

_ROBOT_STATE = "sim.robot.state"
_ENCODER = "sim.belt.encoder"
_TICK_S = 1.0 / 64.0  # шаг GetTickCount64


class _Rec:
    """Записывающий ``state_proxy``: считает ``set`` по путям."""

    def __init__(self) -> None:
        self.paths: list[str] = []

    def set(self, path: str, value: Any, *a: Any, **k: Any) -> None:
        self.paths.append(path)

    def merge(self, *a: Any, **k: Any) -> None: ...

    def delete(self, *a: Any, **k: Any) -> None: ...

    def subscribe(self, *a: Any, **k: Any) -> str:
        return "sub"

    def get(self, *a: Any, **k: Any) -> Any:
        return None


def _quantized_jittery_clock(step_s: float = 0.05, seed: int = 1):
    """Часы воркера: истинное время ``k * step + jitter`` (±1.2 мс), показание — вниз до 1/64 с."""
    rng = random.Random(seed)
    jitter = [rng.uniform(-0.0012, 0.0012) for _ in range(100)]
    index = [0]

    def clock() -> float:
        true_t = index[0] * step_s + jitter[index[0]]
        return math.floor(true_t / _TICK_S) * _TICK_S

    return clock, index


def _run_100(**cfg: Any) -> tuple[_Rec, str, int]:
    """Сервер поднят (без воркера паблишера), 100 вызовов ``_publish_once`` на часах выше."""
    rec = _Rec()
    services = MockProcessServices(name="robot", state_proxy=rec)
    workers = ThreadWorkerManager()
    services.worker_manager = workers
    config: dict[str, Any] = {
        "host": HOST,
        "port": free_port(),
        "unit_id": ROBOT_UNIT_ID,
        "auto_start": True,
        "protocol": "v2",
    }
    config.update(cfg)
    ctx = PluginContext(services=services, config=config)
    plugin = SimRobotHostPlugin()
    plugin.configure(ctx)
    try:
        plugin._start_server(ctx)
        assert plugin._state == "running", f"сервер не поднялся: {plugin._reason!r}"
        clock, index = _quantized_jittery_clock()
        plugin._clock = clock
        for i in range(100):
            index[0] = i
            plugin._publish_once()
        state = getattr(services, "_health_state", None)
        return rec, plugin._state, 0 if state is None else int(state.error_count)
    finally:
        plugin.shutdown(ctx)
        workers.stop_all()


@pytest.mark.parametrize(("hz", "expected"), [(20, 100), (10, 50), (4, 20)])
def test_rate_holds_on_quantized_jittery_clock(hz: int, expected: int) -> None:
    rec, _state, errors = _run_100(robot_state_hz=hz)
    published = rec.paths.count(_ROBOT_STATE)
    assert published == pytest.approx(expected, abs=1), f"robot_state_hz={hz}: записей {published}, ждали {expected}"
    assert rec.paths.count(_ENCODER) == 100
    assert errors == 0


@pytest.mark.parametrize(
    "bad",
    [-1, "abc", True, 21, 10**400, float("nan"), float("inf")],
    ids=["-1", "abc", "True", "21", "1e400-int", "nan", "inf"],
)
def test_bad_rate_is_one_health_refusal(bad: Any) -> None:
    rec, state, errors = _run_100(robot_state_hz=bad)
    assert rec.paths.count(_ROBOT_STATE) == 0
    assert rec.paths.count(_ENCODER) == 100, "энкодер обязан работать"
    assert state == "running"
    assert errors == 1, f"ожидался ровно один отказ в health, их {errors}"
