"""Тест лида после break-injection Task 3.5b: боевая проводка «ядро -> хост -> сцена».

Инъекция J16 (ядро собирается без `on_job_done`) проходила весь набор зелёным: тесты
тестера зовут `_on_job_done` напрямую. Здесь задание проходит через НАСТОЯЩЕЕ ядро,
которое строит `_start_server`; подменены только сетевой сервер и клиент шины.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import Plugins.sim.robot_host.plugin as robot_plugin_module
import Services.robot_comm.server.sim_robot as sim_robot_module
from Plugins.sim.robot_host.plugin import SimRobotHostPlugin
from Services.modbus.sdk.datatypes import encode_int32
from Services.robot_comm.core.registers import REG_JOB_ECAP, REG_JOB_FLAG, REG_JOB_X, REG_JOB_Y


class _FakeServer:
    def __init__(self, host, port, unit_id, *, core=None, on_write=None):
        self.core = core

    def start(self):
        pass

    def stop(self):
        pass


class _Client:
    sent: list[tuple[str, str, dict]] = []

    def __init__(self, ctx, target_process="devices"):
        self.target = target_process

    def send_fire_and_forget(self, command, args=None):
        type(self).sent.append((self.target, command, args))
        return True


def test_job_completed_by_real_core_reaches_scene(monkeypatch):
    _Client.sent = []
    monkeypatch.setattr(sim_robot_module, "SimRobotServer", _FakeServer)
    monkeypatch.setattr(robot_plugin_module, "DeviceHubClient", _Client)

    ctx = MagicMock()
    ctx.config = {"host": "127.0.0.1", "port": 0, "unit_id": 2, "auto_start": False}
    plugin = SimRobotHostPlugin()
    plugin.configure(ctx)
    monkeypatch.setattr(plugin, "_probe_port_free", lambda: None)
    plugin._start_server(ctx)
    core = plugin._server.core

    core.write(REG_JOB_X, [125])
    core.write(REG_JOB_Y, [65506])  # -3.0 мм
    core.write(REG_JOB_ECAP, encode_int32(106016, word_order="little"))
    core.write(REG_JOB_FLAG, [1])
    for _ in range(3):
        core.tick()

    assert len(_Client.sent) == 1
    target, command, args = _Client.sent[0]
    assert (target, command) == ("camera", "scene.job_done")
    assert args["ecap"] == 106016 and args["x_mm"] == 12.5 and args["y_mm"] == -3.0


def test_journal_counts_job_and_done_through_real_core(monkeypatch):
    """Лид, 5.1: задание, пришедшее через хук сервера (`_on_write`) и выполненное
    НАСТОЯЩИМ ядром из `_start_server`, видно в `sim_robot.journal` как jobs=1, done=1.
    Тесты тестера держат jobs_done только нулём — проводка `on_event` ядра не прибита."""
    _Client.sent = []
    monkeypatch.setattr(sim_robot_module, "SimRobotServer", _FakeServer)
    monkeypatch.setattr(robot_plugin_module, "DeviceHubClient", _Client)

    ctx = MagicMock()
    ctx.config = {"host": "127.0.0.1", "port": 0, "unit_id": 2, "auto_start": False}
    plugin = SimRobotHostPlugin()
    plugin.configure(ctx)
    monkeypatch.setattr(plugin, "_probe_port_free", lambda: None)
    plugin._start_server(ctx)
    core = plugin._server.core

    # Сервер pymodbus зовёт хук ДО записи в регистры — повторяем его порядок.
    for addr, values in (
        (REG_JOB_X, [125]),
        (REG_JOB_Y, [65506]),
        (REG_JOB_ECAP, encode_int32(106016, word_order="little")),
        (REG_JOB_FLAG, [1]),
    ):
        plugin._on_write(16, addr, values)
        core.write(addr, values)
    plugin._on_write(3, REG_JOB_X, None)  # одно чтение
    for _ in range(3):
        core.tick()

    counters = plugin.cmd_journal({})["counters"]
    assert (counters["jobs"], counters["done"], counters["reads"], counters["dups"]) == (1, 1, 1, 0)


def test_restart_starts_with_empty_recent(monkeypatch):
    """Ревью 3.5/5.1, minor 2: рестарт сервера создаёт новый журнал — строки прошлого
    запуска не должны оставаться в `recent` при нулевых счётчиках."""
    monkeypatch.setattr(sim_robot_module, "SimRobotServer", _FakeServer)
    ctx = MagicMock()
    ctx.config = {"host": "127.0.0.1", "port": 0, "unit_id": 2, "auto_start": False}
    plugin = SimRobotHostPlugin()
    plugin.configure(ctx)
    monkeypatch.setattr(plugin, "_probe_port_free", lambda: None)
    plugin._start_server(ctx)
    for addr, values in ((REG_JOB_X, [125]), (REG_JOB_Y, [200]), (REG_JOB_FLAG, [1])):
        plugin._on_write(16, addr, values)
    plugin._publish_journal_once()
    assert [e["tag"] for e in plugin.cmd_journal({})["recent"]] == ["job"]

    plugin._server = None  # сервер остановлен
    plugin._start_server(ctx)
    journal = plugin.cmd_journal({})
    assert journal["counters"]["jobs"] == 0 and journal["recent"] == []
