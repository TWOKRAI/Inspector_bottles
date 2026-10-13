# -*- coding: utf-8 -*-
"""Обвязка хоста sim v2 для тестов ``robot_host`` (менеджер воркеров, плагин, клиент v2 по TCP).

Purpose: поднять хост ``SimRobotHostPlugin`` на фреймворке и ходить к нему настоящим клиентом
``RobotClientV2`` поверх ``ModbusDevice`` (Modbus TCP). Протокола руками здесь нет: команды и
ожидание DONE — обёртки клиента, чтения регистров — по имени из ``REG``.

Public API: ``HOST``, ``ThreadWorkerManager``, ``call``, ``close_client``, ``encoder``, ``free_port``,
``make_host``, ``open_client``, ``read_reg``, ``run_with_deadline``, ``to_s16``, ``wait_done_hb``.

Stability: lite (тестовый слой, публичного API продукта нет).

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
  * ``open_client`` / ``close_client`` — устройство ``ModbusDevice`` и клиент ``RobotClientV2``
    к порту хоста; ``read_reg`` / ``encoder`` — чтение телеметрии по имени ``REG``;
    ``wait_done_hb`` — ожидание DONE с пульсом ПК в каждом опросе.

Каждый блокирующий вызов — с дедлайном.
"""

from __future__ import annotations

import random
import socket
import threading
import time
from typing import Any, Callable

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from Plugins.sim.robot_host.plugin import SimRobotHostPlugin
from Services.modbus.core.config import ModbusConfig
from Services.modbus.core.device import ModbusDevice
from Services.robot_comm.core.client_v2 import ClientV2Config, RobotClientV2
from Services.robot_comm.core.protocol_v2 import REG
from Services.robot_comm.core.registers import ROBOT_UNIT_ID

__all__ = [
    "HOST",
    "ThreadWorkerManager",
    "call",
    "close_client",
    "encoder",
    "free_port",
    "make_host",
    "open_client",
    "read_reg",
    "run_with_deadline",
    "to_s16",
    "wait_done_hb",
]

HOST = "127.0.0.1"
_FORBIDDEN_PORTS = {5021, 8765, 8766, 8091, 8092}  # живой стенд владельца — не трогать


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


def to_s16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value >= 0x8000 else value


def open_client(
    port: int, *, timeout: float = 5.0, rng: random.Random | None = None
) -> tuple[ModbusDevice, RobotClientV2]:
    """Устройство и клиент v2 к порту хоста: соединение с повтором до ``timeout``, затем ``probe()``.

    Окно ответа клиента — 3.0 с (у клиента по умолчанию 2.0); окно DONE — по умолчанию клиента (30 с).
    Любой сбой (не подключились — ``AssertionError``, дедлайн, ошибка ``probe()``) — исключение уходит
    наружу как есть, устройство перед этим закрыто."""
    device = ModbusDevice(ModbusConfig(host=HOST, port=port, unit_id=ROBOT_UNIT_ID))
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if run_with_deadline(device.connect, timeout=timeout, label="device.connect"):
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"порт {port} не принял соединение за {timeout} с")
        client = RobotClientV2(device, ClientV2Config.from_dict({"res_timeout_s": 3.0}), rng=rng)
        run_with_deadline(client.probe, timeout=5.0, label="client.probe")
    except BaseException:
        close_client(device)
        raise
    return device, client


def close_client(device: ModbusDevice) -> None:
    """Закрыть устройство; ошибка закрытия не маскирует причину падения теста."""
    try:
        device.disconnect()
    except Exception:  # noqa: BLE001 — закрытие в finally не должно маскировать причину падения
        pass


def read_reg(device: ModbusDevice, name: str, count: int = 1) -> list[int]:
    """Чтение по имени ``REG``: ОДИН запрос на ``count`` слов (один FC3)."""
    regs = run_with_deadline(lambda: device.read_registers(REG[name], count), timeout=5.0, label=f"read {name}")
    assert len(regs) == count, f"FC3 {name}x{count}: ответ {regs!r}"
    return list(regs)


def encoder(device: ModbusDevice) -> int:
    """Энкодер ленты из телеметрии — два слова, младшее первым."""
    lo, hi = read_reg(device, "TLM_ENC", 2)
    return lo | (hi << 16)


def wait_done_hb(client: RobotClientV2, seq: int, timeout: float = 40.0) -> None:
    """Ждать DONE команды ``seq``; пульс ПК — в каждом опросе. ``timeout`` — дедлайн зависания поверх окна клиента."""
    run_with_deadline(
        lambda: client.wait_done(seq, on_poll=lambda _tlm: client.kick_heartbeat()),
        timeout=timeout,
        label="wait_done",
    )
