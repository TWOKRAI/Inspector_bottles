"""Авторские hazard-тесты Task 2.13 (C-125), драйверная часть: сбой чтения носителя, постоянный текст, флаг drawing."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from Services.device_hub.drivers.robot_driver import RobotDriver
from Services.device_hub.drivers.vfd_driver import VfdDriver
from Services.device_hub.registry.entry import DeviceEntry
from Services.device_hub.tests.conftest import FakeClock
from Services.robot_comm.server.sim_core import RobotSimCore
from Services.robot_comm.testing.fake_transport import FakeRobotTransport

_REFUSAL = "ПЧ: робот в режиме DRAW (идёт рисование), команда не отправлена"
_DEFERRED = "ПЧ: стоп записан, но может исполниться только после рисования"
_STOP = [("w", 0x1200, 0), ("w", 0x1204, 1)]


class _Transport:
    is_connected = True

    def __init__(self) -> None:
        self.writes: list[list[tuple]] = []

    def transaction(self, ops: list[tuple]) -> bool:
        self.writes.append(list(ops))
        return True

    def read_registers(self, address: int, count: int = 1) -> list[int]:
        return [0] * count


class _Carrier:
    kind = "robot"
    busy = False

    def __init__(self, mode: str = "cvt", drawing: bool = False) -> None:
        self.mode = mode
        self.drawing = drawing


class _BrokenCarrier:
    """Носитель, у которого чтение состояния бросает."""

    kind = "robot"
    busy = False

    @property
    def mode(self) -> str:
        raise RuntimeError("носитель разобран")


def _make_vfd(carrier: Any) -> tuple[VfdDriver, _Transport]:
    entry = DeviceEntry(
        id="vfd_belt",
        name="ПЧ лента",
        kind="vfd",
        protocol="gd20_bridge",
        transport={"type": "bridge", "bridge": "robot_main"},
        params={"freq_max_hz": 50.0},
    )
    fake = _Transport()
    driver = VfdDriver(entry, resolve_device=lambda _dev_id: carrier, transport=fake)
    assert driver.connect() is True
    return driver, fake


@pytest.mark.parametrize(
    ("op", "args"),
    [
        ("run", {"freq_hz": 12.5}),
        ("run", {"freq_hz": 47.0}),
        ("run", {}),
        ("set_freq", {"freq_hz": 33.0}),
        ("set_freq", {}),  # под замком отказ замка, а не «freq_hz обязателен»
    ],
)
def test_refusal_text_is_constant(op: str, args: dict) -> None:
    driver, fake = _make_vfd(_Carrier("draw"))

    result = driver.call(op, args)

    assert result == {"status": "error", "message": _REFUSAL, "error": _REFUSAL}
    assert fake.writes == []


@pytest.mark.parametrize("op", ["run", "set_freq"])
def test_unreadable_carrier_does_not_let_run_through(op: str) -> None:
    driver, fake = _make_vfd(_BrokenCarrier())

    result = driver.call(op, {"freq_hz": 10.0})

    assert result["status"] == "error"
    assert fake.writes == []


def test_unreadable_carrier_does_not_block_stop() -> None:
    driver, fake = _make_vfd(_BrokenCarrier())

    result = driver.call("stop", {})

    assert fake.writes == [_STOP]
    assert result == {"status": "ok", "deferred": True, "message": _DEFERRED}
    assert driver.stats["tx_ok"] == 1
    assert driver.stats["tx_err"] == 0


# --- RobotDriver.drawing: обрывы посреди фигуры ---


def _make_robot() -> RobotDriver:
    clock = FakeClock()
    entry = DeviceEntry(
        id="robot_main", name="Робот", kind="robot", transport={"type": "tcp"}, params={"word_order": "little"}
    )
    driver = RobotDriver(entry, transport=FakeRobotTransport(RobotSimCore()), clock=clock.clock, sleep=clock.sleep)
    assert driver.connect() is True
    return driver


def _tick_one_figure(driver: RobotDriver, monkeypatch: pytest.MonkeyPatch, fake_draw: Any) -> list[Exception]:
    monkeypatch.setattr(driver.transport, "draw", fake_draw)
    queued = driver.call(
        "draw_polyline",
        {"points": [{"x_mm": 0.0, "y_mm": 0.0, "pen": 0}, {"x_mm": 10.0, "y_mm": 0.0, "pen": 1}]},
    )
    assert queued["status"] == "ok"
    errors: list[Exception] = []

    def run_tick() -> None:
        try:
            driver.tick()
        except Exception as exc:
            errors.append(exc)

    tick = threading.Thread(target=run_tick, daemon=True)
    tick.start()
    tick.join(timeout=10.0)
    assert not tick.is_alive(), "tick с заданием рисования завис"
    return errors


def test_drawing_is_false_after_disconnect_in_the_middle_of_a_figure(monkeypatch: pytest.MonkeyPatch) -> None:
    driver = _make_robot()
    inside: list[bool] = []

    def fake_draw(_points: Any, **_kwargs: Any) -> bool:
        driver.disconnect()
        inside.append(driver.drawing)
        raise RuntimeError("связь закрыта посреди фигуры")

    # tick после обрыва падает на возврате режима в cvt (поведение до этой задачи) — здесь важен только флаг
    _tick_one_figure(driver, monkeypatch, fake_draw)

    assert inside == [True]  # disconnect сам по себе флаг не снимает: фигура ещё идёт
    assert driver.drawing is False


def test_draw_abort_drops_flag_but_draw_mode_keeps_vfd_locked(monkeypatch: pytest.MonkeyPatch) -> None:
    driver = _make_robot()
    vfd, fake = _make_vfd(driver)
    seen: list[tuple] = []

    def fake_draw(_points: Any, **_kwargs: Any) -> bool:
        assert driver.call("draw_abort", {})["status"] == "ok"
        seen.append((driver.drawing, driver.mode, vfd.call("run", {"freq_hz": 10.0})["status"]))
        return False

    _tick_one_figure(driver, monkeypatch, fake_draw)

    assert seen == [(False, "draw", "error")]
    assert fake.writes == []
    assert driver.drawing is False
