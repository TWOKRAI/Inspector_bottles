# -*- coding: utf-8 -*-
"""Обвязка слепой приёмки T3.8 (``test_t38_line_view_acceptance.py``): хост линии, хост робота,
ядро в позе, запуск ``main`` в подпроцессе.

Вынесено из файла приёмки ради лимита fan-out sentrux (``no_god_files``); тела не менялись.
Хост — НАСТОЯЩИЕ ``RouterManager`` + ``StateStoreManager`` за дверью ``setup_backend_ctl_channel``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import Mock

import pytest

from multiprocess_framework.modules.process_manager_module.process.backend_ctl_endpoint import (
    setup_backend_ctl_channel,
    teardown_backend_ctl_channel,
)
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.router_module.channels.queue_channel import QueueChannel
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
from multiprocess_framework.modules.state_store_module.manager.state_store_manager import StateStoreManager
from Plugins.sim.robot_host.plugin import SimRobotHostPlugin
from Plugins.sim.robot_host.tests.host_harness import HOST, ThreadWorkerManager, free_port
from Services.robot_comm.core.protocol_v2 import KIND, OP, REG
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

_ROOT = Path(__file__).resolve().parents[3]
_ROBOT_STATE = "sim.robot.state"


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
