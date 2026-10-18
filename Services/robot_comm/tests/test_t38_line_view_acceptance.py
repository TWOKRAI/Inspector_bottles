# -*- coding: utf-8 -*-
"""Слепая приёмка T3.8 (RED до кода): вид робота рисует робота ЛИНИИ из ``sim.robot.state``.

Контракт — только публичный перечень брифа лида и ``plans/robot-protocol-v2/tasks/T3.8.reds.md``;
тела ``line_source.py``, ``build_window``/``attach_line``/``main``, ``_publish_once``/
``_robot_state_snapshot``/``configure`` до RED не читались (``line_source.py`` ещё не существует).
Тела ``build_window``/``main`` в ``sim_view.py`` на базе — прежние (демо), их увидел при поиске
образцов запуска; реализации T3.8 в дереве нет.

Хост для REDS 5, 6, 10 — НАСТОЯЩИЙ ``RouterManager`` + НАСТОЯЩИЙ ``StateStoreManager`` за дверью
``setup_backend_ctl_channel(router, host="127.0.0.1", port=0, env={"BACKEND_CTL": "1"})``. Команды
``state.*`` ведут в его ``handle_state_*`` через тонкую прокладку ``get_command_info``/
``handle_command`` (образец ``test_remote_state_proxy.py::_make_command_host``): настоящий
``CommandManager`` требует процесса. Снимок кладёт ``handle_state_set`` от источника ``robot``,
между снимками хост пишет ``sim.belt.encoder`` (revision идут с разрывами, как на линии).
Макет хоста (``_FakeLink``) — только REDS 9.

Ожидаемые значения — литералы из REDS; позы ядра — ``PTP_MOVE`` + тики до ``TLM_MOVING == 0``.
Всё, что может зависнуть, — в daemon-потоке с дедлайном или в подпроцессе с таймаутом.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import Mock

import pytest

pytest.importorskip("PySide6", reason="окно-вид требует PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from multiprocess_framework.modules.frontend_module.bridge.remote_state_proxy import RemoteStateProxy
from multiprocess_framework.modules.process_manager_module.process.backend_ctl_endpoint import (
    setup_backend_ctl_channel,
    teardown_backend_ctl_channel,
)
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.router_module.channels.queue_channel import QueueChannel
from multiprocess_framework.modules.router_module.channels.socket_client import SocketClient
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
from multiprocess_framework.modules.state_store_module.manager.state_store_manager import StateStoreManager
from Plugins.sim.robot_host.plugin import SimRobotHostPlugin
from Plugins.sim.robot_host.tests.host_harness import HOST, ThreadWorkerManager, free_port, run_with_deadline
from Services.robot_comm import ROBOT_AVAILABLE
from Services.robot_comm.core.protocol_v2 import KIND, OP, REG
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.gui.sim_view import SimView, build_window
from Services.robot_comm.gui.z_view import TimeTape, ZScale
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

_ROOT = Path(__file__).resolve().parents[3]

#: позы ядра (мм, мм, мм, град) — литералы REDS
POSE_A = (350.0, -150.0, -60.0, 10.0)
POSE_B = (400.0, -100.0, -90.0, -20.0)
POSE_C = (320.0, -180.0, -50.0, 0.0)
POSE_HOME = (300.0, -210.0, -40.0, -100.0)

_STATUS_A = "X=350.0  Y=-150.0  Z=-60.0  RZ=10.0"
_STATUS_B = "X=400.0  Y=-100.0  Z=-90.0  RZ=-20.0"
_STATUS_C = "X=320.0  Y=-180.0  Z=-50.0  RZ=0.0"

_ROBOT_STATE = "sim.robot.state"
_TLM, _RES, _PMIR = 0x1040, 0x1010, 0x3000


# --------------------------------------------------------------------------- #
# Ядро в заданной позе и снимок                                               #
# --------------------------------------------------------------------------- #


def _u16(v: int) -> int:
    return v & 0xFFFF


def _s16(raw: int) -> int:
    return raw - 65536 if raw >= 0x8000 else raw


def _core_pose(core: RobotSimCoreV2) -> tuple[float, float, float, float]:
    return tuple(_s16(core.read(REG[n], 1)[0]) / 10.0 for n in ("TLM_X", "TLM_Y", "TLM_Z", "TLM_RZ"))  # type: ignore[return-value]


def _core_at(pose: tuple[float, float, float, float]) -> RobotSimCoreV2:
    """Ядро v2 в позе ``pose``: PTP_MOVE по mailbox + тики до TLM_MOVING == 0 (потолок тиков)."""
    core = RobotSimCoreV2()
    core.write(REG["CMD_SEQ"], [1])
    core.write(REG["CMD_OPCODE"], [OP["PTP_MOVE"]])
    args = [_u16(round(v * 10)) for v in pose] + [KIND["JOINT"], 0]
    core.write(REG["CMD_ARGC"], [len(args)])
    core.write(REG["CMD_ARGS"], args)
    core.write(REG["CMD_FLAG"], [1])  # последним
    for _ in range(6000):
        core.tick()
        if core.regs[REG["TLM_MOVING"]] == 0:
            break
    else:
        pytest.fail("предпосылка теста: ход ядра не завершился за 6000 тиков")
    assert _core_pose(core) == pytest.approx(pose, abs=0.05), "предпосылка теста: ядро не доехало до позы"
    return core


def _bare_plugin() -> SimRobotHostPlugin:
    """Плагин v2 без сервера и воркеров — только ради ``_robot_state_snapshot(core)``."""
    ctx = PluginContext(services=MockProcessServices(name="robot"), config={"auto_start": False, "protocol": "v2"})
    plugin = SimRobotHostPlugin()
    plugin.configure(ctx)
    return plugin


def _snapshot(pose: tuple[float, float, float, float]) -> dict:
    core = _core_at(pose)
    snap = _bare_plugin()._robot_state_snapshot(core)
    return json.loads(json.dumps(snap))  # провод: только JSON-типы


def _line_source() -> Any:
    return importlib.import_module("Services.robot_comm.gui.line_source")


def _attach_line() -> Callable[..., Any]:
    from Services.robot_comm.gui import sim_view

    return sim_view.attach_line


def _src_pose(src: Any) -> tuple[float, float, float, float]:
    return tuple(_s16(src.read(REG[n], 1)[0]) / 10.0 for n in ("TLM_X", "TLM_Y", "TLM_Z", "TLM_RZ"))  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Хост: настоящие RouterManager + StateStoreManager за дверью backend_ctl      #
# --------------------------------------------------------------------------- #


class _NoQueues:
    """Реестр очередей без процессов: внешний подписчик ``backend_ctl.<сессия>`` доставляется каналом."""

    def send_to_queue(self, process: str, qtype: str, msg: Any) -> bool:
        return False


class _LineHost:
    """Линия в миниатюре: дерево состояния + дверь. ``put`` кладёт снимок от источника ``robot``."""

    _COMMANDS = (
        "state.set",
        "state.merge",
        "state.delete",
        "state.get",
        "state.get_subtree",
        "state.subscribe",
        "state.unsubscribe",
        "state.unsubscribe_all",
    )

    def __init__(self, port: int = 0) -> None:
        self._lock = threading.Lock()
        self._seen: list[str] = []
        self._enc = 0
        self.router = RouterManager(manager_name="host", queue_registry=_NoQueues())
        self.router.register_channel(QueueChannel("self", Queue()))
        self.ssm = StateStoreManager(router=self.router, initial_state={}, auto_register_ipc=False)
        handlers = {
            name: self._wrap(name, getattr(self.ssm, "handle_" + name.replace(".", "_"))) for name in self._COMMANDS
        }

        cm = Mock()
        cm.get_command_info = Mock(side_effect=lambda n: {"key": n, "metadata": {}} if n in handlers else None)
        cm.handle_command = Mock(
            side_effect=lambda msg: (
                handlers[msg["command"]](msg)
                if msg.get("command") in handlers
                else {"status": "error", "reason": "no handler"}
            )
        )
        self.router.process = SimpleNamespace(command_manager=cm)
        to_self = RouterManager._make_channel_handler("self")
        for key in list(handlers) + ["command.response"]:
            self.router.register_channel_handler(key, to_self)
        self.router.initialize()
        self.ssm.initialize()
        self.router.start_listening(poll_interval=0.01)
        self.channel = setup_backend_ctl_channel(self.router, host="127.0.0.1", port=port, env={"BACKEND_CTL": "1"})
        assert self.channel is not None, "HOST_BUILD_FAILED: setup_backend_ctl_channel вернул None"
        self.port: int = self.channel.port

    def _wrap(self, name: str, handler: Callable[[dict], dict]) -> Callable[[dict], dict]:
        def _h(msg: dict) -> dict:
            with self._lock:
                self._seen.append(name)
            return handler(msg)

        return _h

    def commands(self) -> list[str]:
        with self._lock:
            return list(self._seen)

    def count(self, name: str) -> int:
        return self.commands().count(name)

    def put(self, snapshot: dict) -> None:
        """Энкодер лент(ы) между снимками (разрыв revision), затем снимок робота."""
        for _ in range(3):
            self._enc += 1
            self.ssm.handle_state_set(
                {
                    "data": {
                        "path": "sim.belt.encoder",
                        "value": {"value": float(self._enc), "mm_s": 0.0},
                        "source": "robot",
                    }
                }
            )
        self.ssm.handle_state_set({"data": {"path": _ROBOT_STATE, "value": snapshot, "source": "robot"}})

    def close(self) -> None:
        for step in (
            lambda: teardown_backend_ctl_channel(self.channel, self.router),
            self.router.shutdown,
            self.ssm.shutdown,
        ):
            try:
                step()
            except Exception:  # noqa: BLE001, S110 — закрытие в finally не маскирует причину падения теста
                pass


def _wait(predicate: Callable[[], bool], timeout: float, step: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


def _pump(link: Any, predicate: Callable[[], bool], timeout: float) -> bool:
    """``tick()`` каждые 0.05 с (главный поток) до ``predicate`` или дедлайна."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        link.tick()
        if predicate():
            return True
        time.sleep(0.05)
    link.tick()
    return predicate()


# --------------------------------------------------------------------------- #
# Хост робота (плагин) с записывающим state_proxy                             #
# --------------------------------------------------------------------------- #


class _RecordingStateProxy:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls: list[tuple[str, str, Any]] = []  # (метод, путь, значение)

    def _rec(self, method: str, path: str, value: Any = None) -> None:
        with self._lock:
            self.calls.append((method, path, value))

    def set(self, path: str, value: Any, *a: Any, **k: Any) -> None:
        self._rec("set", path, json.loads(json.dumps(value)))  # JSON-типы или TypeError

    def merge(self, path: str, value: Any = None, *a: Any, **k: Any) -> None:
        self._rec("merge", path, value)

    def delete(self, path: str, *a: Any, **k: Any) -> None:
        self._rec("delete", path)

    def subscribe(self, *a: Any, **k: Any) -> str:
        return "sub"

    def get(self, *a: Any, **k: Any) -> Any:
        return None

    def snapshot(self) -> list[tuple[str, str, Any]]:
        with self._lock:
            return list(self.calls)

    def states(self) -> list[dict]:
        return [v for m, p, v in self.snapshot() if m == "set" and p == _ROBOT_STATE]

    def count(self, path: str) -> int:
        return sum(1 for m, p, _ in self.snapshot() if m == "set" and p == path)


def _build_robot_host(
    rec: _RecordingStateProxy, **cfg: Any
) -> tuple[SimRobotHostPlugin, PluginContext, MockProcessServices, ThreadWorkerManager]:
    services = MockProcessServices(name="robot", state_proxy=rec)
    workers = ThreadWorkerManager()
    services.worker_manager = workers
    config: dict[str, Any] = {"host": HOST, "port": free_port(), "unit_id": ROBOT_UNIT_ID, "auto_start": True}
    config.update(cfg)
    ctx = PluginContext(services=services, config=config)
    assert ctx.state_proxy is rec and ctx.worker_manager is workers
    plugin = SimRobotHostPlugin()
    plugin.configure(ctx)
    return plugin, ctx, services, workers


def _health_errors(services: MockProcessServices) -> int:
    state = getattr(services, "_health_state", None)
    return 0 if state is None else int(state.error_count)


# --------------------------------------------------------------------------- #
# 1. Паблишер кладёт sim.robot.state                                          #
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен")
def test_publisher_puts_robot_state() -> None:
    rec = _RecordingStateProxy()
    plugin, ctx, _services, workers = _build_robot_host(rec, protocol="v2", robot_state_hz=20)
    try:
        run_with_deadline(lambda: plugin.start(ctx), timeout=10.0, label="start")
        assert plugin._state == "running", f"хост не поднялся: {plugin._reason!r}"
        core = plugin._server.core
        time.sleep(1.0)
        states = rec.states()
        assert len(states) >= 5, f"за 1.0 с при robot_state_hz=20 записей sim.robot.state: {len(states)}"

        first = states[0]
        assert [first["pose"][k] for k in ("x_mm", "y_mm", "z_mm", "rz_deg")] == pytest.approx(POSE_HOME, abs=0.05)
        assert (len(first["regs"]["res"]), len(first["regs"]["tlm"]), len(first["regs"]["pmir"])) == (12, 32, 128)
        assert first["model"] == "ScaraModel"
        assert isinstance(first["joints"], list) and len(first["joints"]) == len(core.joints())

        # Тик встал -> блок tlm снимка равен тому, что отдаёт ядро.
        assert workers.stop_worker("sim_robot_ticker") is True
        time.sleep(0.2)
        mark = len(rec.states())
        assert _wait(lambda: len(rec.states()) >= mark + 2, 3.0), "после остановки тика записи не идут"
        frozen = core.read(_TLM, 32)
        time.sleep(0.1)
        assert core.read(_TLM, 32) == frozen, "предпосылка: тик не встал, tlm меняется"
        assert rec.states()[-1]["regs"]["tlm"] == frozen

        paths = [p for _m, p, _v in rec.snapshot()]
        assert paths, "хост вообще ничего не писал в state_proxy"
        assert all(p.startswith("sim.") for p in paths), f"путь не из sim.*: {sorted(set(paths))}"
        assert not [p for p in paths if p.startswith("devices.")]
    finally:
        plugin.shutdown(ctx)
        workers.stop_all()


# --------------------------------------------------------------------------- #
# 2. Ключ частоты                                                             #
# --------------------------------------------------------------------------- #


def _publish_100(*, protocol: str = "v2", **extra: Any) -> tuple[_RecordingStateProxy, str, int]:
    """Сервер поднят (без воркера паблишера), фейк-часы 0.05 с, 100 вызовов ``_publish_once``."""
    rec = _RecordingStateProxy()
    plugin, ctx, services, workers = _build_robot_host(rec, protocol=protocol, **extra)
    try:
        plugin._start_server(ctx)
        assert plugin._state == "running", f"сервер не поднялся: {plugin._reason!r}"
        now = [0.0]
        plugin._clock = lambda: now[0]
        for i in range(100):
            now[0] = i * 0.05
            plugin._publish_once()
        return rec, plugin._state, _health_errors(services)  # состояние ДО shutdown
    finally:
        plugin.shutdown(ctx)
        workers.stop_all()


def test_rate_key() -> None:
    rec, _state, errors = _publish_100(robot_state_hz=0)
    assert rec.count(_ROBOT_STATE) == 0, "robot_state_hz=0 — публикация обязана быть выключена"
    assert rec.count("sim.belt.encoder") == 100, "контроль: энкодер пишется на каждый вызов"
    assert errors == 0

    rec, _state, errors = _publish_100()  # ключа нет вовсе
    assert rec.count(_ROBOT_STATE) == 0, "по умолчанию (ключа нет) публикация выключена"

    rec, _state, errors = _publish_100(robot_state_hz=4)
    assert rec.count(_ROBOT_STATE) == pytest.approx(20, abs=1), "hz=4 при шаге 0.05 с на 5 с -> 20 записей"
    assert rec.count("sim.belt.encoder") == 100
    assert errors == 0

    rec, _state, errors = _publish_100(robot_state_hz=20)
    assert rec.count(_ROBOT_STATE) == pytest.approx(100, abs=1), "hz=20 (предел при publish_ms=50) -> каждая публикация"
    assert errors == 0

    for bad in (-1, "abc", True, 21):
        rec, state, errors = _publish_100(robot_state_hz=bad)
        assert rec.count(_ROBOT_STATE) == 0, f"robot_state_hz={bad!r}: публикация обязана быть выключена"
        assert rec.count("sim.belt.encoder") == 100, f"robot_state_hz={bad!r}: энкодер обязан работать"
        assert state == "running", f"robot_state_hz={bad!r}: состояние {state!r}"
        assert errors == 1, f"robot_state_hz={bad!r}: ожидался ровно один отказ в health, их {errors}"

    rec, _state, _errors = _publish_100(protocol="v1", robot_state_hz=20)
    assert rec.count(_ROBOT_STATE) == 0, "v1 не публикует sim.robot.state"


# --------------------------------------------------------------------------- #
# 3. Источник читает так же, как ядро                                         #
# --------------------------------------------------------------------------- #


def test_source_read_matches_core() -> None:
    ls = _line_source()
    core = _core_at(POSE_A)
    snap = json.loads(json.dumps(_bare_plugin()._robot_state_snapshot(core)))
    src = ls.LineRobotState()
    src.update(snap)

    for base, count in ((_RES, 12), (_TLM, 32), (_PMIR, 128)):
        for address in range(base, base + count):
            assert src.read(address) == core.read(address, 1), f"слово 0x{address:04X}"
        assert src.read(base, count) == core.read(base, count), f"блок 0x{base:04X}"
    assert src.joints() == pytest.approx(list(core.joints()))
    ws_src, ws_core = src._workspace(), core._workspace()
    assert vars(ws_src) == vars(ws_core) if hasattr(ws_core, "__dict__") else ws_src == ws_core
    with pytest.raises(KeyError):
        src.read(0x2000)

    bad = dict(snap, model="OtherModel")
    with pytest.raises(ValueError) as info:
        ls.LineRobotState().update(bad)
    assert str(info.value) == "модель линии не поддерживается видом: нужна ScaraModel"
    assert "OtherModel" not in str(info.value)


# --------------------------------------------------------------------------- #
# 4. Три вида рисуют позу линии                                               #
# --------------------------------------------------------------------------- #


def test_views_draw_line_pose(qtbot) -> None:
    ls = _line_source()
    src = ls.LineRobotState()
    src.update(_snapshot(POSE_A))
    view, zscale, tape = SimView(src), ZScale(src), TimeTape(src)
    for w in (view, zscale, tape):
        qtbot.addWidget(w)
    assert view.status_text().startswith(_STATUS_A), view.status_text()
    assert zscale.z_value() == pytest.approx(-60.0, abs=0.05)
    assert tape.samples()[-1][1:] == pytest.approx((-60.0, 10.0), abs=0.05)

    src.update(_snapshot(POSE_B))
    view.refresh()
    zscale.refresh()
    tape.refresh()
    assert view.status_text().startswith(_STATUS_B), view.status_text()
    assert zscale.z_value() == pytest.approx(-90.0, abs=0.05)
    assert tape.samples()[-1][1:] == pytest.approx((-90.0, -20.0), abs=0.05)


# --------------------------------------------------------------------------- #
# 5. Поза по сокету (push | poll)                                             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("mode", ["push", "poll"])
def test_pose_over_socket(mode: str) -> None:
    ls = _line_source()
    snap_a, snap_b = _snapshot(POSE_A), _snapshot(POSE_B)
    host = _LineHost()
    second: SocketClient | None = None
    link = None
    try:
        host.put(snap_a)
        seen_by_second: list[tuple[str, Any]] = []
        if mode == "push":  # как backend_ctl лида: второй подписчик на то же дерево, соединение живёт весь тест
            second = SocketClient(HOST, host.port, sender="backend_ctl")
            second.connect()
            proxy = RemoteStateProxy(second, dispatch=lambda fn: fn())
            proxy.subscribe(
                _ROBOT_STATE + ".**",
                lambda deltas: seen_by_second.extend((d.path, d.new_value) for d in deltas),
                sync=False,
            )
        link = ls.LineLink(HOST, host.port, mode=mode, poll_ms=100)
        run_with_deadline(link.open, timeout=5.0, label="link.open")

        assert _pump(link, lambda: _src_pose(link.source) == pytest.approx(POSE_A, abs=0.05), 2.0), (
            f"поза А не дошла за 2.0 с: {_src_pose(link.source)}"
        )
        host.put(snap_b)
        assert _pump(link, lambda: _src_pose(link.source) == pytest.approx(POSE_B, abs=0.05), 2.0), (
            f"поза Б не дошла за 2.0 с: {_src_pose(link.source)}"
        )
        if mode == "poll":
            assert host.count("state.subscribe") == 0, "poll не должен подписываться"
            assert host.count("state.get_subtree") >= 1, "poll обязан читать state.get_subtree"
        else:

            def _second_sees_b() -> bool:
                return any(
                    (p == _ROBOT_STATE and isinstance(v, dict) and v.get("pose", {}).get("x_mm") == POSE_B[0])
                    or (p.endswith("pose.x_mm") and v == POSE_B[0])
                    for p, v in seen_by_second
                )

            assert _wait(_second_sees_b, 2.0), f"второй клиент не увидел позу Б: {seen_by_second[-3:]}"
        t0 = time.monotonic()
        run_with_deadline(link.close, timeout=2.0, label="link.close")
        assert time.monotonic() - t0 <= 2.0
        link = None
    finally:
        if link is not None:
            try:
                link.close()
            except Exception:  # noqa: BLE001, S110
                pass
        if second is not None:
            second.close()
        host.close()


# --------------------------------------------------------------------------- #
# 6-7. main без своего ядра; без линии — код 2                                #
# --------------------------------------------------------------------------- #

_WRAPPER = """\
import atexit, os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from Services.robot_comm.server import sim_core_v2 as _core_module
_made = [0]
_orig_init = _core_module.RobotSimCoreV2.__init__
def _counting_init(self, *a, **k):
    _made[0] += 1
    _orig_init(self, *a, **k)
_core_module.RobotSimCoreV2.__init__ = _counting_init
atexit.register(lambda: print("CORES=%d" % _made[0], flush=True))
from Services.robot_comm.gui import sim_view
sim_view.main(sys.argv[1:])
"""


def _run_main(tmp_path: Path, argv: list[str], *, timeout: float) -> subprocess.CompletedProcess:
    script = tmp_path / "run_main_counting_cores.py"
    script.write_text(_WRAPPER, encoding="utf-8")
    env = dict(os.environ)
    env.update(
        PYTHONUTF8="1",
        QT_QPA_PLATFORM="offscreen",
        PYTHONPATH=str(_ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    )
    return subprocess.run(
        [sys.executable, str(script), *argv],
        cwd=str(_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


@pytest.mark.parametrize("mode", ["push", "poll"])
def test_line_mode_constructs_no_core(tmp_path: Path, mode: str) -> None:
    snap_a = _snapshot(POSE_A)
    host = _LineHost()
    try:
        host.put(snap_a)
        proc = _run_main(
            tmp_path, ["--line", f"127.0.0.1:{host.port}", "--mode", mode, "--quit-after", "1.5"], timeout=60.0
        )
    finally:
        host.close()
    assert proc.returncode == 0, f"код {proc.returncode}; stderr: {proc.stderr[-600:]}"
    assert "CORES=0" in proc.stdout, f"в режиме --line создано ядро: {proc.stdout[-300:]}"
    lines = re.findall(
        r"^\[line-view\] .*x=350\.0 y=-150\.0 z=-60\.0 rz=10\.0 moving=0 link=ok$", proc.stdout, flags=re.MULTILINE
    )
    assert len(lines) >= 3, f"строк [line-view] с позой А: {len(lines)}; stdout: {proc.stdout[-500:]}"


def test_line_mode_without_endpoint_exits(tmp_path: Path) -> None:
    port = free_port()
    proc = _run_main(tmp_path, ["--line", f"127.0.0.1:{port}"], timeout=10.0)
    assert proc.returncode == 2, f"код {proc.returncode}; stderr: {proc.stderr[-400:]}"
    assert f"нет связи с линией 127.0.0.1:{port}" in proc.stderr, f"stderr: {proc.stderr[-400:]}"
    assert "CORES=0" in proc.stdout
    with socket.socket() as probe:
        probe.settimeout(1.0)
        assert probe.connect_ex(("127.0.0.1", port)) != 0, "порт линии почему-то принимает соединения"


def test_demo_mode_constructs_one_core(tmp_path: Path) -> None:
    """Контроль (зелёный до кода): без --line демо строит ровно одно ядро."""
    proc = _run_main(tmp_path, ["--quit-after", "1"], timeout=60.0)
    assert proc.returncode == 0, f"код {proc.returncode}; stderr: {proc.stderr[-400:]}"
    assert "CORES=1" in proc.stdout, proc.stdout[-300:]


# --------------------------------------------------------------------------- #
# 8-10. Окно только для чтения, устаревшие данные, потеря и возврат связи     #
# --------------------------------------------------------------------------- #


def test_line_window_is_read_only(qtbot) -> None:
    ls = _line_source()
    host = _LineHost()
    link = None
    try:
        host.put(_snapshot(POSE_A))
        link = ls.LineLink(HOST, host.port, mode="push")
        run_with_deadline(link.open, timeout=5.0, label="link.open")
        src = link.source
        window = build_window(src, writable=False)
        qtbot.addWidget(window)
        _attach_line()(window, link)
        window.show()
        qtbot.waitExposed(window)

        assert window.findChildren(QPushButton) == [], "в окне линии есть кнопки"
        assert not hasattr(src, "write"), "у источника линии есть write"
        view = window.findChild(SimView)
        assert view is not None
        res_before, tlm_before = src.read(_RES, 12), src.read(_TLM, 32)
        qtbot.mouseClick(view, Qt.MouseButton.LeftButton)
        qtbot.wait(400)
        assert src.read(_RES, 12) == res_before and src.read(_TLM, 32) == tlm_before
        allowed = {"state.subscribe", "state.unsubscribe"}
        foreign = [c for c in host.commands() if c not in allowed and not c.startswith("state.get")]
        assert foreign == [], f"на хост ушли команды, кроме чтения: {foreign}"
    finally:
        if link is not None:
            try:
                link.close()
            except Exception:  # noqa: BLE001, S110
                pass
        host.close()


class _FakeLink:
    """Макет связи (REDS 9): данные подкладывает тест, ``tick`` ничего не делает."""

    lost = False
    last_error = None

    def __init__(self, source: Any) -> None:
        self.source = source

    def tick(self) -> None:
        pass


def test_stale_title(qtbot) -> None:
    ls = _line_source()
    attach_line = _attach_line()
    now = [100.0]
    clock = lambda: now[0]  # noqa: E731
    snap = _snapshot(POSE_A)

    src = ls.LineRobotState(clock=clock)
    src.update(snap)
    now[0] = 101.5  # данные 1.5 с назад
    window = build_window(src, writable=False)
    qtbot.addWidget(window)
    attach_line(window, _FakeLink(src), clock=clock)
    qtbot.waitUntil(lambda: "нет данных линии 1.5 с" in window.windowTitle(), timeout=3000)

    src.update(snap)  # свежий
    qtbot.waitUntil(lambda: "нет данных линии" not in window.windowTitle(), timeout=3000)

    # Хост без sim.robot.state: open() проходит, возраст неизвестен, заголовок честный.
    host = _LineHost()
    link = None
    try:
        link = ls.LineLink(HOST, host.port, mode="push")
        run_with_deadline(link.open, timeout=5.0, label="link.open")
        assert link.source.age_s() is None
        empty = build_window(link.source, writable=False)
        qtbot.addWidget(empty)
        attach_line(empty, link)
        qtbot.waitUntil(lambda: "нет данных линии" in empty.windowTitle(), timeout=3000)
    finally:
        if link is not None:
            try:
                link.close()
            except Exception:  # noqa: BLE001, S110
                pass
        host.close()


@pytest.mark.parametrize("mode", ["push", "poll"])
def test_link_lost_and_resumed(qtbot, mode: str) -> None:
    ls = _line_source()
    host = _LineHost()
    host2 = None
    link = None
    try:
        host.put(_snapshot(POSE_A))
        port = host.port
        link = ls.LineLink(HOST, port, mode=mode, poll_ms=100, retry_ms=1000)
        run_with_deadline(link.open, timeout=5.0, label="link.open")
        window = build_window(link.source, writable=False)
        qtbot.addWidget(window)
        _attach_line()(window, link)
        window.show()
        qtbot.waitExposed(window)
        view = window.findChild(SimView)
        assert view is not None
        qtbot.waitUntil(lambda: view.status_text().startswith(_STATUS_A), timeout=3000)
        assert "потеряна" not in window.windowTitle()

        host.close()  # дверь и роутер
        qtbot.waitUntil(lambda: "связь с линией потеряна" in window.windowTitle(), timeout=2000)
        assert view.status_text().startswith(_STATUS_A), "при потере связи вид обязан держать последнюю позу"
        assert window.isVisible()

        host2 = _LineHost(port=port)  # ТОТ ЖЕ порт, другое состояние
        host2.put(_snapshot(POSE_C))
        qtbot.waitUntil(
            lambda: view.status_text().startswith(_STATUS_C) and "потеряна" not in window.windowTitle(), timeout=3000
        )
        if mode == "push":
            assert host2.count("state.subscribe") >= 1, "после возврата связи push не подписался заново"
    finally:
        if link is not None:
            try:
                link.close()
            except Exception:  # noqa: BLE001, S110
                pass
        host.close()
        if host2 is not None:
            host2.close()
