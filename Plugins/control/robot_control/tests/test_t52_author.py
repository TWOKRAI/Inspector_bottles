# -*- coding: utf-8 -*-
"""Task 5.2 — авторские тесты ``robot_control`` по ревью раунда 1 (находки 2 и 3).

* ``reset_counters`` обязан обнулять и процессные счётчики планировщика в ``get_stats``
  (``actuation_late_fires``, ``actuation_unfired_on_stop_items``): планировщик общий, поэтому
  плагин вычитает базу, а не обнуляет чужое. До правки: после сброса ``fired=0, late=1``.
* WARNING об устаревшем ``reject_delay_ms`` — один на экземпляр, на первом ``process()`` при
  ЛЮБОМ исходе. До правки он звучал только на первом ``reject``: на линии без брака — никогда.

Контекст — настоящий ``PluginContext`` над ``MockProcessServices`` с ``worker_manager=None``
(``tick()`` и ``run_loop`` зовутся руками). Блокирующее — в daemon-потоке с дедлайном.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

import numpy as np

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Plugins.control.robot_control.plugin import RobotControlPlugin


def _plugin(config: Dict[str, Any]):
    svc = MockProcessServices(name="inspector")
    svc.worker_manager = None  # type: ignore[assignment]
    ctx = PluginContext(svc, config=dict(config), plugin_name="robot_control")
    plugin = RobotControlPlugin()
    plugin.configure(ctx)
    return plugin, ctx, svc


def _reject(capture_ts: float | None) -> dict:
    item: dict = {
        "frame": np.zeros((8, 8, 3), dtype=np.uint8),
        "detections": [{"bbox": [1, 1, 5, 5], "center": [3, 3], "area": 900}],
        "trace_id": "t",
    }
    if capture_ts is not None:
        item["capture_ts"] = capture_ts
    return item


def _pass() -> dict:
    return {"frame": np.zeros((8, 8, 3), dtype=np.uint8), "detections": [], "trace_id": "p"}


def _run_bounded(target, *args: Any, timeout: float = 5.0) -> None:
    t = threading.Thread(target=target, args=args, daemon=True)
    t.start()
    t.join(timeout)
    assert not t.is_alive(), f"вызов завис дольше {timeout} с"


# --- Находка 2: reset_counters и процессные счётчики ----------------------------------------------


def test_reset_counters_zeroes_late_fires_seen_by_get_stats() -> None:
    # допуск 1 мс. Цель — в БУДУЩЕМ (fire_at ~ now + 30 мс): шаг time.time() на Windows
    # 15.625 мс, и цель «ровно сейчас» с окном +1 мс закрывалась шагом часов между
    # чтением в тесте и чтением в schedule() -> "missed" (ревью 5.2: 3 из 1500).
    # Выстрел через ~100 мс сна -> опоздание ~70 +- 16 мс > 1 мс, late_fires == 1.
    plugin, ctx, _ = _plugin({"transit_ms": 100, "actuation_tolerance_ms": 1})
    plugin.process([_reject(time.time() - 0.100 + 0.030)])
    time.sleep(0.1)
    assert ctx.scheduler.tick() == 1
    stats = plugin.cmd_get_stats({})
    assert (stats["actuation_fired_items"], stats["actuation_late_fires"]) == (1, 1)  # якорь

    plugin.cmd_reset_counters({})

    stats = plugin.cmd_get_stats({})
    assert stats["actuation_fired_items"] == 0
    assert stats["actuation_late_fires"] == 0
    assert stats["actuation_unfired_on_stop_items"] == 0


def test_reset_counters_zeroes_unfired_on_stop_and_counts_only_new_ones_after() -> None:
    plugin, ctx, _ = _plugin({"transit_ms": 100})
    plugin.process([_reject(time.time() + 50.0)])  # далёкая цель — не выстрелит
    stop, pause = threading.Event(), threading.Event()
    stop.set()  # run_loop сразу выходит и считает невыстреленное
    _run_bounded(ctx.scheduler.run_loop, stop, pause)
    assert plugin.cmd_get_stats({})["actuation_unfired_on_stop_items"] == 1  # якорь

    plugin.cmd_reset_counters({})
    assert plugin.cmd_get_stats({})["actuation_unfired_on_stop_items"] == 0

    plugin.process([_reject(time.time() + 50.0)])
    _run_bounded(ctx.scheduler.run_loop, stop, pause)
    assert plugin.cmd_get_stats({})["actuation_unfired_on_stop_items"] == 1  # прирост после сброса


# --- Находка 3: WARNING об алиасе на первом process() при любом исходе ---------------------------


def _alias_warnings(svc: MockProcessServices) -> List[str]:
    return [e["msg"] for e in svc.logs if e["level"] == "WARNING" and "reject_delay_ms" in e["msg"]]


def test_alias_warning_sounds_once_on_a_line_with_only_pass_outcomes() -> None:
    plugin, ctx, svc = _plugin({"reject_delay_ms": 50})

    for _ in range(100):
        plugin.process([_pass()])

    assert plugin.cmd_get_stats({})["total_rejected"] == 0  # якорь: ни одного reject
    assert len(_alias_warnings(svc)) == 1, _alias_warnings(svc)
    assert getattr(svc, "_actuation_scheduler", None) is None  # pass не создаёт планировщик


def test_alias_warning_is_not_repeated_by_later_rejects() -> None:
    plugin, _, svc = _plugin({"reject_delay_ms": 50})

    plugin.process([_pass()])
    for _ in range(10):
        plugin.process([_reject(time.time())])

    assert len(_alias_warnings(svc)) == 1
