"""Слепая приёмка R2-S1d (A1-A11): СТОП оператора не запирается готовностью драйвера.

Источник — только «Приёмка» ``plans/robot-protocol-v2/tasks/R2-S1d.md`` и правило
``docs/reviews/2026-11-27_task-R2-S1a-cto.md``. Написано до реализации.

Команды идут как из приложения: настоящий ``DeviceHubPlugin`` (``configure`` + ``start``), настоящий ``WorkerManager``
(supervisor и тик устройства — свои потоки), настоящие ``DeviceManager`` и драйверы; робот — ядро sim v2 (A6 — v1)
за ``LoopbackServer`` на ``127.0.0.1``. Сервер пишет все кадры, рвёт связь (FIN / RST), молчит, отвечает
исключением. Дублёр один — получатель публикаций вместо ``state_proxy`` (``_Publisher``).
A7 — порядок «тик первым» — идёт на стенде драйвера R2-S1a (помощники ``test_r2s1a_hazards``).

«Робот встал» само по себе не доказательство: сторож sim сам обрывает ход примерно через 3 с без пульса. Поэтому
проверяются кадр ``STOP_REQ``, эхо ``TLM_STOP_ACK``, равное значению этого кадра, остановка не позже 1 с и путь,
не дошедший до цели.

``robot_abort`` посылается с ``mode: 2`` (HARD): без ``mode`` это SOFT, а SOFT посреди хода sim откладывает до цели.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.worker_module import WorkerManager

from Plugins.hub.device_hub.plugin import DeviceHubPlugin
from Plugins.hub.device_hub.tests.conftest import make_ctx
from Services.device_hub.tests.test_r2s1a_hazards import _force_order, _op_writes, _stop
from Services.device_hub.tests.test_r2s1a_link_drop_acceptance import (
    _Sim,
    _Ticker,
    _motion_writes,
    _v2,
    _wait,
)
from Services.modbus.core.device import ModbusDevice
from Services.modbus.tests.test_r2s1a_transport_acceptance import Call, Frame, run
from Services.robot_comm.core.params_v2 import PARAM_ID
from Services.robot_comm.core.protocol_v2 import CONSTANTS, REG
from Services.robot_comm.server.sim_core import RobotSimCore
from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2

# Литералы протокола и спецификации: ожидания не выводятся из проверяемого кода
_STOP_REQ = 0x1021
_HARD = 2
_OP_CVT_JOB = 32
_TEXT_UNCONFIRMED = "стоп не подтверждён роботом"
_TEXT_CONNECT_FAILED = "подключение к роботу не удалось"
_TEXT_NOT_CONNECTED_RV1 = "Устройство 'rv1' не подключено"
_TEXT_NOT_CONNECTED_RV2 = "Устройство 'rv2' не подключено"

_DEV = "rv2"
_JOB = {"x_mm": 300.0, "y_mm": 0.0, "e_capture": 0}
# Ход вдоль Y на 150 мм со скоростью 1 % — около 10 с; свежий sim стоит в (300, -210)
_LONG_STEP = {"dx": 0.0, "dy": 150.0, "spd": 1}
_Y_SHORT_OF_TARGET = -100.0  # цель хода -60 мм; «не дошёл» — заметно раньше неё

_PRESS = {"robot_stop": {"level": "HARD"}, "robot_abort": {"mode": 2}}
_COMMANDS = ["robot_stop", "robot_abort"]

# Адрес зеркала параметра, который читает только проба (второе чтение пробы)
_PROBE_PARAM_ADDR = CONSTANTS["PMIR_BASE"] + PARAM_ID["P_WDG_TIMEOUT_MS"]


def _stop_frames(frames: list[Frame]) -> list[Frame]:
    return [f for f in frames if f.fc in (6, 16) and f.addr == _STOP_REQ]


def _levels(frames: list[Frame]) -> list[int]:
    return [f.values[0] & 3 for f in _stop_frames(frames)]


class _Publisher:
    """Вместо ``state_proxy``: все ``set`` / ``merge`` по порядку (строковый ``last_error`` стор не принимает)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[tuple[str, Any]] = []

    def set(self, path: str, data: Any) -> None:
        self._put(path, data)

    def merge(self, path: str, data: Any) -> None:
        self._put(path, data)

    def _put(self, path: str, data: Any) -> None:
        with self._lock:
            self._items.append((path, dict(data) if isinstance(data, dict) else data))

    def mark(self) -> int:
        with self._lock:
            return len(self._items)

    def _since(self, path: str, since: int) -> list[Any]:
        with self._lock:
            return [data for p, data in self._items[since:] if p == path]

    def errors(self, dev: str, since: int = 0) -> list[str]:
        return self._since(f"devices.state.{dev}.last_error", since)

    def conns(self, dev: str, since: int = 0) -> list[dict]:
        return self._since(f"devices.state.{dev}.conn", since)


class _Hub:
    """Плагин хаба с настоящими потоками и один или несколько роботов sim."""

    def __init__(self, tmp_path: Path) -> None:
        self.pub = _Publisher()
        self.sims: dict[str, _Sim] = {}
        self.ctx = make_ctx({}, tmp_registry=tmp_path / "devices.yaml", state_proxy=self.pub)
        self.workers = WorkerManager("r2s1d")
        self.workers.initialize()
        self.ctx.worker_manager = self.workers
        self.plugin = DeviceHubPlugin()
        self.plugin.configure(self.ctx)
        self.plugin.start(self.ctx)

    def add(
        self,
        dev: str = _DEV,
        *,
        protocol: str = "delta_v2",
        timeout_sec: float = 4.0,
        params: dict | None = None,
    ) -> _Sim:
        sim = _Sim(RobotSimCoreV2() if protocol == "delta_v2" else RobotSimCore())
        self.sims[dev] = sim
        entry = {
            "id": dev,
            "name": dev,
            "kind": "robot",
            "protocol": protocol,
            "transport": {
                "type": "tcp",
                "host": "127.0.0.1",
                "port": sim.server.port,
                "unit_id": 2,
                "timeout_sec": timeout_sec,
                "retries": 1,
            },
            "params": {"poll_interval_s": 0.1, **(params or {})},
        }
        reply = self.command("device_upsert", dev=None, **entry)
        assert reply["status"] == "ok", reply
        return sim

    def command(self, command_name: str, /, *, dev: str | None = _DEV, **args: Any) -> dict:
        """Команда по таблице команд плагина, в потоке-демоне со сроком."""
        handler = getattr(self.plugin, self.plugin.commands[command_name])
        data = dict(args) if dev is None else {"device_id": dev, **args}
        return run(lambda: handler(data), 30.0)

    def press(self, command: str, dev: str = _DEV) -> tuple[dict, float]:
        """Нажатие СТОП: ответ и длительность команды, с."""
        started = time.monotonic()
        reply = self.command(command, dev=dev, **_PRESS[command])
        return reply, time.monotonic() - started

    def driver(self, dev: str = _DEV) -> Any:
        return self.plugin._manager.get_driver(dev)  # публичной команды за драйвером у плагина нет

    def connect(self, dev: str = _DEV) -> None:
        """``device_connect`` и первый удачный тик (``conn`` с ``ts`` пишет только тик)."""
        mark = self.pub.mark()
        assert self.command("device_connect", dev=dev)["status"] == "ok"
        _wait(
            lambda: any(c.get("conn") == "connected" and "ts" in c for c in self.pub.conns(dev, mark)),
            30.0,
            f"{dev}: подключение и первый тик",
        )

    def disconnect(self, dev: str = _DEV) -> None:
        """``device_disconnect`` и конец отключения в supervisor."""
        mark = self.pub.mark()
        assert self.command("device_disconnect", dev=dev)["status"] == "ok"
        _wait(
            lambda: any(c.get("conn") == "disconnected" for c in self.pub.conns(dev, mark)),
            30.0,
            f"{dev}: конец отключения",
        )

    def connect_failures(self, since: int, dev: str = _DEV) -> int:
        return sum(1 for e in self.pub.errors(dev, since) if e.startswith(_TEXT_CONNECT_FAILED))

    def close(self) -> None:
        try:
            run(lambda: self.plugin.shutdown(self.ctx), 30.0)
        finally:
            self.workers.stop_all_workers(timeout=10.0)
            for sim in self.sims.values():
                sim.close()


@contextmanager
def _hub(tmp_path: Path) -> Iterator[_Hub]:
    hub = _Hub(tmp_path)
    try:
        yield hub
        for dev, sim in hub.sims.items():
            assert sim.errors == [], f"ядро sim {dev} упало: {sim.errors}"
    finally:
        hub.close()


@contextmanager
def _connected(tmp_path: Path, **kwargs: Any) -> Iterator[tuple[_Hub, _Sim]]:
    with _hub(tmp_path) as hub:
        sim = hub.add(**kwargs)
        hub.connect()
        yield hub, sim


# --------------------------------------------------------------------------------------------------
# Движение робота sim и сценарии неготовности
# --------------------------------------------------------------------------------------------------


def _reg(sim: _Sim, name: str) -> int:
    with sim.server.store_lock:
        return sim.core.regs[REG[name]]


def _moving(sim: _Sim) -> bool:
    return _reg(sim, "TLM_ACTIVITY") != 0


def _y_mm(sim: _Sim) -> float:
    raw = _reg(sim, "TLM_Y")
    return (raw - 0x10000 if raw >= 0x8000 else raw) / 10.0


def _start_motion(hub: _Hub, sim: _Sim) -> None:
    reply = hub.command("robot_jog_step", **_LONG_STEP)
    assert reply["status"] == "ok", reply
    _wait(lambda: _moving(sim), 3.0, "робот sim поехал")


def _assert_stopped_by_our_stop(sim: _Sim, mark: int) -> None:
    """Робот встал именно от кадра ``STOP_REQ`` после метки: эхо равно его значению, до цели не дошёл."""
    value = _stop_frames(sim.server.frames(mark))[-1].values[0]
    _wait(lambda: not _moving(sim), 1.0, "робот sim встал после STOP")
    assert _reg(sim, "TLM_STOP_ACK") == value
    assert _reg(sim, "TLM_WDG_STATE") != 2, "ход оборвал сторож sim, а не СТОП"
    assert _y_mm(sim) < _Y_SHORT_OF_TARGET


def _failed_reconnect_while_moving(hub: _Hub, sim: _Sim) -> None:
    """Устройство с ``on_connect.servo: false``: робот едет, повторный connect получает NAK «занят» на SERVO OFF."""
    assert hub.command("robot_servo", on=True)["status"] == "ok"
    _start_motion(hub, sim)
    mark = hub.pub.mark()
    assert hub.command("device_connect")["status"] == "ok"
    _wait(lambda: hub.connect_failures(mark) >= 1, 5.0, "повторный connect не удался")
    assert hub.driver().is_connected is False
    assert _moving(sim), "предпосылка: робот ещё едет"


def _drop_noticed_by_tick(hub: _Hub, sim: _Sim, kind: str) -> None:
    """Тик получает обрыв на чтении; сервер принимает новые соединения; первая проба переподключения не проходит.

    После возврата идёт порог переподключения (2 с): драйвер не готов, на сервер никто не стучится.
    """
    mark = hub.pub.mark()
    old = sim.server.accepted
    drop = sim.server.on_next(lambda f: f.fc == 3, kind)
    probe = sim.server.on_next(lambda f: f.fc == 3 and f.conn > old, "exc")
    assert drop.entered.wait(5.0), "тик не читает"
    assert probe.entered.wait(5.0), "тик не пробует переподключиться"
    _wait(lambda: hub.connect_failures(mark) >= 1, 5.0, "неудачное переподключение опубликовано")
    assert hub.driver().is_connected is False


class _Gate:
    """Шов порядка: первый вызов, прошедший ``pred``, ждёт отпускания ДО оригинала (замок устройства не взят)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, method: str, pred: Callable[..., bool]) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.waits: list[bool] = []
        original = getattr(ModbusDevice, method)
        taken = threading.Lock()

        def gated(device: ModbusDevice, *args: Any, **kwargs: Any) -> Any:
            if pred(*args) and taken.acquire(blocking=False):
                self.entered.set()
                self.waits.append(self.release.wait(10.0))
            return original(device, *args, **kwargs)

        monkeypatch.setattr(ModbusDevice, method, gated)

    def finish(self) -> None:
        self.release.set()
        _wait(lambda: self.waits, 12.0, "удержанный вызов продолжился")
        assert self.waits == [True], "порядок не навязан: ожидание вышло по сроку"


# --------------------------------------------------------------------------------------------------
# A1: повторный connect уже подключённого устройства не удался
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("command", _COMMANDS)
def test_a1_stop_after_failed_repeat_connect_is_written_and_robot_stops(tmp_path: Path, command: str) -> None:
    with _connected(tmp_path, params={"on_connect": {"servo": False}}) as (hub, sim):
        _failed_reconnect_while_moving(hub, sim)
        mark = sim.server.mark()
        reply, _ = hub.press(command)
        assert reply["status"] == "ok", reply
        assert _levels(sim.server.frames(mark)) == [_HARD]
        _assert_stopped_by_our_stop(sim, mark)


# --------------------------------------------------------------------------------------------------
# A2а: обрыв и возврат связи, тик обрыв заметил; СТОП до удачного переподключения
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["fin", "rst"])
@pytest.mark.parametrize("command", _COMMANDS)
def test_a2a_stop_before_successful_reconnect_is_written_and_robot_stops(
    tmp_path: Path, command: str, kind: str
) -> None:
    with _connected(tmp_path) as (hub, sim):
        _start_motion(hub, sim)
        _drop_noticed_by_tick(hub, sim, kind)
        assert _moving(sim), "предпосылка: робот ещё едет"
        mark = sim.server.mark()
        reply, _ = hub.press(command)
        assert _levels(sim.server.frames(mark)) == [_HARD], reply
        _assert_stopped_by_our_stop(sim, mark)


# --------------------------------------------------------------------------------------------------
# A2б: обрыв, обменов после него не было, одно нажатие
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["fin", "rst"])
@pytest.mark.parametrize("command", _COMMANDS)
def test_a2b_one_press_on_unnoticed_drop_is_ok_with_one_stop_frame(tmp_path: Path, command: str, kind: str) -> None:
    # такт 30 с: тик идёт, но после первого такта обменов не делает
    with _connected(tmp_path, params={"poll_interval_s": 30.0}) as (hub, sim):
        _start_motion(hub, sim)
        sim.server.drop_idle(kind)
        assert hub.driver().is_connected is True, "предпосылка: обрыв никто не заметил"
        mark = sim.server.mark()
        reply, elapsed = hub.press(command)
        print(f"A2b {command} {kind}: команда {elapsed:.3f} с, ответ {reply}")
        assert reply["status"] == "ok", reply
        time.sleep(0.2)
        assert _levels(sim.server.frames(mark)) == [_HARD]
        assert elapsed < 0.5
        _assert_stopped_by_our_stop(sim, mark)


# --------------------------------------------------------------------------------------------------
# A3: после законченного намеренного отключения
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("command", _COMMANDS)
def test_a3_stop_after_deliberate_disconnect_is_refused_without_frames_or_new_tcp(tmp_path: Path, command: str) -> None:
    with _connected(tmp_path) as (hub, sim):
        hub.disconnect()
        mark, accepted = sim.server.mark(), sim.server.accepted
        reply, _ = hub.press(command)
        assert reply["status"] == "error", reply
        assert reply.get("message"), reply
        assert reply.get("error"), reply
        time.sleep(0.5)
        assert sim.server.frames(mark) == []
        assert sim.server.accepted == accepted


@pytest.mark.parametrize("command", _COMMANDS)
def test_refusal_without_driver_has_message_and_error_and_neutral_text(tmp_path: Path, command: str) -> None:
    """Дизайн п.3 и п.8: «драйвер не создан» — тоже отказ с обоими ключами и не про журнал."""
    with _hub(tmp_path) as hub:
        sim = hub.add()
        assert hub.driver() is None, "предпосылка: connect не звали, драйвера нет"
        reply, _ = hub.press(command)
        assert reply["status"] == "error", reply
        assert reply.get("message"), reply
        assert reply.get("error"), reply
        assert "журнал" not in reply["message"], reply
        assert sim.server.accepted == 0


# --------------------------------------------------------------------------------------------------
# A4: прошивка этим клиентом ни разу не подтверждена, или WrongFirmware
# --------------------------------------------------------------------------------------------------


class _Firmware:
    """Хранилище сервера поверх ядра sim: ``wrong`` — ``TLM_PROTO_VER`` читается как чужая прошивка 0x0100."""

    def __init__(self, core: Any) -> None:
        self._core = core
        self.wrong = False

    def read(self, address: int, count: int) -> list[int]:
        words = list(self._core.read(address, count))
        offset = 0x1040 - address
        if self.wrong and 0 <= offset < len(words):
            words[offset] = 0x0100
        return words

    def write(self, address: int, values: list[int]) -> None:
        self._core.write(address, values)


def _assert_refused_with_zero_writes(hub: _Hub, sim: _Sim, command: str) -> None:
    mark = sim.server.mark()
    reply, _ = hub.press(command)
    assert reply["status"] == "error", reply
    assert reply.get("message"), reply
    assert reply.get("error"), reply
    time.sleep(0.3)
    assert sim.server.writes(mark) == []


@pytest.mark.parametrize("cause", ["wrong_firmware", "probe_io_error"])
@pytest.mark.parametrize("command", _COMMANDS)
def test_a4_never_confirmed_firmware_gets_no_stop(tmp_path: Path, command: str, cause: str) -> None:
    with _hub(tmp_path) as hub:
        sim = hub.add()
        if cause == "wrong_firmware":
            firmware = _Firmware(sim.core)
            firmware.wrong = True
            sim.server.store = firmware
        else:
            for _ in range(60):
                sim.server.on_next(lambda f: f.fc == 3, "exc")
        mark = hub.pub.mark()
        assert hub.command("device_connect")["status"] == "ok"
        _wait(lambda: hub.connect_failures(mark) >= 1, 20.0, "connect не удался")
        assert sim.server.writes() == [], "предпосылка: прошивка не подтверждена, записей не было"
        _assert_refused_with_zero_writes(hub, sim, command)


@pytest.mark.parametrize("command", _COMMANDS)
def test_a4_wrong_firmware_after_confirmed_one_gets_no_stop(tmp_path: Path, command: str) -> None:
    with _hub(tmp_path) as hub:
        sim = hub.add()
        firmware = _Firmware(sim.core)
        sim.server.store = firmware
        hub.connect()  # прошивка этим клиентом подтверждена
        firmware.wrong = True
        mark = hub.pub.mark()
        assert hub.command("device_connect")["status"] == "ok"
        _wait(
            lambda: any("WrongFirmware" in e for e in hub.pub.errors(_DEV, mark)),
            20.0,
            "повторная проба отвергла прошивку",
        )
        assert hub.driver().is_connected is False
        _assert_refused_with_zero_writes(hub, sim, command)


# --------------------------------------------------------------------------------------------------
# A5: мёртвая связь
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("state", ["tick_noticed", "untouched"])
@pytest.mark.parametrize("command", _COMMANDS)
def test_a5_dead_link_stop_is_error_in_time_and_stays_unconfirmed(tmp_path: Path, command: str, state: str) -> None:
    params = {"poll_interval_s": 30.0} if state == "untouched" else {}
    with _connected(tmp_path, timeout_sec=1.0, params=params) as (hub, sim):
        mark = hub.pub.mark()
        sim.server.close()  # порт закрыт: ни старого соединения, ни нового
        if state == "tick_noticed":
            # первая попытка тика уже кончилась: нажатие не встаёт за ней на замок устройства
            _wait(lambda: hub.connect_failures(mark) >= 1, 15.0, "тик заметил обрыв и не переподключился")
        mark = hub.pub.mark()
        reply, elapsed = hub.press(command)
        print(f"A5 {command} {state}: команда {elapsed:.3f} с, ответ {reply}")
        assert reply["status"] == "error", reply
        assert reply.get("message"), reply
        assert reply.get("error"), reply
        assert elapsed < 3.0
        time.sleep(0.3)
        assert hub.pub.errors(_DEV, mark).count(_TEXT_UNCONFIRMED) == 1
        assert hub.driver().stop_unconfirmed is True

        attempt = hub.pub.mark()
        assert hub.command("device_connect")["status"] == "ok"
        _wait(
            lambda: any(c.get("conn") == "error" for c in hub.pub.conns(_DEV, attempt)),
            20.0,
            "следующая попытка connect кончилась неудачей",
        )
        assert hub.connect_failures(attempt) >= 1, "предпосылка: попытка connect действительно была"
        assert hub.driver().stop_unconfirmed is True


def test_a5_each_press_on_dead_link_publishes_unconfirmed_once(tmp_path: Path) -> None:
    with _connected(tmp_path, timeout_sec=1.0, params={"poll_interval_s": 30.0}) as (hub, sim):
        sim.server.close()
        mark = hub.pub.mark()
        hub.press("robot_stop")
        time.sleep(0.3)
        assert hub.pub.errors(_DEV, mark).count(_TEXT_UNCONFIRMED) == 1
        hub.press("robot_stop")
        time.sleep(0.3)
        assert hub.pub.errors(_DEV, mark).count(_TEXT_UNCONFIRMED) == 2


def test_a5_guard_timed_out_stop_write_is_not_written_again(tmp_path: Path) -> None:
    """Сторож: ответа на запись STOP нет. pymodbus сам повторяет тот же кадр; второй записи драйвера (новый
    ``stop_seq`` — другое значение) нет."""
    with _connected(tmp_path, timeout_sec=1.0, params={"poll_interval_s": 30.0}) as (hub, sim):
        # два кадра на первую запись драйвера и два на возможную вторую
        for _ in range(4):
            sim.server.on_next(lambda f: f.fc in (6, 16) and f.addr == _STOP_REQ, "silent")
        mark = sim.server.mark()
        reply, elapsed = hub.press("robot_stop")
        time.sleep(1.5)  # запоздавшая вторая запись уже была бы на проводе
        values = [f.values[0] for f in _stop_frames(sim.server.frames(mark))]
        print(f"A5 timeout: команда {elapsed:.3f} с, кадры STOP {values}, ответ {reply}")
        assert values != []
        assert len(set(values)) == 1, values
        assert reply["status"] == "error", reply
        assert elapsed < 3.0


def test_a5_measure_second_device_command_delay(tmp_path: Path) -> None:
    """Измерение, не приёмка: сколько ждёт команда второго устройства, поданная тем же потоком после СТОП."""
    with _hub(tmp_path) as hub:
        dead = hub.add(timeout_sec=1.0, params={"poll_interval_s": 30.0})
        hub.add("rv2b")
        hub.connect()
        hub.connect("rv2b")
        dead.server.close()

        def receive_thread() -> tuple[float, float, dict, dict]:
            started = time.monotonic()
            first = hub.plugin.cmd_robot_stop({"device_id": _DEV, "level": "HARD"})
            stopped = time.monotonic()
            second = hub.plugin.cmd_robot_get_telemetry({"device_id": "rv2b"})
            return stopped - started, time.monotonic() - started, first, second

        stop_s, second_s, first, second = run(receive_thread, 30.0)
        print(f"MEASURE: СТОП мёртвого {stop_s:.3f} с; ответ второго устройства через {second_s:.3f} с; {first}")
        assert second["status"] == "ok", second


# --------------------------------------------------------------------------------------------------
# A6: робот v1 без связи
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("state", ["link_lost", "disconnected"])
def test_a6_v1_abort_without_link_is_refused_with_zero_writes(tmp_path: Path, state: str) -> None:
    with _hub(tmp_path) as hub:
        sim = hub.add("rv1", protocol="delta_universal3", params={"telemetry_interval_s": 0.0})
        hub.connect("rv1")
        if state == "link_lost":
            sim.server.close()
            _wait(lambda: hub.driver("rv1").is_connected is False, 15.0, "тик v1 заметил обрыв")
        else:
            hub.disconnect("rv1")
        mark, accepted = sim.server.mark(), sim.server.accepted
        reply = hub.command("robot_abort", dev="rv1", mode=3)
        assert reply["status"] == "error", reply
        assert reply["message"] == _TEXT_NOT_CONNECTED_RV1
        assert reply.get("error"), reply
        time.sleep(0.5)
        assert sim.server.writes(mark) == []
        assert sim.server.accepted == accepted


# --------------------------------------------------------------------------------------------------
# A7: порядок «тик первым» при задании после обрыва
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["fin", "rst"])
@pytest.mark.parametrize("how", ["request_stop", "disconnect"])
def test_a7_tick_first_stop_during_job_is_on_the_wire(monkeypatch: pytest.MonkeyPatch, how: str, kind: str) -> None:
    with _v2() as rig:
        assert rig.call("enqueue_job", _JOB)["status"] == "ok"
        ticker = _Ticker(rig.drv)
        try:
            _wait(lambda: _op_writes(rig, 0, _OP_CVT_JOB) == 1, 20.0, "CVT_JOB на проводе")
            rig.sim.frozen.set()  # задание не кончается
            held = rig.srv.on_next(lambda f: f.fc == 3, kind, hold=True)
            assert held.entered.wait(10.0), "тик не читает"
            stop_reached, link_done, waits = _force_order(monkeypatch, rig.drv, "tick_first")
            mark = rig.srv.mark()
            stopping = Call(lambda: _stop(rig, how))
            assert stop_reached.wait(10.0), "стоп не дошёл до записи STOP_REQ"
            time.sleep(0.4)
            held.release.set()
            stopping.result(30.0)
            assert link_done.wait(10.0), "тик не дошёл до _link_lost"
            time.sleep(0.5)
            assert waits == [True]  # порядок навязан, а не вышел по сроку
            assert _levels(rig.srv.frames(mark)) == [_HARD]
        finally:
            ticker.close()


# --------------------------------------------------------------------------------------------------
# A8: прочие команды в неготовности по-прежнему отклоняются
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "args"),
    [("robot_servo", {"on": True}), ("robot_jog_step", {"dx": 1.0, "dy": 0.0, "spd": 20})],
    ids=["robot_servo", "robot_jog_step"],
)
def test_a8_motion_command_when_not_ready_is_refused_with_zero_frames(tmp_path: Path, command: str, args: dict) -> None:
    with _connected(tmp_path) as (hub, sim):
        # парная проверка: на готовом устройстве эта же команда пишет в регистры команд
        mark = sim.server.mark()
        assert hub.command(command, **args)["status"] == "ok"
        assert _motion_writes(sim.server.frames(mark)) != []
        _wait(lambda: not _moving(sim), 10.0, "робот sim в простое")

        _drop_noticed_by_tick(hub, sim, "fin")
        mark = sim.server.mark()
        reply = hub.command(command, **args)
        assert reply["status"] == "error", reply
        assert reply["message"] == _TEXT_NOT_CONNECTED_RV2
        assert _motion_writes(sim.server.frames(mark)) == []


# --------------------------------------------------------------------------------------------------
# A9: СТОП в окне между закрытием и открытием транспорта в connect
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("command", _COMMANDS)
def test_a9_stop_between_transport_close_and_open_is_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command: str
) -> None:
    with _connected(tmp_path, params={"on_connect": {"servo": False}}) as (hub, sim):
        # после неудачного connect транспорт открыт, драйвер не готов: следующий connect сначала закрывает сокет
        _failed_reconnect_while_moving(hub, sim)
        gate = _Gate(monkeypatch, "connect", lambda: True)
        try:
            assert hub.command("device_connect")["status"] == "ok"
            assert gate.entered.wait(8.0), "connect не дошёл до открытия транспорта"
            assert hub.driver().transport.is_connected is False, "предпосылка: сокет уже закрыт, ещё не открыт"
            assert _moving(sim), "предпосылка: робот ещё едет"
            mark = sim.server.mark()
            reply, _ = hub.press(command)
            assert gate.release.is_set() is False and gate.waits == [], "СТОП должен пройти, пока окно открыто"
            assert reply["status"] == "ok", reply
            assert _levels(sim.server.frames(mark)) == [_HARD]
            _assert_stopped_by_our_stop(sim, mark)
            gate.finish()
        finally:
            gate.release.set()


# --------------------------------------------------------------------------------------------------
# A10: СТОП во время повторной пробы и после пробы, упавшей на вводе-выводе
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("command", _COMMANDS)
def test_a10_stop_during_repeat_probe_is_on_the_wire(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command: str
) -> None:
    with _connected(tmp_path) as (hub, sim):
        _start_motion(hub, sim)
        gate = _Gate(monkeypatch, "read_registers", lambda address, *_: address == _PROBE_PARAM_ADDR)
        try:
            assert hub.command("device_connect")["status"] == "ok"
            assert gate.entered.wait(8.0), "повторная проба не идёт"
            assert hub.driver().is_connected is False, "предпосылка: драйвер не готов, проба идёт"
            mark = sim.server.mark()
            reply, _ = hub.press(command)
            assert gate.waits == [], "СТОП должен пройти, пока проба ещё идёт"
            assert _levels(sim.server.frames(mark)) == [_HARD], reply
            _assert_stopped_by_our_stop(sim, mark)
            gate.finish()
        finally:
            gate.release.set()


@pytest.mark.parametrize("kind", ["fin", "rst"])
def test_a10_stop_after_probe_failed_on_io_is_on_the_wire(tmp_path: Path, kind: str) -> None:
    with _connected(tmp_path) as (hub, sim):
        _start_motion(hub, sim)
        # первая повторная проба — обрыв посреди неё; проба переподключения тиком — тоже неудачна
        broken = sim.server.on_next(lambda f: f.addr == _PROBE_PARAM_ADDR, kind)
        again = sim.server.on_next(lambda f: f.addr == _PROBE_PARAM_ADDR, "exc")
        mark_pub = hub.pub.mark()
        assert hub.command("device_connect")["status"] == "ok"
        assert broken.entered.wait(8.0), "повторная проба не дошла до сервера"
        assert again.entered.wait(8.0), "тик не пробует переподключиться"
        _wait(lambda: hub.connect_failures(mark_pub) >= 2, 5.0, "обе пробы кончились неудачей")
        assert hub.driver().is_connected is False
        assert _moving(sim), "предпосылка: робот ещё едет"
        mark = sim.server.mark()
        reply, _ = hub.press("robot_stop")
        assert _levels(sim.server.frames(mark)) == [_HARD], reply
        _assert_stopped_by_our_stop(sim, mark)


# --------------------------------------------------------------------------------------------------
# A11: повторный disconnect после jog с упавшим стопом
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("failure", ["dead_host", "stop_rejected"])
def test_a11_repeat_disconnect_after_failed_jog_stop_says_nothing_again(tmp_path: Path, failure: str) -> None:
    with _connected(tmp_path, timeout_sec=1.0, params={"poll_interval_s": 30.0}) as (hub, sim):
        if failure == "stop_rejected":
            for _ in range(20):
                sim.server.on_next(lambda f: f.fc in (6, 16) and f.addr == _STOP_REQ, "exc")
        mark = hub.pub.mark()
        assert hub.command("robot_jog_hold", dir=1, spd=1)["status"] == "ok"
        if failure == "dead_host":
            sim.server.close()
        time.sleep(0.6)  # окно удержания 0,2 с вышло: драйвер сам шлёт стоп, и он падает
        hub.disconnect()
        first = hub.pub.errors(_DEV, mark).count(_TEXT_UNCONFIRMED)
        assert first >= 1, ("предпосылка: стоп jog упал и это объявлено", hub.pub.errors(_DEV, mark))

        wire, accepted = sim.server.mark(), sim.server.accepted
        hub.disconnect()
        time.sleep(0.3)
        assert hub.pub.errors(_DEV, mark).count(_TEXT_UNCONFIRMED) == first
        assert _stop_frames(sim.server.frames(wire)) == []
        assert sim.server.accepted == accepted
