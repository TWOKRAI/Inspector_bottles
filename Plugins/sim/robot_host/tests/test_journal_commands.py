# -*- coding: utf-8 -*-
"""RED-приёмка Task 5.1 — журнал заданий наружу процесса ``robot`` через команды.

Независимый tester, worktree на коммите контракта лида (до реализации). Контракт —
ТОЛЬКО «Контракт лида 5.1 (ред. 3, 2026-09-23, до тестера)», §2, в
``plans/line-sim/phase-5-ground-truth.md``. Сегодня ``SimRobotHostPlugin`` НЕ заводит
``SimJournal`` вообще (символ ``journal`` не существует, ``sim_robot.journal`` /
``sim_robot.journal_reset`` не зарегистрированы в ``commands``) — ожидаемый провал
``KeyError`` на диспетче команды.

Харнесс скопирован с ``Plugins/sim/robot_host/tests/test_belt_commands.py``
(``MockProcessServices`` + реальный ``PluginContext`` + реальный ``SimRobotServer`` на
свободном порту, команды — только через публичный контракт
``plugin.commands["<имя>"]`` -> ``getattr(plugin, method)``). Приём задания —
``plugin._on_write(fc, addr, values)`` напрямую (тот же приём, что уже использует
ЗЕЛЁНЫЙ ``test_hazards.py`` для ``plugin._on_write(16, 0x1000, [3])`` — это
приёмник, которым реально пользуется ``SimRobotServer.on_write=self._on_write``,
не угаданное имя), в порядке транзакции реального клиента: координаты, DW-энкодер,
маркер ``job_flag`` последним (TRAPS ведущего, тот же порядок, что
``Services/robot_comm/tests/test_sim_journal.py::_send_job``).

**Догадка тестера (см. отчёт).** Контракт говорит «такт публикации забирает
``journal.drain()`` в свой ``deque(maxlen=50)``» — то есть ``recent`` в ответе команды
наполняется ТОЛЬКО тиком паблишера, не самим приёмом записи. Тик паблишера сегодня —
приватный метод ``plugin._publish_once()`` (уже вызывается напрямую существующим
ЗЕЛЁНЫМ ``test_hazards.py::test_publish_once_reports_metrics_without_state_proxy`` —
не угаданное тестером имя, скопировано с уже работающего теста). Тесты этого файла
зовут его вручную после приёма задания, чтобы получить непустой ``recent``.
"""

from __future__ import annotations

import socket
import threading
import time
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

_ZERO_COUNTERS = {
    "jobs": 0,
    "dups": 0,
    "done": 0,
    "reads": 0,
    "dups_same_capture": 0,
    "dups_tracked": 0,
    "repeats_frozen_xy": 0,
}


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
    """Вызвать команду через публичный контракт ``commands`` (``KeyError`` — ожидаемый RED)."""
    method_name = plugin.commands[name]
    method = getattr(plugin, method_name)
    return method(data)


def _run_with_deadline(fn, *, timeout: float, label: str):
    """Потенциально блокирующий вызов — в daemon-потоке с join-дедлайном (не висим)."""
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
    """Транзакция клиента через приёмник сервера: X, Y, DW-энкодер, флаг последним."""
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


# --------------------------------------------------------------------------- #
# R5 — sim_robot.journal отдаёт counters + recent (≤50, старые первыми)      #
# --------------------------------------------------------------------------- #


def test_journal_command_returns_counters_and_recent(running_plugin) -> None:
    plugin, _ctx, _services = running_plugin
    _drive_job(plugin, x_mm=10.0, y_mm=20.0, ecap=1000)
    plugin._publish_once()  # тик паблишера — переносит строку журнала в recent

    resp = _call(plugin, "sim_robot.journal")

    assert resp["status"] == "ok"
    counters = resp["counters"]
    expected = dict(_ZERO_COUNTERS)
    expected["jobs"] = 1
    assert counters == expected, counters

    recent = resp["recent"]
    assert isinstance(recent, list)
    assert len(recent) == 1, recent
    entry = recent[0]
    assert set(entry.keys()) == {"t", "side", "text", "tag"}, entry
    assert entry["tag"] == "job", entry


# --------------------------------------------------------------------------- #
# R6 — sim_robot.journal_reset обнуляет counters и чистит recent            #
# --------------------------------------------------------------------------- #


def test_journal_reset_zeroes_and_clears_recent(running_plugin) -> None:
    plugin, _ctx, _services = running_plugin
    _drive_job(plugin, x_mm=10.0, y_mm=20.0, ecap=1000)
    _drive_job(plugin, x_mm=10.0, y_mm=20.0, ecap=1000)  # дубль той же съёмки
    plugin._publish_once()

    reset_resp = _call(plugin, "sim_robot.journal_reset")
    assert reset_resp == {"status": "ok"}, reset_resp

    resp = _call(plugin, "sim_robot.journal")
    assert resp["status"] == "ok"
    assert resp["counters"] == _ZERO_COUNTERS, resp["counters"]
    assert resp["recent"] == [], resp["recent"]


# --------------------------------------------------------------------------- #
# R7 — sim_robot.status несёт снимок journal; без сервера journal -> error    #
# --------------------------------------------------------------------------- #


def test_status_carries_journal_snapshot_and_no_server_is_error() -> None:
    # (a) сервер не поднят -> sim_robot.journal отвечает ошибкой, не бросает.
    port_a = _free_port()
    plugin_a, _ctx_a, _services_a = _make_plugin(port_a, auto_start=False)
    assert plugin_a._server is None

    no_server_resp = _call(plugin_a, "sim_robot.journal")
    assert no_server_resp["status"] == "error", no_server_resp

    # (b) сервер поднят -> sim_robot.status несёт ключ "journal" со снимком counters().
    port_b = _free_port()
    plugin_b, ctx_b, _services_b = _make_plugin(port_b)
    _run_with_deadline(lambda: plugin_b.start(ctx_b), timeout=5.0, label="start")
    try:
        assert plugin_b._state == "running", f"сервер не поднялся: {plugin_b._reason!r}"
        _drive_job(plugin_b, x_mm=10.0, y_mm=20.0, ecap=1000)

        status = _call(plugin_b, "sim_robot.status")

        assert "journal" in status, status
        expected = dict(_ZERO_COUNTERS)
        expected["jobs"] = 1
        assert status["journal"] == expected, status["journal"]
    finally:
        _run_with_deadline(lambda: plugin_b.shutdown(ctx_b), timeout=5.0, label="shutdown")


# --------------------------------------------------------------------------- #
# R8 — уровни журнала публикуются на такте паблишера (ctx.publish_metric)     #
# --------------------------------------------------------------------------- #


def test_journal_levels_published_on_tick(running_plugin) -> None:
    plugin, ctx, _services = running_plugin
    _drive_job(plugin, x_mm=10.0, y_mm=20.0, ecap=1000)
    _drive_job(plugin, x_mm=10.0, y_mm=20.0, ecap=1000)  # dups_same_capture=1

    published: list[tuple[str, object]] = []
    ctx.publish_metric = lambda name, value: published.append((name, value))  # noqa: E731

    plugin._publish_once()

    levels = dict(published)
    assert levels.get("jobs_seen") == 2, published
    assert levels.get("dups_seen") == 1, published
    assert levels.get("dups_same_capture") == 1, published
    assert levels.get("dups_tracked") == 0, published
    assert levels.get("repeats_frozen_xy") == 0, published
    assert levels.get("jobs_done") == 0, published
