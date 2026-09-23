# -*- coding: utf-8 -*-
"""RED-приёмка Task 5.1b — §3 контракта, сторона robot_host: ``repeats_frozen_xy``
исчезает из журнала, который отдаёт ``SimRobotHostPlugin`` наружу — ни в
``sim_robot.journal``, ни среди ``ctx.declare_metric``/``ctx.publish_metric``.

Независимый tester, worktree на коммите контракта лида (602be8ec, до реализации).
Контракт — ТОЛЬКО ``plans/line-sim/phase-5-contract-5.1b.md`` §1+§3: журнал теряет
категорию целиком (§1, см. ``Services/robot_comm/tests/test_acceptance_5_1b.py``), и
robot_host, который сегодня явно заводит уровень ``repeats_frozen_xy`` (см.
``Plugins/sim/robot_host/plugin.py``: ``ctx.declare_metric("repeats_frozen_xy")`` в
``configure()`` и ``ctx.publish_metric("repeats_frozen_xy", ...)`` в
``_publish_journal_once()``), должен перестать это делать.

Сегодня оба ключа/уровня ЕСТЬ — ожидаемый провал ``AssertionError`` (ключ найден
там, где контракт требует отсутствия), не ``KeyError``.

Харнесс скопирован с ``Plugins/sim/robot_host/tests/test_journal_commands.py``
(``_make_plugin``/``_call``/``_drive_job``/``_free_port``/``_run_with_deadline`` —
тот же паттерн: ``MockProcessServices`` + реальный ``PluginContext`` + реальный
``SimRobotServer`` на свободном порту, приём задания — через публичный приёмник
``plugin._on_write`` в порядке транзакции клиента: координаты, DW-энкодер, флаг
последним).
"""

from __future__ import annotations

import socket
import threading
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Plugins.sim.robot_host.plugin import SimRobotHostPlugin
from Services.robot_comm import ROBOT_AVAILABLE
from Services.robot_comm.core.registers import REG_JOB_ECAP, REG_JOB_FLAG, REG_JOB_X, REG_JOB_Y, XY_SCALE

pytestmark = [
    pytest.mark.timeout(30),
    pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен"),
]

_HOST = "127.0.0.1"
_FORBIDDEN_PORTS = {5021, 8765, 8766, 8091, 8092}  # живой стенд владельца — не трогать

_FC_WRITE_SINGLE = 6
_FC_WRITE_MULTI = 16


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((_HOST, 0))
        port = s.getsockname()[1]
    finally:
        s.close()
    assert port not in _FORBIDDEN_PORTS, f"порту {port} не повезло совпасть со стендом, перегенерировать"
    return port


def _make_plugin(port: int, **extra_cfg: Any) -> tuple[SimRobotHostPlugin, PluginContext, MockProcessServices]:
    services = MockProcessServices(name="robot")
    cfg = {"host": _HOST, "port": port, "unit_id": 2, "auto_start": True}
    cfg.update(extra_cfg)
    ctx = PluginContext(services=services, config=cfg)
    plugin = SimRobotHostPlugin()
    plugin.configure(ctx)
    return plugin, ctx, services


def _call(plugin: SimRobotHostPlugin, name: str, data: dict | None = None) -> dict:
    method_name = plugin.commands[name]
    method = getattr(plugin, method_name)
    return method(data)


def _run_with_deadline(fn, *, timeout: float, label: str):
    """Потенциально блокирующий вызов — в daemon-потоке с join-дедлайном."""
    result: dict = {}
    error: dict = {}

    def _target() -> None:
        try:
            result["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            error["exc"] = exc

    thread = threading.Thread(target=_target, name=f"deadline-{label}", daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    if thread.is_alive():
        raise AssertionError(f"{label} не вернулась за {timeout} с — похоже на зависание")
    if "exc" in error:
        raise error["exc"]
    return result.get("value")


def _drive_job(plugin: SimRobotHostPlugin, x_mm: float, y_mm: float, ecap: int) -> None:
    """Транзакция клиента: X, Y, DW-энкодер, флаг последним."""
    plugin._on_write(_FC_WRITE_SINGLE, REG_JOB_X, [int(x_mm * XY_SCALE) & 0xFFFF])
    plugin._on_write(_FC_WRITE_SINGLE, REG_JOB_Y, [int(y_mm * XY_SCALE) & 0xFFFF])
    plugin._on_write(_FC_WRITE_MULTI, REG_JOB_ECAP, [ecap & 0xFFFF, (ecap >> 16) & 0xFFFF])
    plugin._on_write(_FC_WRITE_SINGLE, REG_JOB_FLAG, [1])


@pytest.fixture
def running_plugin():
    port = _free_port()
    plugin, ctx, services = _make_plugin(port)
    _run_with_deadline(lambda: plugin.start(ctx), timeout=5.0, label="start")
    assert plugin._state == "running", f"сервер не поднялся: {plugin._reason!r}"
    try:
        yield plugin, ctx, services
    finally:
        _run_with_deadline(lambda: plugin.shutdown(ctx), timeout=5.0, label="shutdown")


def test_journal_has_no_repeats_key(running_plugin) -> None:
    """§1 контракта 5.1b, зеркало наружу: ``sim_robot.journal`` не должен отдавать
    ``repeats_frozen_xy`` ни в ``counters``, ни в отдельных строках-тегах "repeat"."""
    plugin, _ctx, _services = running_plugin
    _drive_job(plugin, x_mm=10.0, y_mm=20.0, ecap=1000)
    _drive_job(plugin, x_mm=10.0, y_mm=20.0, ecap=2000)  # была бы repeat-строкой ДО 5.1b
    plugin._publish_once()

    resp = _call(plugin, "sim_robot.journal")
    assert resp["status"] == "ok"
    counters = resp["counters"]
    assert "repeats_frozen_xy" not in counters, (
        f"§1 контракта 5.1b: repeats_frozen_xy должен исчезнуть из journal counters: {counters!r}"
    )
    tags = [entry["tag"] for entry in resp["recent"]]
    assert "repeat" not in tags, f"тег 'repeat' не должен появляться после 5.1b: {resp['recent']!r}"


def test_no_repeats_frozen_xy_in_metric_calls() -> None:
    """§3 контракта: robot_host не должен заводить/публиковать уровень
    ``repeats_frozen_xy`` — ни через ``declare_metric`` (сегодня в ``configure()``),
    ни через ``publish_metric`` (сегодня в ``_publish_journal_once()``). Патчим
    ``declare_metric`` ДО ``configure()``, чтобы поймать объявление уровня —
    ``running_plugin`` для этого не годится, там ``configure()`` уже отработал."""
    port = _free_port()
    services = MockProcessServices(name="robot")
    ctx = PluginContext(services=services, config={"host": _HOST, "port": port, "unit_id": 2, "auto_start": True})
    plugin = SimRobotHostPlugin()

    declared: list[str] = []
    ctx.declare_metric = lambda name: declared.append(name)  # noqa: E731

    plugin.configure(ctx)  # declare_metric звучит здесь — патч должен стоять ДО этого вызова
    assert "repeats_frozen_xy" not in declared, (
        f"§3 контракта 5.1b: repeats_frozen_xy не должен объявляться, объявлено: {declared!r}"
    )

    _run_with_deadline(lambda: plugin.start(ctx), timeout=5.0, label="start")
    assert plugin._state == "running", f"сервер не поднялся: {plugin._reason!r}"
    try:
        _drive_job(plugin, x_mm=10.0, y_mm=20.0, ecap=1000)

        published: list[tuple[str, object]] = []
        ctx.publish_metric = lambda name, value: published.append((name, value))  # noqa: E731

        plugin._publish_once()

        published_names = {name for name, _value in published}
        assert "repeats_frozen_xy" not in published_names, (
            f"§3 контракта 5.1b: repeats_frozen_xy не должен публиковаться, опубликовано: {published!r}"
        )
    finally:
        _run_with_deadline(lambda: plugin.shutdown(ctx), timeout=5.0, label="shutdown")
