# -*- coding: utf-8 -*-
"""Слепая приёмка T5.3e.6t: пуши статуса листьями и срок итога «Остановить» (вкладка робота v2).

Критерии A1..A13 — в T5.3e.6.acceptance.md. Пуши идут только через настоящий
``TreeStore.merge("devices.state.<id>.status", снимок)``; каждая дельта попадает в настоящие
``TelemetryReadModel`` и ``GuiStateBindings``. Презентер — мок; ответ ``robot_park`` подаётся в колбэк,
отданный презентеру. Ожидаемые значения — литералы из критериев.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
from multiprocess_framework.modules.telemetry_readmodel_module.telemetry_read_model import TelemetryReadModel
from multiprocess_prototype.frontend.state.bindings import GuiStateBindings
from multiprocess_prototype.frontend.widgets.tabs.services.robot.controller import (
    RobotWidgetController,
)
from multiprocess_prototype.frontend.widgets.tabs.services.robot.widget import (
    RobotControlWidget,
)

_STATUS = "devices.state.robot_main.status"
_PARK = "devices.state.robot_main.park"

_TXT_ACCEPTED = "Основная остановка принята: домой, затем серво OFF…"
_TXT_DONE = "Робот дома, серво выключено."
_TXT_LINK = "Связь с роботом активна."
_TXT_NO_HUB = "Нет связи с hub"  # в критерии — «Нет связи с hub…»; сравниваем по началу фразы
_TXT_NO_RESULT_MARK = "итог не получен"


def _deadline_text(seconds: int) -> str:
    return f"Основная остановка: итог не получен за {seconds} с. Проверьте робота."


# ---------------------------------------------------------------------------
# Снимки и цепочка
# ---------------------------------------------------------------------------


def _snapshot(
    x: float = 300.0,
    y: float = 200.0,
    *,
    free: bool = True,
    ts: float | None = None,
    encoder: int = 5,
    queue_len: int = 0,
) -> dict:
    """Снимок статуса в форме хаба (plugin._publish_state)."""
    return {
        "quality": "good",
        "ts": time.time() if ts is None else ts,
        "stats": {"jobs_done": 3},
        "queue_len": queue_len,
        "telemetry": {"x_mm": x, "y_mm": y, "z_mm": 50.0, "rz_deg": 0.0, "servo": True},
        "free": free,
        "encoder": encoder,
    }


def _park_value(seq: int, state: str, step: str, *, home=None, servo=None, dropped=None, reason=None, elapsed=None):
    """Значение ``devices.state.<id>.park`` в форме хаба."""
    return {
        "seq": seq,
        "state": state,
        "step": step,
        "home": home,
        "servo": servo,
        "dropped": dropped,
        "reason": reason,
        "elapsed_s": elapsed,
    }


def _make_presenter() -> MagicMock:
    return MagicMock()


class _Chain:
    """Настоящие TreeStore / TelemetryReadModel / GuiStateBindings; презентер и мост — моки."""

    def __init__(self, qtbot) -> None:
        self.store = TreeStore()
        self.read_model = TelemetryReadModel()
        self.ensured: list[str] = []
        self.released: list[str] = []
        bridge = MagicMock()
        self.bindings = GuiStateBindings(
            bridge,
            read_model=self.read_model,
            ensure_subscription=self.ensured.append,
            release_subscription=self.released.append,
        )
        self._deliver = bridge.set_state_callback.call_args.args[0]
        self.widget = RobotControlWidget()
        qtbot.addWidget(self.widget)
        self.presenter = _make_presenter()
        self.controller: RobotWidgetController | None = None

    def start(self, device_id: str = "robot_main") -> RobotWidgetController:
        self.controller = RobotWidgetController(self.widget, self.presenter, bindings=self.bindings)
        self.controller.set_device(device_id)
        return self.controller

    def merge(self, path: str, value: dict) -> None:
        """Как хаб: store.merge -> дельты по листьям -> read-model и GuiStateBindings."""
        for delta in self.store.merge(path, value):
            self.read_model.ingest(delta.path, delta.new_value)
            self._deliver({"data_type": "state_delta", "path": delta.path, "value": delta.new_value})

    def push_status(self, snapshot: dict, device_id: str = "robot_main") -> None:
        self.merge(f"devices.state.{device_id}.status", snapshot)

    def status_text(self) -> str:
        return self.widget._lbl_status.text()

    def telemetry_text(self) -> str:
        return self.widget._lbl_telemetry.text()

    def click_park(self):
        """Клик «Остановить»: вернуть on_result, отданный презентеру."""
        self.widget._btn_park.click()
        return self.presenter.park.call_args.args[1]


@pytest.fixture
def chain(qtbot) -> _Chain:
    c = _Chain(qtbot)
    c.start("robot_main")
    return c


def _accept(chain: _Chain, timeout_s: float = 30) -> float:
    """«Остановить» -> ответ допуска seq=1; вернуть момент ответа (time.monotonic)."""
    reply = chain.click_park()
    reply({"status": "ok", "accepted": True, "seq": 1, "timeout_s": timeout_s})
    return time.monotonic()


def _sleep_until(qtbot, t0: float, at_s: float) -> None:
    """Дожить (в цикле событий Qt) до at_s секунд после t0."""
    left_ms = int((at_s - (time.monotonic() - t0)) * 1000)
    if left_ms > 0:
        qtbot.wait(left_ms)


def _wait_by(qtbot, t0: float, limit_s: float, predicate) -> None:
    """Дождаться predicate не позже limit_s секунд после t0 (явный timeout)."""
    left_ms = int((limit_s - (time.monotonic() - t0)) * 1000)
    qtbot.waitUntil(predicate, timeout=max(left_ms, 1))


# ---------------------------------------------------------------------------
# A1..A4: пуши статуса листьями
# ---------------------------------------------------------------------------


def test_a1_second_status_push_updates_x(chain: _Chain) -> None:
    chain.push_status(_snapshot(x=300.0))
    chain.push_status(_snapshot(x=310.0))
    assert "X=310.0" in chain.telemetry_text()


def test_a2_free_only_delta_enables_mode_and_keeps_telemetry(chain: _Chain) -> None:
    base = time.time()
    chain.push_status(_snapshot(x=300.0, free=False, ts=base))
    assert not chain.widget._combo_mode.isEnabled()  # free=False -> переключатель заблокирован
    chain.push_status(_snapshot(x=300.0, free=True, ts=base + 1.0))  # меняются только free и ts
    assert chain.widget._combo_mode.isEnabled()
    assert "X=300.0" in chain.telemetry_text()


def test_a3_status_of_old_device_does_not_change_telemetry_after_switch(chain: _Chain) -> None:
    chain.push_status(_snapshot(x=300.0))
    chain.controller.set_device("robot_2")
    before = chain.telemetry_text()
    chain.push_status(_snapshot(x=777.0))  # статус robot_main
    assert chain.telemetry_text() == before
    assert "777.0" not in chain.telemetry_text()


def test_a4_every_ensured_robot_main_pattern_is_released_on_switch(chain: _Chain) -> None:
    ensured = {p for p in chain.ensured if "robot_main" in p}
    assert ensured, "set_device('robot_main') не оформил ни одной подписки на robot_main"
    chain.controller.set_device("robot_2")
    released = set(chain.released)
    assert ensured <= released, f"не отпущены: {sorted(ensured - released)}"


# ---------------------------------------------------------------------------
# A5: возврат связи после «Нет связи с hub…»
# ---------------------------------------------------------------------------


@pytest.fixture
def shiftable_clock(monkeypatch):
    """time.time модуля контроллера идёт как реальное + сдвиг (список из одного числа)."""
    real = time.time
    offset = [0.0]
    monkeypatch.setattr(time, "time", lambda: real() + offset[0])
    return offset


@pytest.mark.parametrize("with_park_result", [True, False], ids=["a_park_result_restored", "b_link_text"])
@pytest.mark.timeout(30)
def test_a5_fresh_push_after_no_hub_restores_status(qtbot, shiftable_clock, chain: _Chain, with_park_result) -> None:
    chain.push_status(_snapshot())
    if with_park_result:
        _accept(chain)
        chain.merge(
            _PARK, _park_value(1, "done", "servo", home="moved", servo=False, dropped={"jobs": 0, "returns": 0})
        )
        assert chain.status_text() == _TXT_DONE
    shiftable_clock[0] += 10.0  # пуши прекратились дольше 3 с
    qtbot.waitUntil(lambda: _TXT_NO_HUB in chain.status_text(), timeout=8000)
    chain.push_status(_snapshot(x=310.0))  # ts = сдвинутое «сейчас»
    expected = _TXT_DONE if with_park_result else _TXT_LINK
    assert chain.status_text() == expected


# ---------------------------------------------------------------------------
# A6: свой текст кнопки не затирается статусом
# ---------------------------------------------------------------------------


def test_a6_status_push_keeps_send_job_text(chain: _Chain) -> None:
    chain.push_status(_snapshot(x=300.0))
    chain.widget._btn_send_job.click()  # «Послать тест-job»
    after_click = chain.status_text()
    assert after_click not in ("", _TXT_LINK)
    chain.push_status(_snapshot(x=310.0))
    assert chain.status_text() == after_click


# ---------------------------------------------------------------------------
# A7..A11, A13: срок итога «Остановить»
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("timeout_s", "not_yet_s", "latest_s", "shown_s", "exact_before"),
    [
        pytest.param(1, 3.5, 4.6, 4, True, id="timeout_1"),
        pytest.param(1.5, 4.0, 5.1, 5, False, id="timeout_1_5"),
    ],
)
@pytest.mark.timeout(30)
def test_a7_deadline_text_when_no_park_leaves(
    qtbot, chain: _Chain, timeout_s, not_yet_s, latest_s, shown_s, exact_before
):
    t0 = _accept(chain, timeout_s)
    _sleep_until(qtbot, t0, not_yet_s)
    if exact_before:
        assert chain.status_text() == _TXT_ACCEPTED
    else:
        assert _TXT_NO_RESULT_MARK not in chain.status_text()
    _wait_by(qtbot, t0, latest_s, lambda: chain.status_text() == _deadline_text(shown_s))


@pytest.mark.timeout(30)
def test_a8_park_leaves_before_deadline_keep_done_text(qtbot, chain: _Chain) -> None:
    t0 = _accept(chain, 1)
    qtbot.wait(1000)
    chain.merge(_PARK, _park_value(1, "done", "servo", home="moved", servo=False, dropped={"jobs": 0, "returns": 0}))
    _sleep_until(qtbot, t0, 4.6)
    assert chain.status_text() == _TXT_DONE


@pytest.mark.timeout(30)
def test_a9_failed_leaves_after_deadline_show_reason(qtbot, chain: _Chain) -> None:
    t0 = _accept(chain, 1)
    _wait_by(qtbot, t0, 4.6, lambda: chain.status_text() == _deadline_text(4))
    chain.merge(
        _PARK,
        _park_value(1, "failed", "home", dropped={"jobs": 0, "returns": 0}, reason="срок вышел", elapsed=5.1),
    )
    assert chain.status_text() == "Основная остановка не выполнена: срок вышел."


@pytest.mark.timeout(30)
def test_a10_set_device_cancels_deadline(qtbot, chain: _Chain) -> None:
    t0 = _accept(chain, 1)
    qtbot.wait(1000)
    chain.controller.set_device("robot_2")
    _sleep_until(qtbot, t0, 4.6)
    assert _TXT_NO_RESULT_MARK not in chain.status_text()


@pytest.mark.timeout(30)
def test_a11_second_press_refusal_keeps_first_deadline(qtbot, chain: _Chain) -> None:
    t0 = _accept(chain, 1)
    qtbot.wait(1000)
    second_reply = chain.click_park()
    second_reply({"status": "error", "message": "основная остановка уже идёт"})
    _wait_by(qtbot, t0, 4.6, lambda: chain.status_text() == _deadline_text(4))


# ---------------------------------------------------------------------------
# A12: тёплый кэш
# ---------------------------------------------------------------------------


def test_a12_warm_cache_status_and_telemetry_at_set_device(qtbot) -> None:
    c = _Chain(qtbot)
    base = time.time()
    c.push_status(_snapshot(x=300.0, free=True, ts=base))
    c.push_status(_snapshot(x=310.0, free=True, ts=base + 0.1))
    c.start("robot_main")  # контроллер создан после прохождения дельт
    qtbot.waitUntil(
        lambda: c.status_text() == _TXT_LINK and "X=310.0" in c.telemetry_text(),
        timeout=2000,
    )
    c.push_status(_snapshot(x=310.0, y=222.0, free=True, ts=base + 0.2))  # изменился только y_mm
    assert "X=310.0" in c.telemetry_text()
    assert c.widget._combo_mode.isEnabled()


# ---------------------------------------------------------------------------
# A13: unbind контроллера
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_a13_unbind_cancels_deadline_without_slot_exceptions(qtbot, chain: _Chain) -> None:
    with qtbot.capture_exceptions() as exceptions:
        t0 = _accept(chain, 1)
        qtbot.wait(1000)
        chain.controller.unbind()
        _sleep_until(qtbot, t0, 4.6)
        assert _TXT_NO_RESULT_MARK not in chain.status_text()
    assert exceptions == []
