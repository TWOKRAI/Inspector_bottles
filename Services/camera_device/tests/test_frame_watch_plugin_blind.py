# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты W2-t2: плагин камеры замечает «триггер без кадра» (блок `frame_watch`, `trigger_seen`).

Написаны ДО кода по `plans/2026-11-25_multicam-observability/tasks/W2-t2.md` и `plate-modes.md`. Плагин, сеанс,
`WorkerManager`, `StateProxy` с деревом и хранилище уровней — настоящие; порт — фейк ядра (для программного
триггера и поздних кадров у него обёрнуты `get_frame`/`execute`). Проверяется наблюдаемое: блок в дереве,
ответы команд, метрика `trigger_missed`, строки журнала. Ожидаемые значения — литералы из спеки.
Вызов плагина, который может зависнуть, идёт в daemon-потоке с дедлайном `join`.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.heartbeat.telemetry import PluginLevels
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
from multiprocess_framework.modules.state_store_module.proxy.state_proxy import StateProxy
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device import plugin_base
from Services.camera_device.frame_watch import FrameWatch
from Services.camera_device.interface import PortError
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.testing import fake_port

_PROCESS = "cam_fw"
_NODE = f"processes.{_PROCESS}.state.plugins.camera_device"
_CFG = {
    "auto_start": False,
    "camera_id": 3,
    "device_select": "serial",
    "device_serial": "FAKE-0001",
    "timeout_ms": 100,
    "frame_watch": "message",
    "frame_watch_deadline_ms": 200,
}
_RECONNECT = {"reconnect": True, "link_silence_s": 0.5, "reconnect_interval_s": 0.5}
_WARN = "триггер без кадра"
_CLOSED = "кадр после пропуска триггера"
_REFUSAL = "trigger_seen: frame_watch не message"
_BLOCK_KEYS = {"source", "deadline_ms", "triggers", "misses", "open_miss", "last_miss_ts"}


def _call(fn: Callable[[], Any], deadline: float = 8.0) -> Any:
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — исключение возвращается тесту
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(deadline)
    assert not worker.is_alive(), f"вызов не вернулся за {deadline} с"
    if "error" in box:
        raise box["error"]
    return box.get("result")


class _TreeRouter:
    """Приёмник настоящего `StateProxy`: `merge`/`delete` в настоящее дерево."""

    def __init__(self, store: TreeStore) -> None:
        self.store = store

    def send_async(self, msg: dict, priority: str = "normal") -> None:
        data = msg["data"]
        if msg["command"] == "state.merge":
            self.store.merge(data["path"], data["data"])
        elif msg["command"] == "state.delete":
            self.store.delete(data["path"])


class _Gate:
    """Обёртка фейка: кадр отдаётся только по разрешению (`give` или `execute` в режиме `frame`)."""

    def __init__(self, port: Any) -> None:
        self.port = port
        self.on_execute = "frame"  # `frame` — кадр после execute; `silent` — кадра не будет; `raise` — отказ прибора
        self.delivered = 0
        self._permits = 0
        self._lock = threading.Lock()
        self._get_frame = port.get_frame
        self._execute = port.execute
        port.get_frame = self.get_frame
        port.execute = self.execute

    def give(self, count: int = 1) -> None:
        with self._lock:
            self._permits += count

    def get_frame(self, timeout_ms: int) -> Any:
        with self._lock:
            allowed = self._permits > 0
            if allowed:
                self._permits -= 1
        if not allowed:
            time.sleep(0.005)
            return None
        frame = self._get_frame(timeout_ms)
        if frame is not None:
            self.delivered += 1
        return frame

    def execute(self, binding: Any) -> None:
        self._execute(binding)
        if self.on_execute == "raise":
            raise PortError("network", "execute")
        if self.on_execute == "frame":
            self.give()


class _Rig:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, port: Any, **cfg: Any) -> None:
        self.port = port
        config = {**_CFG, **cfg}
        monkeypatch.setattr(plugin_base, "create_port", lambda driver: port)
        self.services = MockProcessServices(name=_PROCESS, config=config, plugin_levels=PluginLevels())
        self.wm = WorkerManager("test_frame_watch_plugin_blind")
        self.services.worker_manager = self.wm
        self.ctx = PluginContext(services=self.services, config=config, plugin_name="camera_device")
        self.tree = TreeStore()
        self.ctx.state_proxy = StateProxy(_PROCESS, router=_TreeRouter(self.tree))
        self.plugin = CameraDevicePlugin()
        self.plugin.configure(self.ctx)

    # -- команды ------------------------------------------------------------------------------- #

    def take(self) -> None:
        assert _call(lambda: self.plugin.cmd_take_device({}))["status"] == "ok"

    def command(self, name: str, data: dict | None = None) -> dict:
        """Команда по имени из `commands` плагина (то, что регистрирует процесс)."""
        assert name in self.plugin.commands, f"команда {name!r} не объявлена плагином"
        handler = getattr(self.plugin, self.plugin.commands[name])
        return _call(lambda: handler(data or {}))

    def seen(self) -> None:
        assert self.command("trigger_seen") == {"success": True}

    # -- наблюдения ---------------------------------------------------------------------------- #

    def node(self) -> dict:
        return dict(self.tree.get(_NODE, None) or {})

    def block(self) -> dict:
        return dict(self.node().get("frame_watch") or {})

    def link_state(self) -> str | None:
        return (self.node().get("link") or {}).get("state")

    def metric(self) -> Any:
        return self.services.plugin_levels.publications().get("camera_device", {}).get("trigger_missed")

    def lines(self, level: str, part: str) -> list[str]:
        return [e["msg"] for e in list(self.services.logs) if e["level"] == level and part in e["msg"]]

    # -- ведение produce ----------------------------------------------------------------------- #

    def produce(self) -> None:
        _call(self.plugin.produce)

    def drive(self, seconds: float) -> None:
        """Звать `produce()` как процесс-источник, пауза 10 мс."""

        def run() -> None:
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                self.plugin.produce()
                time.sleep(0.01)

        _call(run, seconds + 8.0)

    def drive_until(self, pred: Callable[[], bool], message: str, deadline: float = 3.0) -> None:
        def run() -> bool:
            end = time.monotonic() + deadline
            while time.monotonic() < end:
                self.plugin.produce()
                if pred():
                    return True
                time.sleep(0.01)
            return False

        assert _call(run, deadline + 8.0), (
            f"не дождались за {deadline} с: {message}; блок frame_watch={self.block()}, metric={self.metric()}"
        )

    def wait_misses(self, count: int) -> None:
        self.drive_until(lambda: self.block().get("misses") == count, f"misses == {count}")

    def close(self) -> None:
        try:
            if getattr(self.plugin, "_session", None) is not None:
                _call(lambda: self.plugin.shutdown(self.ctx), 10.0)
        finally:
            self.wm.stop_all_workers(2.0)


@pytest.fixture
def make(monkeypatch):
    rigs: list[_Rig] = []

    def factory(port: Any = None, **cfg: Any) -> _Rig:
        port = port if port is not None else fake_port.make_port(frame_period_s=0.01)
        built = _Rig(monkeypatch, port, **cfg)
        rigs.append(built)
        return built

    yield factory
    for built in rigs:
        built.close()


def _unplugged(make, **cfg: Any) -> _Rig:
    """Захват идёт, кабель вынут: кадров больше нет (без `reconnect` сеанс остаётся в `grabbing`)."""
    rig = make(**cfg)
    rig.take()
    rig.drive(0.1)
    rig.port.disconnect()
    rig.drive(0.2)  # кадр, уже летевший в момент обрыва, дошёл
    return rig


def _gated(make, **cfg: Any) -> tuple[_Rig, _Gate]:
    gate = _Gate(fake_port.make_port())
    rig = make(gate.port, **cfg)
    rig.take()
    return rig, gate


# ---------------------------------------------------------------------------------------------- #
# Источник `message`
# ---------------------------------------------------------------------------------------------- #


def test_trigger_seen_is_a_declared_command(make):
    assert make().plugin.commands.get("trigger_seen") == "cmd_trigger_seen"


def test_message_without_frame_opens_miss(make, monkeypatch):
    """Окно `_TICK_S` 5 с: `open_miss` обязан дойти до дерева раньше окна."""
    monkeypatch.setattr(plugin_base, "_TICK_S", 5.0)
    rig = _unplugged(make)
    rig.seen()

    rig.drive_until(lambda: rig.block().get("open_miss") is True, "open_miss True", deadline=2.0)
    block = rig.block()
    assert set(block) == _BLOCK_KEYS
    assert (block["source"], block["deadline_ms"], block["misses"], block["open_miss"]) == ("message", 200, 1, True)
    rig.drive_until(lambda: rig.metric() == 1, "метрика trigger_missed 1", deadline=8.0)
    warnings = rig.lines("WARNING", _WARN)
    assert len(warnings) == 1, warnings
    assert "триггер без кадра: срок 200 мс" in warnings[0]


def test_last_miss_ts_is_wall_time_of_episode_start(make):
    """`last_miss_ts` — `time.time()` открытия эпизода; второй пропуск того же эпизода его не двигает."""
    rig = _unplugged(make)
    before = time.time()
    rig.seen()
    rig.wait_misses(1)
    after = time.time()

    first = rig.block()["last_miss_ts"]
    assert before - 0.05 <= first <= after + 0.05, (before, first, after)
    time.sleep(0.3)
    rig.seen()
    rig.wait_misses(2)
    assert rig.block()["last_miss_ts"] == first


def test_frame_closes_miss(make):
    rig = _unplugged(make, **_RECONNECT)
    rig.seen()
    rig.wait_misses(1)
    assert rig.block()["open_miss"] is True
    # кабель вставляется ПОСЛЕ того, как сеанс заметил обрыв: иначе переоткрытия нет и кадры не вернутся
    rig.drive_until(lambda: rig.link_state() == "lost", "связь потеряна", deadline=6.0)

    rig.port.restore()
    rig.drive_until(lambda: rig.block().get("open_miss") is False, "open_miss False после кадра", deadline=8.0)
    rig.drive(1.2)

    assert rig.block()["misses"] == 1
    closed = rig.lines("INFO", _CLOSED)
    assert len(closed) == 1, closed
    assert "кадр после пропуска триггера, пропущено 1" in closed[0]


def test_close_info_counts_misses_of_each_episode_separately(make):
    """`k` — пропуски ЭТОГО эпизода: первый эпизод 2, второй 1 (не 3)."""
    rig, gate = _gated(make)
    rig.seen()
    rig.wait_misses(1)
    rig.seen()
    rig.wait_misses(2)
    gate.give()
    rig.drive_until(lambda: rig.block().get("open_miss") is False, "первый эпизод закрыт")
    rig.seen()
    rig.wait_misses(3)
    gate.give()
    rig.drive_until(lambda: rig.block().get("open_miss") is False, "второй эпизод закрыт")
    rig.drive(0.2)

    closed = rig.lines("INFO", _CLOSED)
    assert len(closed) == 2, closed
    assert "пропущено 2" in closed[0]
    assert "пропущено 1" in closed[1]
    assert len(rig.lines("WARNING", _WARN)) == 2


def test_late_frame_between_polls_warns_and_infos(make):
    """Кадр пришёл после срока, но до `poll`: пропуск есть, эпизод уже закрыт — WARNING и INFO в одном такте."""
    rig, gate = _gated(make)
    rig.seen()
    time.sleep(0.5)  # срок 200 мс прошёл, `produce()` не звали
    gate.give()
    end = time.monotonic() + 3.0
    while gate.delivered < 1 and time.monotonic() < end:
        time.sleep(0.01)
    assert gate.delivered == 1
    time.sleep(0.1)  # колбэк кадра отработал
    rig.produce()

    assert len(rig.lines("WARNING", _WARN)) == 1
    closed = rig.lines("INFO", _CLOSED)
    assert len(closed) == 1, closed
    assert "пропущено 1" in closed[0]
    rig.drive_until(lambda: rig.block().get("misses") == 1, "misses 1 в дереве")
    assert rig.block()["open_miss"] is False


def test_free_run_trigger_with_frame_no_miss(make):
    rig = make()
    rig.take()
    rig.drive(0.2)
    rig.seen()
    rig.drive(1.0)
    rig.drive_until(lambda: rig.block().get("triggers") == 1, "triggers 1 в дереве")

    assert rig.block()["misses"] == 0
    assert rig.block()["open_miss"] is False
    assert rig.lines("WARNING", _WARN) == []


def test_repeated_misses_one_warning(make):
    rig = _unplugged(make)
    for count in (1, 2, 3):
        rig.seen()
        rig.wait_misses(count)
    rig.drive(0.3)

    assert rig.block()["misses"] == 3
    assert len(rig.lines("WARNING", _WARN)) == 1


def test_metric_trigger_missed_is_cumulative(make):
    rig = _unplugged(make)
    for count in (1, 2):
        rig.seen()
        rig.wait_misses(count)
    rig.drive_until(lambda: rig.metric() == 2, "метрика trigger_missed 2")


def test_message_source_ignores_trigger_software(make):
    rig = make()
    rig.take()
    assert rig.command("trigger_software") == {"success": True}
    rig.drive(1.3)

    assert rig.block().get("triggers") == 0
    assert rig.block()["misses"] == 0


# ---------------------------------------------------------------------------------------------- #
# Источник `software`
# ---------------------------------------------------------------------------------------------- #


def test_software_source_counts_trigger_software(make):
    """Кадр приходит только после `execute`: импульс, записанный позже вызова, дал бы ложный пропуск."""
    rig, gate = _gated(make, frame_watch="software", frame_watch_deadline_ms=1000)
    for number in range(1, 21):
        assert rig.command("trigger_software") == {"success": True}
        end = time.monotonic() + 2.0
        while gate.delivered < number and time.monotonic() < end:
            time.sleep(0.005)
        assert gate.delivered == number
        rig.produce()
    rig.drive(1.5)  # дольше срока и окна публикации

    assert rig.block().get("source") == "software"
    assert rig.block()["triggers"] == 20
    assert rig.block()["misses"] == 0


def test_software_source_refuses_trigger_seen(make):
    rig, _gate = _gated(make, frame_watch="software")
    reply = rig.command("trigger_seen")
    rig.drive(1.2)

    assert reply.get("success") is False
    assert reply.get("error") == _REFUSAL
    assert rig.block()["triggers"] == 0


def test_software_failed_execute_withdraws_only_its_pulse(make):
    """`execute` бросил: `triggers` не вырос, а более ранний ждущий импульс остался и стал пропуском."""
    rig, gate = _gated(make, frame_watch="software", frame_watch_deadline_ms=1500)
    gate.on_execute = "silent"
    assert rig.command("trigger_software") == {"success": True}  # импульс ждёт кадр
    gate.on_execute = "raise"
    assert rig.command("trigger_software")["success"] is False
    rig.drive_until(lambda: rig.block().get("misses", 0) >= 1, "ранний импульс просрочен", deadline=5.0)
    rig.drive(1.3)

    assert rig.block()["triggers"] == 1
    assert rig.block()["misses"] == 1


def test_software_refused_trigger_not_counted(make):
    """Сеанс не в захвате: `trigger_software` отказан, `execute` не звался — импульса нет."""
    rig, _gate = _gated(make, frame_watch="software")
    assert _call(lambda: rig.plugin.cmd_release_device({}))["status"] == "ok"
    assert rig.command("trigger_software")["success"] is False
    rig.drive(1.3)

    assert rig.block().get("triggers") == 0
    assert rig.block()["misses"] == 0


# ---------------------------------------------------------------------------------------------- #
# Пауза, простой, обрыв, сбросы
# ---------------------------------------------------------------------------------------------- #


def test_pulses_before_run_dropped(make):
    """Импульс, пришедший на паузе: ответ success, ни `triggers`, ни `misses`."""
    rig = _unplugged(make)
    _call(lambda: rig.plugin.pause(rig.ctx))
    rig.seen()
    _call(lambda: rig.plugin.resume(rig.ctx))
    time.sleep(0.5)
    rig.produce()
    rig.drive(1.2)

    assert rig.block().get("triggers") == 0
    assert rig.block()["misses"] == 0
    assert rig.lines("WARNING", _WARN) == []


def test_pause_drops_pending_pulse(make):
    """Импульс принят до паузы и ещё ждёт: пауза его забывает, пропуска после `resume` нет."""
    rig = _unplugged(make, frame_watch_deadline_ms=1000)
    rig.seen()
    _call(lambda: rig.plugin.pause(rig.ctx))
    _call(lambda: rig.plugin.resume(rig.ctx))
    time.sleep(1.2)
    rig.produce()
    rig.drive(1.2)

    assert rig.block().get("triggers") == 1
    assert rig.block()["misses"] == 0


def test_pulses_counted_again_after_resume(make):
    rig = _unplugged(make)
    _call(lambda: rig.plugin.pause(rig.ctx))
    _call(lambda: rig.plugin.resume(rig.ctx))
    rig.seen()
    rig.wait_misses(1)

    assert rig.block()["triggers"] == 1


def test_stall_keeps_miss(make):
    """1,2 с без `produce` и без `pause`: первый же `produce()` считает пропуск."""
    rig = _unplugged(make)
    rig.seen()
    time.sleep(1.2)
    rig.produce()

    assert rig.block().get("misses") == 1
    assert rig.block()["open_miss"] is True


def test_reconnect_without_frame_keeps_open_miss(make):
    """Камера по триггеру: обрыв, импульс без кадра, переподключение в `grabbing` без кадров — эпизод открыт."""
    gate = _Gate(fake_port.make_port())  # разрешений на кадр никто не даёт: триггеров на приборе нет
    rig = make(gate.port, trigger_managed=True, trigger_mode="On", trigger_source="Line0", **_RECONNECT)
    rig.take()
    rig.drive(0.1)
    gate.port.disconnect()
    rig.drive_until(lambda: rig.link_state() == "lost", "связь потеряна", deadline=6.0)
    rig.seen()  # импульс во время обрыва — пропуск
    rig.wait_misses(1)

    gate.port.restore()
    rig.drive_until(lambda: rig.link_state() not in (None, "lost"), "связь вернулась", deadline=8.0)
    rig.drive(1.3)

    assert rig.node()["state"] == "grabbing"
    assert gate.delivered == 0
    assert rig.block()["open_miss"] is True
    assert rig.block()["misses"] == 1


def test_reset_stats_resets_counts(make):
    rig = _unplugged(make)
    rig.seen()
    rig.wait_misses(1)
    assert rig.command("reset_stats") == {"success": True}
    rig.drive_until(lambda: rig.block().get("misses") == 0, "misses 0 после reset_stats")
    rig.drive(0.2)

    assert rig.block()["triggers"] == 0
    assert rig.block()["misses"] == 0
    assert rig.block()["open_miss"] is False
    assert rig.lines("INFO", _CLOSED) == []


def test_release_device_closes_episode_without_info(make):
    rig = _unplugged(make)
    rig.seen()
    rig.wait_misses(1)
    assert _call(lambda: rig.plugin.cmd_release_device({}))["status"] == "ok"
    rig.drive_until(lambda: rig.block().get("open_miss") is False, "open_miss False после release_device")
    rig.drive(0.2)

    assert rig.block()["misses"] == 1
    assert rig.lines("INFO", _CLOSED) == []


def test_release_device_drops_pending_pulse(make):
    rig = _unplugged(make, frame_watch_deadline_ms=1000)
    rig.seen()
    assert _call(lambda: rig.plugin.cmd_release_device({}))["status"] == "ok"
    rig.drive(2.3)

    assert rig.block().get("triggers") == 1
    assert rig.block()["misses"] == 0


def test_new_take_cycle_drops_pending_pulse(make):
    """Новый цикл (`opening`) забывает ждущий импульс, принятый без прибора в захвате."""
    rig, _gate = _gated(make, frame_watch_deadline_ms=1000)  # кадров нет и в новом цикле
    assert _call(lambda: rig.plugin.cmd_release_device({}))["status"] == "ok"
    rig.seen()
    rig.take()
    rig.drive(2.3)

    assert rig.block().get("triggers") == 1
    assert rig.block()["misses"] == 0


# ---------------------------------------------------------------------------------------------- #
# `off`
# ---------------------------------------------------------------------------------------------- #


def test_off_publishes_off_block_and_refuses(make, monkeypatch):
    polls: list[float] = []
    original = FrameWatch.poll
    monkeypatch.setattr(FrameWatch, "poll", lambda self, now: (polls.append(now), original(self, now))[1])
    rig = make(frame_watch="off")
    rig.take()
    reply = rig.command("trigger_seen")
    rig.drive(1.2)

    assert reply.get("success") is False
    assert reply.get("error") == _REFUSAL
    block = rig.block()
    assert set(block) == _BLOCK_KEYS
    assert block["source"] == "off"
    assert (block["triggers"], block["misses"], block["open_miss"], block["last_miss_ts"]) == (0, 0, False, None)
    assert polls == []
