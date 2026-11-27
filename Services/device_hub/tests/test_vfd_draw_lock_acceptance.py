"""Приёмочные тесты (слепые) Task 2.13: во время рисования ПЧ не принимает пуск и смену частоты (C-125).

Драйверная часть: R1–R7, R11, R12 и драйверные половины R3, R13. Написаны до реализации по строкам REDS приёмки.
Ожидаемые значения — литералы. «Запись в ПЧ» — вызов ``transaction`` транспорта; адреса mailbox моста:
0x1200 RUN, 0x1201 DIR, 0x1202 FREQ (x100), 0x1203 RESET, 0x1204 FLAG.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from Services.device_hub.drivers.robot_driver import RobotDriver
from Services.device_hub.drivers.vfd_driver import VfdDriver
from Services.device_hub.manager import DeviceManager
from Services.device_hub.registry.entry import DeviceEntry
from Services.device_hub.tests.conftest import FakeClock
from Services.robot_comm.server.sim_core import RobotSimCore
from Services.robot_comm.testing.fake_transport import FakeRobotTransport

_BRIDGE = {"type": "bridge", "bridge": "robot_main"}

_RUN_10HZ = [("w", 0x1202, 1000), ("w", 0x1201, 0), ("w", 0x1200, 1), ("w", 0x1204, 1)]
_SET_FREQ_10HZ = [("w", 0x1202, 1000), ("w", 0x1204, 1)]
_STOP = [("w", 0x1200, 0), ("w", 0x1204, 1)]
_RESET = [("w", 0x1200, 0), ("w", 0x1203, 1), ("w", 0x1204, 1)]
_PULSE = [("w", 0x1204, 1)]


class _Transport:
    """Дублёр RegisterTransport ПЧ: запоминает каждую запись, читает нули."""

    is_connected = True

    def __init__(self) -> None:
        self.writes: list[list[tuple]] = []

    def transaction(self, ops: list[tuple]) -> bool:
        self.writes.append(list(ops))
        return True

    def read_registers(self, address: int, count: int = 1) -> list[int]:
        return [0] * count


class _Carrier:
    """Дублёр робота-носителя с режимом и флагом рисования (как RobotDriver)."""

    kind = "robot"

    def __init__(self, mode: str = "cvt", *, busy: bool = False, drawing: bool = False) -> None:
        self.mode = mode
        self.busy = busy
        self.drawing = drawing


class _CarrierWithoutModes:
    """Дублёр носителя без ``mode`` и ``drawing`` (как RobotDriverV2)."""

    kind = "robot"
    busy = False


def _make(carrier: Any, transport_cfg: dict | None = None) -> tuple[VfdDriver, _Transport]:
    entry = DeviceEntry(
        id="vfd_belt",
        name="ПЧ лента",
        kind="vfd",
        protocol="gd20_bridge",
        transport=dict(transport_cfg or _BRIDGE),
        params={"freq_max_hz": 50.0, "default_freq_hz": 10.0},
    )
    fake = _Transport()
    driver = VfdDriver(
        entry,
        resolve_device=lambda dev_id: carrier if dev_id == "robot_main" else None,
        transport=fake,
    )
    assert driver.connect() is True
    return driver, fake


def _assert_refused(driver: VfdDriver, fake: _Transport, op: str) -> None:
    result = driver.call(op, {"freq_hz": 10.0})

    assert result["status"] == "error"
    assert "DRAW" in result["message"]
    assert result["error"] == result["message"]
    assert fake.writes == []
    assert driver.stats["tx_ok"] == 0
    assert driver.stats["tx_err"] == 0


def _assert_write_is_observable(op: str) -> None:
    """Парная проверка: тот же дублёр без замка запись и счётчик видит."""
    driver, fake = _make(_Carrier("cvt"))
    assert driver.call(op, {"freq_hz": 10.0})["status"] == "ok"
    assert len(fake.writes) == 1
    assert driver.stats["tx_ok"] == 1


# --- R1, R2: режим DRAW ---


def test_r1_draw_mode_refuses_run_without_writing() -> None:
    _assert_write_is_observable("run")
    driver, fake = _make(_Carrier("draw"))

    _assert_refused(driver, fake, "run")


def test_r2_draw_mode_refuses_set_freq_without_writing() -> None:
    _assert_write_is_observable("set_freq")
    driver, fake = _make(_Carrier("draw"))

    _assert_refused(driver, fake, "set_freq")


# --- R3: под замком остальное работает ---


@pytest.mark.parametrize(
    ("op", "expected_write"),
    [
        pytest.param("reset_fault", _RESET, id="reset_fault"),
        pytest.param("get_status", _PULSE, id="get_status"),
        pytest.param("stop", _STOP, id="stop"),
    ],
)
def test_r3_under_lock_op_is_executed(op: str, expected_write: list) -> None:
    driver, fake = _make(_Carrier("draw"))

    result = driver.call(op, {})

    assert result["status"] == "ok"
    assert fake.writes == [expected_write]


# --- R4: busy и прочие режимы не блокируют ---


@pytest.mark.parametrize(
    ("mode", "busy"),
    [
        pytest.param("cvt", True, id="cvt-busy"),
        pytest.param("manual", False, id="manual"),
        pytest.param("return", False, id="return"),
    ],
)
@pytest.mark.parametrize(
    ("op", "expected_write"),
    [
        pytest.param("run", _RUN_10HZ, id="run"),
        pytest.param("set_freq", _SET_FREQ_10HZ, id="set_freq"),
    ],
)
def test_r4_non_draw_carrier_passes_command(mode: str, busy: bool, op: str, expected_write: list) -> None:
    driver, fake = _make(_Carrier(mode, busy=busy))

    result = driver.call(op, {"freq_hz": 10.0})

    assert result["status"] == "ok"
    assert fake.writes == [expected_write]


@pytest.mark.parametrize(
    ("op", "expected_write"),
    [
        pytest.param("run", _RUN_10HZ, id="run"),
        pytest.param("set_freq", _SET_FREQ_10HZ, id="set_freq"),
        pytest.param("stop", _STOP, id="stop"),
    ],
)
def test_r4_carrier_without_mode_and_drawing_is_not_locked(op: str, expected_write: list) -> None:
    driver, fake = _make(_CarrierWithoutModes())

    result = driver.call(op, {"freq_hz": 10.0})

    assert result["status"] == "ok"
    assert "deferred" not in result
    assert fake.writes == [expected_write]


# --- R5: не мост либо носителя нет ---


def test_r5_tcp_transport_ignores_draw_carrier() -> None:
    driver, fake = _make(_Carrier("draw", drawing=True), {"type": "tcp", "bridge": "robot_main"})

    result = driver.call("run", {"freq_hz": 10.0})

    assert result["status"] == "ok"
    assert fake.writes == [_RUN_10HZ]


def test_r5_bridge_with_missing_carrier_passes_run() -> None:
    driver, fake = _make(None)

    result = driver.call("run", {"freq_hz": 10.0})

    assert result["status"] == "ok"
    assert fake.writes == [_RUN_10HZ]


# --- R6: замок снимается без переподключения, память частоты не портится ---


def test_r6_lock_follows_mode_per_command_and_keeps_accepted_frequency() -> None:
    carrier = _Carrier("draw")
    driver, fake = _make(carrier)  # подключение при уже включённом DRAW

    assert driver.call("run", {"freq_hz": 35.0})["status"] == "error"

    carrier.mode = "cvt"
    assert driver.call("run", {"freq_hz": 20.0})["status"] == "ok"

    carrier.mode = "draw"
    assert driver.call("run", {"freq_hz": 35.0})["status"] == "error"
    assert driver.call("set_freq", {"freq_hz": 40.0})["status"] == "error"

    carrier.mode = "cvt"
    fake.writes.clear()
    assert driver.call("run", {})["status"] == "ok"

    assert fake.writes == [[("w", 0x1202, 2000), ("w", 0x1201, 0), ("w", 0x1200, 1), ("w", 0x1204, 1)]]


# --- R7: настоящие менеджер, RobotDriver и мостовой ПЧ ---


def _written_addresses(transactions: list[list[tuple]]) -> set[int]:
    addresses: set[int] = set()
    for ops in transactions:
        for kind, address, value in ops:
            width = len(value) if kind == "wm" else 1
            addresses.update(range(address, address + width))
    return addresses


def test_r7_real_manager_refuses_run_after_set_mode_draw() -> None:
    robot_transport = FakeRobotTransport(RobotSimCore())
    manager = DeviceManager(store=None)
    manager.initialize()
    try:
        manager.set_driver_options("robot", transport=robot_transport)
        manager.upsert(
            {
                "id": "robot_main",
                "name": "Робот",
                "kind": "robot",
                "transport": {"type": "tcp"},
                "params": {"word_order": "little"},
            }
        )
        manager.upsert(
            {
                "id": "vfd_belt",
                "name": "ПЧ лента",
                "kind": "vfd",
                "protocol": "gd20_bridge",
                "transport": dict(_BRIDGE),
                "params": {"freq_max_hz": 50.0},
            }
        )
        assert manager.connect("robot_main") is True
        assert manager.connect("vfd_belt") is True  # ПЧ подключён ДО смены режима

        # Парная проверка: запись ПЧ через мост видна в транспорте робота.
        assert manager.call("vfd_belt", "run", {"freq_hz": 12.0})["status"] == "ok"
        assert {0x1200, 0x1201, 0x1202, 0x1204} <= _written_addresses(robot_transport.transactions)

        assert manager.call("robot_main", "set_mode", {"mode": "draw"})["status"] == "ok"
        mark = len(robot_transport.transactions)

        result = manager.call("vfd_belt", "run", {"freq_hz": 10.0})

        assert result["status"] == "error"
        assert "DRAW" in result["message"]
        after = _written_addresses(robot_transport.transactions[mark:])
        assert after & {0x1200, 0x1201, 0x1202, 0x1203, 0x1204} == set()
    finally:
        manager.shutdown()


# --- R11: RobotDriver.drawing ---


def _draw_once(monkeypatch: pytest.MonkeyPatch, outcome: BaseException | None) -> tuple[RobotDriver, list, list]:
    """Одно задание рисования; клиентский ``draw`` читает ``drawing`` изнутри.

    Returns:
        (драйвер, значения ``drawing`` до задания, значения ``drawing`` изнутри ``draw``).
    """
    clock = FakeClock()
    entry = DeviceEntry(
        id="robot_main",
        name="Робот",
        kind="robot",
        transport={"type": "tcp"},
        params={"word_order": "little"},
    )
    driver = RobotDriver(
        entry,
        transport=FakeRobotTransport(RobotSimCore()),
        clock=clock.clock,
        sleep=clock.sleep,
    )
    assert driver.connect() is True
    before = [driver.drawing]
    inside: list = []

    def fake_draw(points: Any, **_kwargs: Any) -> bool:
        inside.append(driver.drawing)
        if outcome is not None:
            raise outcome
        return True

    monkeypatch.setattr(driver.transport, "draw", fake_draw)
    queued = driver.call(
        "draw_polyline",
        {"points": [{"x_mm": 0.0, "y_mm": 0.0, "pen": 0}, {"x_mm": 10.0, "y_mm": 0.0, "pen": 1}]},
    )
    assert queued["status"] == "ok"

    tick = threading.Thread(target=driver.tick, daemon=True)
    tick.start()
    tick.join(timeout=10.0)
    assert not tick.is_alive(), "tick с заданием рисования завис"
    return driver, before, inside


def test_r11_drawing_is_true_only_while_figure_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    driver, before, inside = _draw_once(monkeypatch, None)

    assert before == [False]
    assert inside == [True]
    assert driver.draws_done == 1
    assert driver.drawing is False


def test_r11_drawing_is_false_after_draw_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    driver, before, inside = _draw_once(monkeypatch, RuntimeError("обрыв посреди фигуры"))

    assert before == [False]
    assert inside == [True]
    assert driver.draws_done == 0
    assert driver.drawing is False


# --- R12: режим уведён из draw, рисование идёт ---


def test_r12_drawing_flag_refuses_run_in_manual_mode() -> None:
    _assert_write_is_observable("run")
    driver, fake = _make(_Carrier("manual", drawing=True))

    _assert_refused(driver, fake, "run")


# --- R13: ответ «Стоп» ---


@pytest.mark.parametrize(
    ("mode", "drawing"),
    [
        pytest.param("draw", False, id="draw-mode"),
        pytest.param("manual", True, id="drawing-flag"),
    ],
)
def test_r13_stop_under_lock_is_written_and_marked_deferred(mode: str, drawing: bool) -> None:
    driver, fake = _make(_Carrier(mode, drawing=drawing))

    result = driver.call("stop", {})

    assert fake.writes == [_STOP]
    assert result["status"] == "ok"
    assert result.get("deferred") is True
    assert "после рисования" in result.get("message", "")


@pytest.mark.parametrize(
    ("mode", "busy"),
    [
        pytest.param("cvt", False, id="cvt"),
        pytest.param("cvt", True, id="cvt-busy"),
        pytest.param("manual", False, id="manual"),
    ],
)
def test_r13_stop_without_lock_has_no_deferred(mode: str, busy: bool) -> None:
    driver, fake = _make(_Carrier(mode, busy=busy))

    result = driver.call("stop", {})

    assert fake.writes == [_STOP]
    assert result["status"] == "ok"
    assert "deferred" not in result
