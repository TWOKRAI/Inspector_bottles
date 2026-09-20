# -*- coding: utf-8 -*-
"""Авторские hazard-тесты ``SimRobotHostPlugin`` (Task 1.1 плана ``line-sim``).

Что здесь проверяется — четыре опасных места механизма, названные в докстринге
``plugin.py``: (a) занятый порт обнаруживается СВОИМ пробным bind'ом и не роняет
процесс; (b) повторный ``start`` при живом сервере — no-op; (c) ``shutdown``
закрывает порт достаточно быстро; (d) наблюдатель ``_on_write`` считает только
записи, а не чтения. Харнесс — ``MockProcessServices`` + реальный конструктор
``PluginContext`` (тот же приём, что у ``Plugins/io/otel_export/tests``):
границу процесса (командный менеджер, stats) подделываем, ``PluginContext`` и
плагин — настоящие.

Тесты (b)/(c)/(d) поднимают РЕАЛЬНЫЙ ``SimRobotServer`` (нужен ``pymodbus`` —
``pytest.mark.skipif(not ROBOT_AVAILABLE, ...)``, тот же флаг, что у
``Services/robot_comm/tests/test_sim_e2e.py``); тест (a) — нет, порт занят
проверяется ДО обращения к ``pymodbus`` (см. докстринг ``plugin.py`` про
асинхронный bind фонового потока).
"""

from __future__ import annotations

import socket
import time

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
    MockStatsManager,
)
from Plugins.sim.robot_host.plugin import SimRobotHostPlugin
from Services.robot_comm import ROBOT_AVAILABLE

pytestmark = pytest.mark.timeout(30)


def _free_port() -> int:
    """Свободный TCP-порт (см. Services/robot_comm/tests/test_sim_e2e.py)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_plugin(
    port: int, *, unit_id: int = 2, auto_start: bool = True
) -> tuple[SimRobotHostPlugin, PluginContext, MockProcessServices]:
    """Собрать плагин + PluginContext на MockProcessServices с реальным MockStatsManager."""
    stats = MockStatsManager()
    services = MockProcessServices(name="robot", stats_manager=stats)
    ctx = PluginContext(
        services=services, config={"host": "127.0.0.1", "port": port, "unit_id": unit_id, "auto_start": auto_start}
    )
    plugin = SimRobotHostPlugin()
    plugin.configure(ctx)
    return plugin, ctx, services


# --------------------------------------------------------------------------- #
# (a) Порт занят -> report_error, состояние error, процесс живёт (не бросает) #
# --------------------------------------------------------------------------- #


def test_port_busy_reports_error_not_crash() -> None:
    """Порт занят СВОИМ сокетом -> ``_start_server`` не бросает, health получил ошибку."""
    port = _free_port()
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", port))
    occupied.listen(1)
    try:
        plugin, ctx, services = _make_plugin(port)

        # Не должно бросить — вызывающий (start()) не оборачивает в try/except.
        plugin.start(ctx)

        assert plugin._state == "error", f"ожидали state='error', получили {plugin._state!r}"
        assert plugin._server is None, "сервер не должен быть создан при занятом порту"

        health_state = getattr(services, "_health_state", None)
        assert health_state is not None, "ctx.health.report_error должен был создать HealthState на services"
        assert health_state.error_count >= 1, f"report_error не учтён: error_count={health_state.error_count}"
    finally:
        occupied.close()


# --------------------------------------------------------------------------- #
# (b) Повторный start при живом сервере — no-op                               #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен")
def test_double_start_is_noop() -> None:
    """Второй вызов ``start`` не пересоздаёт сервер (тот же объект)."""
    port = _free_port()
    plugin, ctx, _services = _make_plugin(port)
    try:
        plugin.start(ctx)
        assert plugin._state == "running", (
            f"первый start не поднял сервер: state={plugin._state!r}, reason={plugin._reason!r}"
        )
        first_server = plugin._server
        assert first_server is not None

        plugin.start(ctx)
        assert plugin._server is first_server, "повторный start пересоздал сервер — должен быть no-op"
        assert plugin._state == "running"
    finally:
        plugin.shutdown(ctx)


# --------------------------------------------------------------------------- #
# (c) shutdown закрывает порт                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен")
def test_shutdown_closes_port() -> None:
    """После ``shutdown`` порт освобождается за разумное время (TRAPS lead'а, п.4)."""
    port = _free_port()
    plugin, ctx, _services = _make_plugin(port)
    plugin.start(ctx)
    assert plugin._state == "running", f"сервер не поднялся: {plugin._reason!r}"

    # Дать серверу реально начать слушать порт перед остановом.
    deadline = time.monotonic() + 5.0
    listening = False
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                listening = True
                break
        except OSError:
            time.sleep(0.1)
    assert listening, f"SimRobotServer не начал слушать {port} за 5с"

    plugin.shutdown(ctx)
    assert plugin._server is None

    deadline = time.monotonic() + 5.0
    closed = False
    while time.monotonic() < deadline:
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.bind(("127.0.0.1", port))
            probe.close()
            closed = True
            break
        except OSError:
            time.sleep(0.1)
    assert closed, f"порт {port} не освободился за 5с после shutdown()"


# --------------------------------------------------------------------------- #
# (d) _on_write считает только записи, публикует метрику дельтой              #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен")
def test_on_write_counts_only_writes() -> None:
    """Чтение (values=None) не считается; запись — считается и уходит в record_metric."""
    port = _free_port()
    plugin, ctx, services = _make_plugin(port)

    # Чтение: fc=3 (read holding registers), values=None — не должно посчитаться.
    plugin._on_write(3, 0x1112, None)
    assert plugin._writes_seen == 0, "чтение (values=None) не должно увеличивать writes_seen"

    # Запись: fc=16 (write multiple registers), values — список.
    plugin._on_write(16, 0x1000, [1, 2])
    assert plugin._writes_seen == 1, "запись должна увеличить writes_seen ровно на 1"

    status = plugin.cmd_status()
    assert status["writes_seen"] == 1, status

    stats: MockStatsManager = services.stats_manager
    counter_records = [r for r in stats.records if r[0] == "counter" and r[1] == "sim_robot.writes"]
    assert counter_records, f"ctx.record_metric('sim_robot.writes', ...) не был вызван: {stats.records!r}"
    assert counter_records[-1][2] == 1, f"дельта метрики должна быть 1: {counter_records!r}"

    # Ещё одна запись + повторный status — метрика уходит ВТОРОЙ дельтой (не абсолютом).
    plugin._on_write(16, 0x1000, [3])
    status2 = plugin.cmd_status()
    assert status2["writes_seen"] == 2
    counter_records2 = [r for r in stats.records if r[0] == "counter" and r[1] == "sim_robot.writes"]
    assert len(counter_records2) == 2, f"второй cmd_status должен добавить ровно одну дельту: {counter_records2!r}"
    assert counter_records2[-1][2] == 1, f"вторая дельта должна быть 1 (не 2): {counter_records2!r}"

    plugin.shutdown(ctx)
