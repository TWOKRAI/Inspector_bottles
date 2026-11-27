# -*- coding: utf-8 -*-
"""Приёмочные тесты (слепые): ответ команды в конверте роутера (A1–A6).

Проверяется то, что получает вызывающий через публичные методы VfdPresenter и
DevicesPresenter, и то, что видно на вкладке ПЧ (настоящие виджет, контроллер и
presenter; подменён только транспорт). Ожидаемые значения — литералы.
"""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtWidgets import QDoubleSpinBox, QPushButton

from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.presenter import (
    DevicesPresenter,
)
from multiprocess_prototype.frontend.widgets.tabs.services.vfd.controller import (
    VfdWidgetController,
)
from multiprocess_prototype.frontend.widgets.tabs.services.vfd.presenter import (
    VfdPresenter,
)
from multiprocess_prototype.frontend.widgets.tabs.services.vfd.widget import (
    VfdControlWidget,
)

PRESENTERS = [
    pytest.param(VfdPresenter, id="vfd"),
    pytest.param(DevicesPresenter, id="common"),
]


class _Sender:
    """CommandSender-дублёр: на любой запрос отдаёт заданный ответ."""

    def __init__(self, response: Any) -> None:
        self._response = response

    def request_command(self, process: str, command: str, args: dict) -> Any:
        return self._response


class _ImmediateRunner:
    """RequestRunner-дублёр: исполняет синхронно, ответ отдаёт как есть."""

    def submit(self, fn, on_result) -> None:
        on_result(fn())


def _envelope(result: Any, *, success: bool = True) -> dict:
    """Настоящий конверт роутера."""
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


def _describe_result() -> dict:
    return {
        "status": "ok",
        "entry": {"id": "vfd_belt", "name": "Лента"},
        "protocol_meta": {"cmd_freq": {"min": 0.0, "max": 40.0}},
        "carrier": {"mode": "draw"},
    }


def _describe_via(presenter_cls: type, response: Any) -> list:
    presenter = presenter_cls(command_sender=_Sender(response), request_runner=_ImmediateRunner())
    received: list = []
    presenter.device_describe("vfd_belt", received.append)
    return received


# --- A1: настоящий конверт ---


@pytest.mark.parametrize("presenter_cls", PRESENTERS)
def test_a1_router_envelope_delivers_result_fields(presenter_cls: type) -> None:
    received = _describe_via(presenter_cls, _envelope(_describe_result()))

    assert len(received) == 1
    got = received[0]
    assert got.get("entry") == {"id": "vfd_belt", "name": "Лента"}
    assert got.get("protocol_meta") == {"cmd_freq": {"min": 0.0, "max": 40.0}}
    assert got.get("carrier") == {"mode": "draw"}


@pytest.mark.parametrize("presenter_cls", PRESENTERS)
def test_a1_router_envelope_keys_do_not_reach_receiver(presenter_cls: type) -> None:
    received = _describe_via(presenter_cls, _envelope(_describe_result()))

    leaked = {"type", "command", "sender", "targets", "queue_type", "request_id", "result"} & set(received[0])
    assert leaked == set()


# --- A2: вкладка ПЧ ---


def _open_vfd_tab(qtbot, response: Any) -> tuple[VfdControlWidget, VfdWidgetController]:
    widget = VfdControlWidget()
    qtbot.addWidget(widget)
    presenter = VfdPresenter(command_sender=_Sender(response), request_runner=_ImmediateRunner())
    controller = VfdWidgetController(widget, presenter)
    controller.set_device("vfd_belt")
    return widget, controller


def _button(widget: VfdControlWidget, text: str) -> QPushButton:
    found = [b for b in widget.findChildren(QPushButton) if b.text() == text]
    assert len(found) == 1, f"кнопка {text!r}: найдено {len(found)}"
    return found[0]


@pytest.mark.parametrize("button_text", ["Пуск", "Пуск (реверс)"])
def test_a2_envelope_draw_mode_disables_run_button(qtbot, button_text: str) -> None:
    widget, controller = _open_vfd_tab(qtbot, _envelope(_describe_result()))
    try:
        assert _button(widget, button_text).isEnabled() is False
    finally:
        controller.unbind()


def test_a2_envelope_applies_frequency_limit(qtbot) -> None:
    widget, controller = _open_vfd_tab(qtbot, _envelope(_describe_result()))
    try:
        assert widget.findChild(QDoubleSpinBox).maximum() == 40.0
    finally:
        controller.unbind()


def test_a2_envelope_value_above_limit_is_clamped(qtbot) -> None:
    """Оператор не может задать частоту выше предела из ответа."""
    widget, controller = _open_vfd_tab(qtbot, _envelope(_describe_result()))
    try:
        spin = widget.findChild(QDoubleSpinBox)
        spin.setValue(45.0)
        assert spin.value() == 40.0
    finally:
        controller.unbind()


def test_a2_control_flat_describe_gates_and_limits_tab(qtbot) -> None:
    """Контроль стенда: тот же describe без конверта вкладка применяет."""
    widget, controller = _open_vfd_tab(qtbot, _describe_result())
    try:
        assert _button(widget, "Пуск").isEnabled() is False
        assert widget.findChild(QDoubleSpinBox).maximum() == 40.0
    finally:
        controller.unbind()


# --- A3: ответ без конверта ---


@pytest.mark.parametrize("presenter_cls", PRESENTERS)
@pytest.mark.parametrize(
    "response",
    [
        pytest.param(
            {"status": "ok", "entry": {"id": "vfd_belt"}, "protocol_meta": {"cmd_freq": {"max": 40.0}}},
            id="flat-ok",
        ),
        pytest.param({"success": False, "error": "timeout"}, id="flat-error"),
    ],
)
def test_a3_response_without_envelope_is_unchanged(presenter_cls: type, response: dict) -> None:
    expected = dict(response)

    assert _describe_via(presenter_cls, response) == [expected]


# --- A4: {"result": ...} и {"result": ..., "status": "ok"} ---


@pytest.mark.parametrize("presenter_cls", PRESENTERS)
@pytest.mark.parametrize(
    "response",
    [
        pytest.param({"result": {"entry": {"id": "vfd_belt"}}}, id="result-only"),
        pytest.param({"result": {"entry": {"id": "vfd_belt"}}, "status": "ok"}, id="result-and-status"),
    ],
)
def test_a4_result_wrapper_is_unwrapped(presenter_cls: type, response: dict) -> None:
    assert _describe_via(presenter_cls, response) == [{"entry": {"id": "vfd_belt"}}]


# --- A5: конверт отказа ---


@pytest.mark.parametrize("presenter_cls", PRESENTERS)
def test_a5_refusal_envelope_keeps_success_false(presenter_cls: type) -> None:
    received = _describe_via(presenter_cls, _envelope(None, success=False))

    assert len(received) == 1
    assert received[0].get("success") is False


# --- A6: ответ не dict ---


@pytest.mark.parametrize("presenter_cls", PRESENTERS)
@pytest.mark.parametrize("response", [pytest.param(None, id="none"), pytest.param("boom", id="str")])
def test_a6_non_dict_response_becomes_empty_dict(presenter_cls: type, response: Any) -> None:
    assert _describe_via(presenter_cls, response) == [{}]
