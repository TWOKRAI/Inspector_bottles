# -*- coding: utf-8 -*-
"""Пульт запуска в настоящем MainWindow (Task 2.3, REDS 17-19).

Настоящие ``MainWindow`` + ``GuiStateBindings`` над ``GuiStateProxy`` со spy-роутером
(образец ``test_tab_open_invariant.py``); дельты идут тем же путём, что в проде:
bridge -> bindings (fan-out ``system.run.*``) и bridge -> read-model (replay).

Запуск:
    QT_QPA_PLATFORM=offscreen pytest frontend/tests/test_main_window_run_control.py -q
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QLabel, QPushButton

from multiprocess_framework.modules.frontend_module.state import TelemetryViewModel
from multiprocess_framework.modules.state_store_module.proxy.gui_state_proxy import GuiStateProxy
from multiprocess_prototype.frontend.state.bindings import GuiStateBindings
from multiprocess_prototype.frontend.widgets.chrome import run_control
from multiprocess_prototype.frontend.widgets.chrome.run_control import RunControlWidget
from multiprocess_prototype.frontend.windows.main_window import MainWindow


class _SyncBridge:
    """Синхронный дубль DataReceiverBridge для state-пути."""

    def __init__(self) -> None:
        self._state_cb = None
        self._state_listeners: list = []

    def set_state_callback(self, cb) -> None:
        self._state_cb = cb

    def add_state_listener(self, cb) -> None:
        self._state_listeners.append(cb)

    def dispatch(self, msg_dict: dict) -> None:
        if self._state_cb is not None:
            self._state_cb(msg_dict)
        for cb in list(self._state_listeners):
            cb(msg_dict)


class _SpyRouter:
    """Router-шпион: считает блокирующие request и async state.subscribe."""

    def __init__(self) -> None:
        self.blocking_requests: list[dict] = []
        self.async_subscribes: list[dict] = []
        self._seq = 0

    def register_message_handler(self, *a, **k) -> None:
        pass

    def send_async(self, msg, priority: str = "normal") -> None:
        if isinstance(msg, dict) and msg.get("command") == "state.subscribe":
            self.async_subscribes.append(msg)

    def request(self, msg, timeout: float = 5.0) -> dict:
        self.blocking_requests.append(msg)
        self._seq += 1
        return {"success": True, "result": {"status": "ok", "sub_id": f"srv-{self._seq}"}}


class _Stack:
    """Bridge + роутер + настоящие GuiStateProxy / read-model / GuiStateBindings."""

    def __init__(self) -> None:
        self.router = _SpyRouter()
        self.bridge = _SyncBridge()
        proxy = GuiStateProxy("gui", router=self.router, delta_sink=lambda _deltas: None)
        proxy.subscribe("system.**", lambda _d: None, exclude_self=True)  # стартовый wildcard GUI
        self.read_model = TelemetryViewModel(initial_cache=dict(proxy.cache))
        self.bridge.add_state_listener(self.read_model.on_state_delta)
        self.bindings = GuiStateBindings(
            self.bridge,
            read_model=self.read_model,
            ensure_subscription=proxy.ensure_subscription,
            release_subscription=proxy.release_subscription,
        )

    def leaf(self, name: str, value: Any) -> None:
        self.bridge.dispatch({"data_type": "state_delta", "path": f"system.run.{name}", "value": value})

    def delete(self, name: str) -> None:
        self.bridge.dispatch({"data_type": "state_delta", "path": f"system.run.{name}", "value": None, "deleted": True})


class _FakeCommands:
    """Четыре метода run_*_async; on_result затравки сохраняется и не зовётся."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.start_callbacks: list = []
        self.status_callbacks: list = []

    def run_start_async(self, on_result) -> None:
        self.calls.append("start")
        self.start_callbacks.append(on_result)

    def run_stop_async(self, on_result) -> None:
        self.calls.append("stop")

    def run_ack_async(self, on_result) -> None:
        self.calls.append("ack")

    def run_status_async(self, on_result) -> None:
        self.status_callbacks.append(on_result)


def _lbl(parent, name: str) -> QLabel:
    found = parent.findChild(QLabel, name)
    assert found is not None, f"нет метки {name}"
    return found


def _btn(parent, name: str) -> QPushButton:
    found = parent.findChild(QPushButton, name)
    assert found is not None, f"нет кнопки {name}"
    return found


def _window(qtbot) -> MainWindow:
    window = MainWindow()
    qtbot.addWidget(window)
    return window


# ---------------------------------------------------------------------------
# REDS 17: дельты через настоящие bindings
# ---------------------------------------------------------------------------


def test_deltas_drive_run_control_through_real_bindings(qtbot) -> None:
    """ready+start_allowed -> ЗАПУСТИТЬ включена; running -> «Работает»; удаление -> «Нет данных»."""
    window = _window(qtbot)
    stack = _Stack()
    window.connect_bindings(stack.bindings)
    state = _lbl(window, "RunStateLabel")
    start = _btn(window, "RunStartButton")
    assert state.text() == "Нет данных"
    assert not start.isEnabled()

    stack.leaf("state", "ready")
    stack.leaf("start_allowed", True)
    assert state.text() == "Готов"
    assert start.isEnabled()

    stack.leaf("start_allowed", False)
    stack.leaf("state", "running")
    assert state.text() == "Работает"
    assert _btn(window, "RunStopButton").isEnabled()
    assert not start.isEnabled()

    stack.delete("state")
    assert state.text() == "Нет данных"
    assert not _btn(window, "RunStopButton").isEnabled()

    # подписка system.run.* покрыта стартовым system.** — блокирующего IPC нет
    assert stack.router.blocking_requests == [] or all(
        m.get("data", {}).get("pattern") != "system.run.*" for m in stack.router.blocking_requests
    )
    assert [m for m in stack.router.async_subscribes if m.get("data", {}).get("pattern") == "system.run.*"] == []


def test_values_before_connect_bindings_are_replayed(qtbot) -> None:
    """Листья, пришедшие ДО connect_bindings, видны после (replay read-model)."""
    window = _window(qtbot)
    stack = _Stack()
    stack.leaf("state", "fault")
    stack.leaf("ack_allowed", True)
    stack.leaf(
        "last_fault", {"at": 100.0, "reasons": [{"severity": "failure", "reason": "обрыв"}], "acknowledged_at": None}
    )
    assert _lbl(window, "RunStateLabel").text() == "Нет данных"  # ещё не подключены

    window.connect_bindings(stack.bindings)

    assert _lbl(window, "RunStateLabel").text() == "Авария"
    assert _btn(window, "RunAckButton").isEnabled()
    assert "обрыв" in _lbl(window, "RunFaultLabel").text()


# ---------------------------------------------------------------------------
# REDS 18: размещение
# ---------------------------------------------------------------------------


def test_layout_order_and_bindings_without_fanout(qtbot) -> None:
    """header 0, banner 1, RunControlWidget 2, placeholder 3, tabs 4; bindings без bind_fanout не бросают."""
    window = _window(qtbot)
    layout = window._layout

    assert layout.count() == 5
    assert layout.itemAt(0).widget() is window._header
    assert layout.itemAt(1).widget() is window._error_banner
    assert isinstance(layout.itemAt(2).widget(), RunControlWidget)
    assert layout.itemAt(3).widget() is window._image_panel_placeholder
    assert layout.itemAt(4).widget() is window._tab_widget

    class _BindOnly:
        def bind(self, *args, **kwargs) -> None:
            pass

    window.connect_bindings(_BindOnly())  # не бросает
    window.connect_bindings(None)  # не бросает


# ---------------------------------------------------------------------------
# REDS 19: затравка и жизнь после уничтожения
# ---------------------------------------------------------------------------


def test_seed_fills_empty_snapshot(qtbot) -> None:
    """set_commands -> один run_status_async; ответ success с fault+last_fault рисуется."""
    window = _window(qtbot)
    fake = _FakeCommands()

    window.set_run_commands(fake)

    assert len(fake.status_callbacks) == 1
    fake.status_callbacks[0](
        {
            "success": True,
            "result": {
                "state": "fault",
                "ack_allowed": True,
                "start_allowed": False,
                "reasons": [],
                "last_fault": {
                    "at": 100.0,
                    "reasons": [{"severity": "failure", "reason": "обрыв"}],
                    "acknowledged_at": None,
                },
            },
        }
    )
    assert _lbl(window, "RunStateLabel").text() == "Авария"
    assert "обрыв" in _lbl(window, "RunFaultLabel").text()


def test_seed_does_not_overwrite_fresher_leaf(qtbot) -> None:
    """Лист state=running пришёл до ответа затравки с state=ready -> остаётся «Работает»."""
    window = _window(qtbot)
    stack = _Stack()
    window.connect_bindings(stack.bindings)
    fake = _FakeCommands()
    window.set_run_commands(fake)

    stack.leaf("state", "running")
    fake.status_callbacks[0]({"success": True, "result": {"state": "ready", "start_allowed": True}})

    assert _lbl(window, "RunStateLabel").text() == "Работает"
    # в running ЗАПУСТИТЬ неактивна даже при start_allowed=True (окно между дельтами)
    assert not _btn(window, "RunStartButton").isEnabled()
    assert _btn(window, "RunStopButton").isEnabled()
    # ключ, которого лист ещё не принёс (start_allowed), затравка всё же добрала
    stack.leaf("state", "ready")
    assert _btn(window, "RunStartButton").isEnabled()


def test_seed_failure_is_silent(qtbot) -> None:
    """Ошибка/таймаут затравки не меняют вид и не бросают."""
    window = _window(qtbot)
    fake = _FakeCommands()
    window.set_run_commands(fake)

    fake.status_callbacks[0]({"success": False, "error": "timeout"})

    assert _lbl(window, "RunStateLabel").text() == "Нет данных"


def test_callbacks_after_widget_destroyed_do_not_raise(qtbot, monkeypatch) -> None:
    """on_result клика, on_result затравки и страховка после deleteLater() не бросают."""
    monkeypatch.setattr(run_control, "BUSY_SAFETY_MS", 30)
    w = RunControlWidget()  # без qtbot.addWidget: удаляем сами
    fake = _FakeCommands()
    w.set_commands(fake)
    w.apply_leaf("system.run.state", "ready")
    w.apply_leaf("system.run.start_allowed", True)
    _btn(w, "RunStartButton").click()
    assert fake.calls == ["start"]

    w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    fake.start_callbacks[0]({"success": True, "result": {"success": True, "state": "running"}})
    fake.start_callbacks[0]({"success": False, "error": "timeout"})
    fake.status_callbacks[0]({"success": True, "result": {"state": "ready"}})
    w._on_safety_timeout()  # страховка, сработавшая уже после уничтожения
    qtbot.wait(100)  # настоящий таймер (30 мс) тоже не должен ничего сломать


# ---------------------------------------------------------------------------
# Правки ревью (итерация 1)
# ---------------------------------------------------------------------------


def test_stale_click_answer_does_not_touch_newer_click(qtbot, monkeypatch) -> None:
    """Ответ-отказ клика 1 после страховки и клика 2: busy и текст клика 2 не тронуты."""
    monkeypatch.setattr(run_control, "BUSY_SAFETY_MS", 50)
    w = RunControlWidget()
    qtbot.addWidget(w)
    fake = _FakeCommands()
    w.set_commands(fake)
    w.apply_leaf("system.run.state", "ready")
    w.apply_leaf("system.run.start_allowed", True)
    start = _btn(w, "RunStartButton")

    start.click()  # клик 1
    qtbot.waitUntil(start.isEnabled, timeout=2000)  # страховка сняла busy
    start.click()  # клик 2
    assert fake.calls == ["start", "start"]
    assert not start.isEnabled()

    fake.start_callbacks[0]({"success": False, "error": "timeout"})  # запоздалый ответ клика 1

    assert not start.isEnabled()  # busy клика 2 держится
    assert "нет ответа от системы" not in _lbl(w, "RunDetailLabel").text()


def test_reason_text_is_plain_text_not_html(qtbot) -> None:
    """Причины PM — данные: метки в PlainText, «<b>x</b>» показывается литералом."""
    w = RunControlWidget()
    qtbot.addWidget(w)
    reason = {"severity": "failure", "reason": "<b>x</b>", "node": "n", "source": "s"}
    w.apply_leaf("system.run.state", "not_ready")
    w.apply_leaf("system.run.start_allowed", False)
    w.apply_leaf("system.run.reasons", [reason])
    w.apply_leaf("system.run.last_fault", {"at": 100.0, "reasons": [reason], "acknowledged_at": None})

    for name in ("RunStateLabel", "RunDetailLabel", "RunIndicatorsLabel", "RunFaultLabel"):
        assert _lbl(w, name).textFormat() == Qt.TextFormat.PlainText, name
    assert "<b>x</b>" in _lbl(w, "RunDetailLabel").text()
    assert "<b>x</b>" in _lbl(w, "RunFaultLabel").text()


def test_set_commands_survives_failing_seed_request(qtbot) -> None:
    """run_status_async бросает -> set_commands не бросает, виджет живёт по листам."""

    class _Broken(_FakeCommands):
        def run_status_async(self, on_result) -> None:
            raise RuntimeError("нет транспорта")

    w = RunControlWidget()
    qtbot.addWidget(w)

    w.set_commands(_Broken())  # не бросает

    w.apply_leaf("system.run.state", "running")
    assert _lbl(w, "RunStateLabel").text() == "Работает"
