# -*- coding: utf-8 -*-
"""Стенд-водитель v2 для приёмки T2.4 (хост sim v2 на фреймворке).

ponytail: временный до ``client_v2`` — синхронный ``ModbusSdkClient`` + рукописный
mailbox-хендшейк (по образцу ``_write_cmd``/``_wait_res`` из
``Services/robot_comm/tests/test_sim_v2_tcp.py`` @ 6cf91f824). Когда появится настоящий
клиент v2, водитель удаляется, тесты переезжают на него.

Состав:
  * ``ThreadWorkerManager`` — менеджер воркеров, который ЗАПУСКАЕТ цель в потоке
    (``MockWorkerManager`` из ``plugins.testing`` только пишет вызов — под ним v2-хост,
    у которого тик и слушатель идут воркерами, не получил бы ни тика, ни порта).
    Контракт воркера взят из ``worker_module/ARCHITECTURE.md``: ``target(stop_event,
    pause_event)`` зовётся ОДИН раз и сам крутит цикл; ``create_worker`` на занятое имя
    возвращает ``False`` (как настоящий менеджер) — освободить имя можно только
    ``remove_worker``.
  * ``make_host`` — плагин ``SimRobotHostPlugin`` + реальный ``PluginContext`` на фейковых
    сервисах с ``ThreadWorkerManager``.
  * ``V2Driver`` — клиент по Modbus TCP: probe, ``cmd``, ``wait_done``, ``heartbeat``.

Каждый блокирующий вызов — с дедлайном. Константы протокола — только из ``protocol_v2``.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Any, Callable

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Plugins.sim.robot_host.plugin import SimRobotHostPlugin
from Services.modbus.core.config import ModbusConfig, TransportType
from Services.modbus.sdk.client import ModbusSdkClient
from Services.robot_comm.core.protocol_v2 import CONSTANTS, OP, REG
from Services.robot_comm.core.registers import ROBOT_UNIT_ID

HOST = "127.0.0.1"
ACK = 1
NAK = 2
_FORBIDDEN_PORTS = {5021, 8765, 8766, 8091, 8092}  # живой стенд владельца — не трогать
_RES_TIMEOUT_S = 3.0
_DONE_TIMEOUT_S = 30.0
_POLL_S = 0.02


def free_port() -> int:
    """Свободный TCP-порт от ОС; порты живого стенда исключены."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        port = s.getsockname()[1]
    assert port not in _FORBIDDEN_PORTS, f"порту {port} не повезло совпасть со стендом"
    return port


def run_with_deadline(fn: Callable[[], Any], *, timeout: float, label: str) -> Any:
    """``fn`` в daemon-потоке с join-дедлайном: зависание = падение теста, не подвисший прогон."""
    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — нужна любая причина
            box["exc"] = exc

    thread = threading.Thread(target=_target, name=f"deadline-{label}", daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), f"{label}: не вернулась за {timeout} с — похоже на зависание"
    if "exc" in box:
        raise box["exc"]
    return box.get("value")


class ThreadWorkerManager:
    """Менеджер воркеров, запускающий цель в реальном потоке (см. докстринг модуля)."""

    def __init__(self) -> None:
        self.calls: dict[str, list[tuple[Any, ...]]] = {"create_worker": []}
        self.errors: list[tuple[str, BaseException]] = []
        self._workers: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    @property
    def created_names(self) -> list[str]:
        return [call[0] for call in self.calls["create_worker"]]

    def create_worker(self, worker_name: str, target: Callable, config: Any = None, auto_start: bool = False) -> bool:
        self.calls["create_worker"].append((worker_name, target, config, auto_start))
        with self._lock:
            if worker_name in self._workers:
                return False
            self._workers[worker_name] = {
                "target": target,
                "stop": threading.Event(),
                "pause": threading.Event(),
                "thread": None,
            }
        if auto_start:
            self.start_worker(worker_name)
        return True

    def start_worker(self, worker_name: str) -> bool:
        with self._lock:
            info = self._workers.get(worker_name)
            if info is None or (info["thread"] is not None and info["thread"].is_alive()):
                return False

            def _run() -> None:
                try:
                    info["target"](info["stop"], info["pause"])
                except BaseException as exc:  # noqa: BLE001 — упавший воркер виден тесту
                    self.errors.append((worker_name, exc))

            # Имя с префиксом: не совпадает с именами сырых потоков v1-пути.
            info["thread"] = threading.Thread(target=_run, name=f"v2fake-worker:{worker_name}", daemon=True)
            info["thread"].start()
        return True

    def stop_worker(self, worker_name: str) -> bool:
        with self._lock:
            info = self._workers.get(worker_name)
        if info is None:
            return False
        info["stop"].set()
        thread = info["thread"]
        if thread is not None:
            thread.join(timeout=3.0)
        return True

    def remove_worker(self, worker_name: str) -> bool:
        ok = self.stop_worker(worker_name)
        with self._lock:
            self._workers.pop(worker_name, None)
        return ok

    def pause_worker(self, worker_name: str) -> bool:
        info = self._workers.get(worker_name)
        if info is None:
            return False
        info["pause"].set()
        return True

    def resume_worker(self, worker_name: str) -> bool:
        info = self._workers.get(worker_name)
        if info is None:
            return False
        info["pause"].clear()
        return True

    def is_worker_running(self, worker_name: str) -> bool:
        info = self._workers.get(worker_name)
        return bool(info and info["thread"] is not None and info["thread"].is_alive())

    def stop_all(self) -> None:
        """Подстраховка teardown: погасить всех, кого плагин не снял сам."""
        for name in list(self._workers):
            self.stop_worker(name)


def make_host(
    port: int, **extra_cfg: Any
) -> tuple[SimRobotHostPlugin, PluginContext, MockProcessServices, ThreadWorkerManager]:
    """Плагин хоста + контекст; ``protocol`` и прочее — через ``extra_cfg``."""
    services = MockProcessServices(name="robot")
    workers = ThreadWorkerManager()
    services.worker_manager = workers
    cfg: dict[str, Any] = {"host": HOST, "port": port, "unit_id": ROBOT_UNIT_ID, "auto_start": True}
    cfg.update(extra_cfg)
    ctx = PluginContext(services=services, config=cfg)
    assert ctx.worker_manager is workers, "ctx.worker_manager не наш менеджер — воркеры хоста не запустятся"
    plugin = SimRobotHostPlugin()
    plugin.configure(ctx)
    return plugin, ctx, services, workers


def call(plugin: SimRobotHostPlugin, name: str, data: dict | None = None) -> dict:
    """Команда плагина через публичный контракт ``plugin.commands``."""
    return getattr(plugin, plugin.commands[name])(data)


def to_u16(value: int) -> int:
    return value & 0xFFFF


def to_s16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value >= 0x8000 else value


def mm10(value_mm: float) -> int:
    """Миллиметры/градусы -> слово провода (шаг 0.1, как ``_mm`` в старом TCP-тесте)."""
    return round(value_mm * 10)


class V2Driver:
    """Синхронный водитель v2: probe, ``cmd(op, *args)``, ``wait_done``, ``heartbeat``."""

    def __init__(self, port: int, host: str = HOST) -> None:
        self._client = ModbusSdkClient(
            ModbusConfig(transport=TransportType.TCP, host=host, port=port, unit_id=ROBOT_UNIT_ID)
        )
        self._seq = 0
        self._hb = 0

    def connect(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if run_with_deadline(self._client.connect, timeout=timeout, label="driver.connect"):
                return True
            time.sleep(0.05)
        return False

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # noqa: BLE001 — закрытие в finally не должно маскировать причину падения
            pass

    def read(self, addr: int, count: int) -> list[int]:
        """Один FC3."""
        regs = run_with_deadline(lambda: self._client.read_holding(addr, count), timeout=5.0, label="driver.read")
        assert regs is not None and len(regs) == count, f"FC3 {addr:#06x}x{count}: ответ {regs!r}"
        return list(regs)

    def probe(self) -> int:
        """Проба до любых записей (§12): ``TLM_PROTO_VER``."""
        return self.read(REG["TLM_PROTO_VER"], 1)[0]

    def heartbeat(self) -> None:
        self._hb = self._hb % 0xFFFF + 1
        self._client.write_register(REG["HB_PC"], self._hb)

    def _op(self, op: int | str) -> int:
        return OP[op] if isinstance(op, str) else op

    def cmd(self, op: int | str, *args: int, timeout: float = _RES_TIMEOUT_S) -> dict:
        """Записать команду в mailbox (``CMD_FLAG`` последним) и дождаться ``RES_SEQ``."""
        self._seq += 1
        seq = self._seq
        values = [to_u16(seq), self._op(op), len(args)] + [to_u16(a) for a in args]
        self._client.write_registers(REG["CMD_SEQ"], values)
        self._client.write_register(REG["CMD_FLAG"], 1)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.read(REG["RES_SEQ"], 1)[0] == seq:
                status, errno, rvalc = self.read(REG["RES_STATUS"], 3)
                rvals = self.read(REG["RES_RVALS"], 8)[:rvalc]
                return {"seq": seq, "status": status, "errno": errno, "rvalc": rvalc, "rvals": rvals}
            time.sleep(_POLL_S)
        raise AssertionError(f"RES_SEQ не стал {seq} за {timeout} с (op={op!r})")

    def wait_done(self, seq: int, timeout: float = _DONE_TIMEOUT_S) -> None:
        """Ждать ``TLM_DONE_SEQ == seq``; ``PC``-heartbeat — в каждом опросе. Ошибка — AssertionError."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.heartbeat()
            if self.read(REG["TLM_DONE_SEQ"], 1)[0] == to_u16(seq):
                return
            if self.read(REG["TLM_ERR_SEQ"], 1)[0] == to_u16(seq):
                errno = self.read(REG["TLM_ERRNO_LAST"], 1)[0]
                raise AssertionError(f"команда seq={seq} кончилась ошибкой errno={errno}")
            time.sleep(_POLL_S)
        raise AssertionError(f"TLM_DONE_SEQ не стал {seq} за {timeout} с")

    def tlm(self, name: str) -> int:
        return self.read(REG[name], 1)[0]

    def encoder(self) -> int:
        """``TLM_ENC`` — два слова, младшее первым."""
        lo, hi = self.read(REG["TLM_ENC"], 2)
        return lo | (hi << 16)

    def param_get(self, param_id: int) -> int:
        """``PARAM_GET`` -> первое слово результата как s16."""
        res = self.cmd("PARAM_GET", param_id)
        assert res["status"] == ACK, f"PARAM_GET {param_id}: {res}"
        return to_s16(res["rvals"][0])


assert CONSTANTS["PROTO_VER"] == 0x0200  # водитель и тесты говорят об одной версии
