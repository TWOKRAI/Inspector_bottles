# -*- coding: utf-8 -*-
"""Авторские hazard-тесты Task 2.13 (C-125), вкладка ПЧ: разбор ответов, поздний ответ, поток, сквозной путь."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QThreadPool

from multiprocess_framework.modules.router_module.core.router_manager import RouterManager, _result_is_success
from multiprocess_prototype.frontend.bridge.request_runner import RequestRunner
from multiprocess_prototype.frontend.widgets.tabs.services.vfd.controller import VfdWidgetController
from multiprocess_prototype.frontend.widgets.tabs.services.vfd.presenter import VfdPresenter
from multiprocess_prototype.frontend.widgets.tabs.services.vfd.widget import VfdControlWidget
from Plugins.hub.device_hub.plugin import DeviceHubPlugin
from Services.robot_comm.server.sim_core import RobotSimCore
from Services.robot_comm.testing.fake_transport import FakeRobotTransport

_REFUSAL = "ПЧ: отказ"
_REJECTED_DEFAULT = "ПЧ: команда отклонена"
_NO_REPLY = "ПЧ: нет ответа — команда могла дойти, проверьте ленту"
_SEND_FAILED = {"success": False, "error": "send failed"}  # отказ без message, не таймаут
_DEFERRED = "ПЧ: стоп может исполниться только после рисования"


class _Sender:
    """describe — пустой успех; команды ПЧ — ``reply``."""

    def __init__(self) -> None:
        self.reply: Any = {"success": True, "result": {"status": "ok"}}

    def request_command(self, process: str, command: str, args: dict) -> Any:
        if command == "device_describe":
            return {"success": True, "result": {"status": "ok"}}
        return self.reply


class _Runner:
    """Придерживает ответы команд (``hold``) и отдаёт их по одному в заданном порядке."""

    def __init__(self) -> None:
        self.hold = False
        self.held: list[tuple[Any, Callable[[Any], None]]] = []

    def submit(self, fn: Callable[[], Any], on_result: Callable[[Any], None]) -> None:
        reply = fn()
        if self.hold:
            self.held.append((reply, on_result))
        else:
            on_result(reply)

    def deliver(self, index: int) -> None:
        reply, on_result = self.held.pop(index)
        on_result(reply)


@pytest.fixture
def tab(qtbot):
    widget = VfdControlWidget()
    qtbot.addWidget(widget)
    sender, runner = _Sender(), _Runner()
    controller = VfdWidgetController(widget, VfdPresenter(command_sender=sender, request_runner=runner))
    controller.set_device("vfd_belt")
    yield widget, controller, sender, runner
    controller.unbind()


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        pytest.param(
            {"success": False, "result": {"status": "error", "message": _REFUSAL}}, _REFUSAL, id="stop-refused"
        ),
        pytest.param({"success": False, "error": "timeout"}, _NO_REPLY, id="stop-timeout"),
        pytest.param(
            {"success": False, "error": "timeout", "reason": "no_receive_pump"}, _NO_REPLY, id="no-receive-pump"
        ),
        pytest.param({"success": False, "error": "empty response"}, _NO_REPLY, id="empty-response"),
        pytest.param(_SEND_FAILED, _REJECTED_DEFAULT, id="send-failed"),
        pytest.param(
            {"success": False, "result": {"status": "error", "error": "timeout"}},
            _REJECTED_DEFAULT,
            id="handler-answered-timeout",
        ),
        pytest.param({"success": False, "result": None}, _REJECTED_DEFAULT, id="no-result"),
        pytest.param({"success": True, "result": {"success": False}}, _REJECTED_DEFAULT, id="inner-success-false"),
        pytest.param(
            {"success": True, "result": {"status": "busy", "message": _REFUSAL}}, _REFUSAL, id="status-not-ok"
        ),
        pytest.param({}, "", id="empty-is-not-a-refusal"),
        pytest.param({"success": False, "result": {"status": "ok"}}, _REJECTED_DEFAULT, id="envelope-false"),
    ],
)
def test_stop_reply_classification(tab, reply: dict, expected: str) -> None:
    widget, _controller, sender, _runner = tab
    sender.reply = reply

    widget._btn_stop.click()

    assert widget._lbl_refusal.text() == expected


@pytest.mark.parametrize("button", ["_btn_run", "_btn_set_freq", "_btn_stop"])
def test_refusal_without_message_is_not_reported_as_missing_reply(tab, button: str) -> None:
    widget, _controller, sender, _runner = tab
    sender.reply = _SEND_FAILED

    getattr(widget, button).click()

    assert widget._lbl_refusal.text() == _REJECTED_DEFAULT


def test_without_sender_nothing_is_reported(qtbot) -> None:
    widget = VfdControlWidget()
    qtbot.addWidget(widget)
    controller = VfdWidgetController(widget, VfdPresenter())
    controller.set_device("vfd_belt")

    widget._btn_run.click()
    controller.unbind()

    assert widget._lbl_refusal.text() == ""


@pytest.mark.parametrize("button", ["_btn_run", "_btn_run_rev", "_btn_set_freq", "_btn_stop", "_btn_reset"])
def test_label_is_cleared_on_press_before_the_reply(tab, button: str) -> None:
    widget, _controller, sender, runner = tab
    sender.reply = _SEND_FAILED
    widget._btn_run.click()
    assert widget._lbl_refusal.text() == _REJECTED_DEFAULT

    runner.hold = True
    getattr(widget, button).click()

    assert widget._lbl_refusal.text() == ""


def test_late_success_of_earlier_command_keeps_deferred_stop_text(tab) -> None:
    widget, _controller, sender, runner = tab
    runner.hold = True
    widget._btn_run.click()
    sender.reply = {"success": True, "result": {"status": "ok", "deferred": True, "message": _DEFERRED}}
    widget._btn_stop.click()

    runner.deliver(1)  # ответ «Стоп» пришёл раньше ответа «Пуск»
    runner.deliver(0)

    assert widget._lbl_refusal.text() == _DEFERRED


def test_reselecting_the_same_device_keeps_the_refusal(tab) -> None:
    widget, controller, sender, _runner = tab
    sender.reply = _SEND_FAILED
    widget._btn_run.click()

    controller.set_device("vfd_belt")

    assert widget._lbl_refusal.text() == _REJECTED_DEFAULT


# --- настоящий RequestRunner ---


def test_reply_is_applied_in_the_gui_thread(qtbot) -> None:
    widget = VfdControlWidget()
    qtbot.addWidget(widget)
    sender = _Sender()
    sender.reply = _SEND_FAILED
    runner = RequestRunner()
    controller = VfdWidgetController(widget, VfdPresenter(command_sender=sender, request_runner=runner))
    threads: list[threading.Thread] = []
    real_set_refusal = widget.set_refusal

    def spy(text: str) -> None:
        threads.append(threading.current_thread())
        real_set_refusal(text)

    controller.set_device("vfd_belt")
    widget.set_refusal = spy

    widget._btn_run.click()
    qtbot.waitUntil(lambda: widget._lbl_refusal.text() == _REJECTED_DEFAULT, timeout=3000)
    controller.unbind()

    assert threads == [threading.main_thread(), threading.main_thread()]  # очистка при нажатии, затем ответ


def test_reply_after_the_page_is_destroyed_is_dropped(qtbot) -> None:
    """Страницу сняли (``unbind`` + ``deleteLater``), ответ пришёл позже: колбэк не зовётся, исключений нет."""
    release = threading.Event()
    answered = threading.Event()

    class _SlowSender(_Sender):
        def request_command(self, process: str, command: str, args: dict) -> Any:
            if command != "vfd_run":
                return {"success": True, "result": {"status": "ok"}}
            release.wait(5.0)
            answered.set()
            return {"success": False, "error": "timeout"}

    widget = VfdControlWidget()
    pool = QThreadPool()
    runner = RequestRunner(pool=pool)
    runner.setParent(widget)  # как в section._make_device_page
    controller = VfdWidgetController(widget, VfdPresenter(command_sender=_SlowSender(), request_runner=runner))
    controller.set_device("vfd_belt")
    shown: list[str] = []
    widget.set_refusal = shown.append
    widget._btn_run.click()

    with qtbot.capture_exceptions() as errors:
        controller.unbind()
        with qtbot.waitSignal(widget.destroyed, timeout=3000):
            widget.deleteLater()
        release.set()
        assert pool.waitForDone(5000)
        qtbot.wait(50)

    assert answered.is_set()
    assert shown == [""]  # только очистка при нажатии
    assert errors == []


# --- сквозной путь: кнопка -> обработчик процесса devices -> настоящий драйвер -> конверт роутера -> метка ---


class _EchoRouter(RouterManager):
    """``reply_to_request`` настоящий; ``send`` возвращает построенный конверт."""

    def __init__(self) -> None:  # noqa: super().__init__ намеренно не вызван
        self.process = None
        self.router_id = "test-router"

    def send(self, message: dict) -> dict:
        return message


class _PluginSender:
    def __init__(self, plugin: DeviceHubPlugin) -> None:
        self._plugin = plugin
        self.results: list[dict] = []

    def request_command(self, process: str, command: str, args: dict) -> Any:
        result = getattr(self._plugin, f"cmd_{command}")(dict(args))
        self.results.append(result)
        request = {"request_id": "r1", "reply_to": "gui"}
        return _EchoRouter().reply_to_request(request, result, success=_result_is_success(result))


def test_real_hub_command_delivers_refusal_and_deferred_text_to_the_tab(qtbot, tmp_path: Path) -> None:
    ctx = MagicMock()
    ctx.config = {"registry_path": str(tmp_path / "devices.yaml")}
    ctx.registers = None
    ctx.process_name = "devices"
    plugin = DeviceHubPlugin()
    plugin.configure(ctx)
    try:
        manager = plugin._manager
        manager.set_driver_options("robot", transport=FakeRobotTransport(RobotSimCore()))
        manager.upsert(
            {"id": "robot_main", "name": "Робот", "kind": "robot", "transport": {"type": "tcp"}, "params": {}}
        )
        manager.upsert(
            {
                "id": "vfd_belt",
                "name": "ПЧ лента",
                "kind": "vfd",
                "protocol": "gd20_bridge",
                "transport": {"type": "bridge", "bridge": "robot_main"},
                "params": {"freq_min_hz": 5, "freq_max_hz": 40},
            }
        )
        assert manager.connect("robot_main") is True
        assert manager.connect("vfd_belt") is True

        widget = VfdControlWidget()
        qtbot.addWidget(widget)
        sender = _PluginSender(plugin)
        controller = VfdWidgetController(widget, VfdPresenter(command_sender=sender, request_runner=_Runner()))
        controller.set_device("vfd_belt")
        assert (widget._spin_freq.minimum(), widget._spin_freq.maximum()) == (5.0, 40.0)  # describe настоящий

        widget._btn_run.click()
        assert sender.results[-1]["status"] == "ok"
        assert widget._lbl_refusal.text() == ""

        assert manager.call("robot_main", "set_mode", {"mode": "draw"})["status"] == "ok"

        widget._btn_run.click()
        assert widget._lbl_refusal.text() == "ПЧ: робот в режиме DRAW (идёт рисование), команда не отправлена"

        widget._btn_stop.click()
        assert widget._lbl_refusal.text() == "ПЧ: стоп записан, но может исполниться только после рисования"
        controller.unbind()
    finally:
        plugin.shutdown(ctx)
