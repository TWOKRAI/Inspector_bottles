# -*- coding: utf-8 -*-
"""Приёмочные тесты (слепые) Task 2.13, вкладка ПЧ: R8, R9, R10 и вкладочная часть R13.

Настоящие виджет, контроллер и presenter; подменены только транспорт (sender с конвертом роутера) и runner.
Ожидаемые значения — литералы. Метка отказа — ``widget._lbl_refusal`` (имя задано приёмкой).
"""

from __future__ import annotations

from typing import Any, Callable

import pytest
from PySide6.QtWidgets import QDoubleSpinBox, QPushButton

from multiprocess_prototype.frontend.widgets.tabs.services.vfd.controller import (
    VfdWidgetController,
)
from multiprocess_prototype.frontend.widgets.tabs.services.vfd.presenter import (
    VfdPresenter,
)
from multiprocess_prototype.frontend.widgets.tabs.services.vfd.widget import (
    VfdControlWidget,
)

_REFUSAL = "ПЧ: робот в режиме DRAW, команда не отправлена"
_DEFERRED = "ПЧ: стоп может исполниться только после рисования"
_REJECTED_DEFAULT = "ПЧ: команда отклонена"

_COMMAND_BUTTONS = [
    pytest.param("Пуск", "vfd_run", id="run"),
    pytest.param("Сменить частоту", "vfd_set_freq", id="set_freq"),
]


def _envelope(result: Any, *, success: bool = True) -> dict:
    """Конверт роутера (``RouterManager.reply_to_request``)."""
    return {
        "type": "response",
        "command": "command.response",
        "sender": "devices",
        "targets": ["gui"],
        "queue_type": "system",
        "request_id": "r1",
        "success": success,
        "result": result,
    }


def _ok() -> dict:
    return _envelope({"status": "ok"})


def _refused() -> dict:
    return _envelope({"status": "error", "message": _REFUSAL, "error": _REFUSAL}, success=False)


class _Sender:
    """CommandSender-дублёр: describe — заданный результат, команды ПЧ — ``reply``."""

    def __init__(self, describe: dict) -> None:
        self.describe = describe
        self.reply: Any = _ok()
        self.commands: list[str] = []

    def request_command(self, process: str, command: str, args: dict) -> Any:
        self.commands.append(command)
        if command == "device_describe":
            return _envelope(self.describe)
        return self.reply


class _Runner:
    """RequestRunner-дублёр: синхронный; при ``hold`` придерживает ответ до ``release``."""

    def __init__(self) -> None:
        self.hold = False
        self._held: list[tuple[Any, Callable[[Any], None]]] = []

    def submit(self, fn: Callable[[], Any], on_result: Callable[[Any], None]) -> None:
        reply = fn()
        if self.hold:
            self._held.append((reply, on_result))
        else:
            on_result(reply)

    def release(self) -> None:
        held, self._held = self._held, []
        for reply, on_result in held:
            on_result(reply)


class _Tab:
    def __init__(self, widget: VfdControlWidget, controller: VfdWidgetController, sender: _Sender, runner: _Runner):
        self.widget = widget
        self.controller = controller
        self.sender = sender
        self.runner = runner

    def button(self, text: str) -> QPushButton:
        found = [b for b in self.widget.findChildren(QPushButton) if b.text() == text]
        assert len(found) == 1, f"кнопка {text!r}: найдено {len(found)}"
        return found[0]

    def press(self, text: str, reply: dict) -> None:
        self.sender.reply = reply
        self.button(text).click()

    def refusal(self) -> str:
        return self.widget._lbl_refusal.text()


@pytest.fixture
def open_tab(qtbot):
    opened: list[VfdWidgetController] = []

    def factory(describe: dict | None = None) -> _Tab:
        widget = VfdControlWidget()
        qtbot.addWidget(widget)
        sender = _Sender(describe or {"status": "ok", "entry": {"id": "vfd_belt", "params": {}}})
        runner = _Runner()
        presenter = VfdPresenter(command_sender=sender, request_runner=runner)
        controller = VfdWidgetController(widget, presenter)
        opened.append(controller)
        controller.set_device("vfd_belt")
        return _Tab(widget, controller, sender, runner)

    yield factory
    for controller in opened:
        controller.unbind()


# --- R8: отказ виден и держится ---


@pytest.mark.parametrize(("button", "command"), _COMMAND_BUTTONS)
def test_r8_refusal_is_shown_and_survives_status_push(open_tab, button: str, command: str) -> None:
    tab = open_tab()

    tab.press(button, _refused())

    assert tab.sender.commands[-1] == command
    assert tab.refusal() == "ПЧ: робот в режиме DRAW, команда не отправлена"
    assert tab.widget._lbl_refusal.isVisibleTo(tab.widget)

    tab.controller._on_status_push("devices.state.vfd_belt.status", {"quality": "stale", "reason": "carrier busy"})

    assert "carrier busy" in tab.widget._lbl_quality.text()  # push действительно обработан
    assert tab.refusal() == "ПЧ: робот в режиме DRAW, команда не отправлена"


@pytest.mark.parametrize(("button", "command"), _COMMAND_BUTTONS)
def test_r8_success_leaves_refusal_empty(open_tab, button: str, command: str) -> None:
    tab = open_tab()

    tab.press(button, _ok())

    assert tab.sender.commands[-1] == command
    assert tab.refusal() == ""


@pytest.mark.parametrize(("button", "command"), _COMMAND_BUTTONS)
def test_r8_timeout_shows_default_text(open_tab, button: str, command: str) -> None:
    tab = open_tab()

    tab.press(button, {"success": False, "error": "timeout"})

    assert tab.sender.commands[-1] == command
    assert tab.refusal() == _REJECTED_DEFAULT


@pytest.mark.parametrize(("button", "command"), _COMMAND_BUTTONS)
def test_r8_successful_next_command_clears_refusal(open_tab, button: str, command: str) -> None:
    tab = open_tab()
    tab.press(button, _refused())
    assert tab.refusal() == _REFUSAL

    tab.press(button, _ok())

    assert tab.refusal() == ""


@pytest.mark.parametrize(("button", "command"), _COMMAND_BUTTONS)
def test_r8_selecting_other_device_clears_refusal(open_tab, button: str, command: str) -> None:
    tab = open_tab()
    tab.press(button, _refused())
    assert tab.refusal() == _REFUSAL

    tab.controller.set_device("vfd_other")

    assert tab.refusal() == ""


@pytest.mark.parametrize(("button", "command"), _COMMAND_BUTTONS)
def test_r8_late_refusal_of_previous_device_is_ignored(open_tab, button: str, command: str) -> None:
    tab = open_tab()
    # Парная проверка: придержанный ответ без смены устройства до метки доходит.
    tab.runner.hold = True
    tab.press(button, _refused())
    tab.runner.release()
    assert tab.refusal() == _REFUSAL

    tab.runner.hold = False
    tab.press(button, _ok())
    tab.runner.hold = True
    tab.press(button, _refused())
    tab.runner.hold = False
    tab.controller.set_device("vfd_other")

    tab.runner.release()

    assert tab.refusal() == ""


@pytest.mark.parametrize(("button", "command"), _COMMAND_BUTTONS)
def test_r8_late_success_of_previous_device_keeps_new_refusal(open_tab, button: str, command: str) -> None:
    tab = open_tab()
    tab.runner.hold = True
    tab.press(button, _ok())
    tab.runner.hold = False
    tab.controller.set_device("vfd_other")
    tab.press(button, _refused())
    assert tab.refusal() == _REFUSAL

    tab.runner.release()

    assert tab.refusal() == _REFUSAL


# --- R9: диапазон частоты ---


@pytest.mark.parametrize(
    ("params", "cmd_freq", "expected"),
    [
        pytest.param({"freq_min_hz": 5, "freq_max_hz": 40}, None, (5.0, 40.0), id="params-both"),
        pytest.param({"freq_max_hz": 40}, None, (0.0, 40.0), id="params-max-only"),
        pytest.param({}, None, (0.0, 50.0), id="defaults"),
        pytest.param({"freq_min_hz": 5, "freq_max_hz": 40}, {"min": 2, "max": 30}, (2.0, 30.0), id="meta-wins"),
        pytest.param({"freq_min_hz": 5, "freq_max_hz": 40}, {"max": 30}, (5.0, 30.0), id="meta-max-only"),
    ],
)
def test_r9_frequency_range(open_tab, params: dict, cmd_freq: dict | None, expected: tuple) -> None:
    describe: dict = {"status": "ok", "entry": {"id": "vfd_belt", "params": params}}
    if cmd_freq is not None:
        describe["protocol_meta"] = {"cmd_freq": cmd_freq}

    tab = open_tab(describe)

    spin = tab.widget.findChild(QDoubleSpinBox)
    assert (spin.minimum(), spin.maximum()) == expected


# --- R10: «Стоп» доступен всегда ---


def _enabled(tab: _Tab) -> dict[str, bool]:
    return {
        text: tab.button(text).isEnabled()
        for text in ("Пуск", "Пуск (реверс)", "Сменить частоту", "Сброс аварии", "Стоп")
    }


_ONLY_STOP = {
    "Пуск": False,
    "Пуск (реверс)": False,
    "Сменить частоту": False,
    "Сброс аварии": False,
    "Стоп": True,
}


def test_r10_disabling_controls_keeps_stop_enabled(open_tab) -> None:
    tab = open_tab()
    assert all(_enabled(tab).values())  # исходно всё включено

    tab.widget.set_controls_enabled(False)

    assert _enabled(tab) == _ONLY_STOP


def test_r10_no_device_keeps_stop_enabled(open_tab) -> None:
    tab = open_tab()

    tab.controller.set_device(None)

    assert _enabled(tab) == _ONLY_STOP


# --- R13: отложенный «Стоп» на вкладке ---


def test_r13_deferred_stop_message_is_shown(open_tab) -> None:
    tab = open_tab()

    tab.press("Стоп", _envelope({"status": "ok", "deferred": True, "message": _DEFERRED}))

    assert tab.sender.commands[-1] == "vfd_stop"
    assert tab.refusal() == "ПЧ: стоп может исполниться только после рисования"


def test_r13_plain_stop_shows_nothing(open_tab) -> None:
    tab = open_tab()

    tab.press("Стоп", _ok())

    assert tab.sender.commands[-1] == "vfd_stop"
    assert tab.refusal() == ""
