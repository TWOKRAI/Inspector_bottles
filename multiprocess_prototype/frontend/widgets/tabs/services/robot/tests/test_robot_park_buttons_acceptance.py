# -*- coding: utf-8 -*-
"""Приёмочные тесты T5.3e.4 (слепые): кнопки «Остановить» и «Остановить принудительно».

«Остановить» = команда хаба ``robot_park`` (домой, затем серво OFF), итог приходит из
state-дерева ``devices.state.robot_main.park.*``. «Остановить принудительно» = ``robot_stop``
с level HARD. Тесты написаны по критериям приёмки, без чтения реализации.

Нумерация «К<N>» — пункты критериев приёмки из брифа T5.3e.4.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from multiprocess_prototype.frontend.widgets.tabs.services.robot.controller import (
    RobotWidgetController,
)
from multiprocess_prototype.frontend.widgets.tabs.services.robot.presenter import (
    RobotPresenter,
)
from multiprocess_prototype.frontend.widgets.tabs.services.robot.widget import (
    RobotControlWidget,
)

# --- ожидаемые тексты (литералы из критериев) ---

TXT_ACCEPTED = "Основная остановка принята: домой, затем серво OFF…"
TXT_DONE_MOVED = "Робот дома, серво выключено."
TXT_DONE_ALREADY = "Робот уже дома, серво выключено."
TXT_LINK_OK = "Связь с роботом активна."
TXT_FORCE_OK = "Робот остановлен (HARD)."
TXT_SHUTTING_DOWN = "идёт отключение робота"

PARK_NODE = "devices.state.robot_main.park"
PARK_SEQ = "devices.state.robot_main.park.seq"
PARK_HOME = "devices.state.robot_main.park.home"
PARK_STATE = "devices.state.robot_main.park.state"
PARK_REASON = "devices.state.robot_main.park.reason"
STATUS_PATH = "devices.state.robot_main.status"

TELEMETRY_VALUE = {
    "telemetry": {"x_mm": 1.0, "servo": True},
    "free": True,
    "encoder": 5,
    "queue_len": 0,
}


# --- хелперы ---


class ImmediateRunner:
    """RequestRunner-стаб: исполняет синхронно."""

    def submit(self, fn, on_result=None) -> None:
        result = fn()
        if on_result:
            on_result(result)


def make_real_presenter() -> tuple[RobotPresenter, MagicMock]:
    sender = MagicMock()
    return RobotPresenter(command_sender=sender, request_runner=ImmediateRunner()), sender


def make_ctl(qtbot):
    """Виджет + контроллер с MagicMock-presenter и MagicMock-bindings, устройство robot_main."""
    widget = RobotControlWidget()
    qtbot.addWidget(widget)
    presenter = MagicMock()
    bindings = MagicMock()
    controller = RobotWidgetController(widget, presenter, bindings=bindings)
    controller.set_device("robot_main")
    return widget, controller, presenter, bindings


def find_button(widget, text: str) -> QPushButton:
    found = [b for b in widget.findChildren(QPushButton) if b.text().strip() == text]
    assert len(found) == 1, f"кнопка с текстом {text!r}: найдено {len(found)}"
    return found[0]


def on_result_of(mock_method):
    """Достать on_result из последнего вызова presenter.<method>(device_id, on_result)."""
    call = mock_method.call_args
    assert call is not None, "presenter-метод не вызван"
    if len(call.args) >= 2:
        return call.args[1]
    return call.kwargs["on_result"]


def status(widget) -> str:
    QApplication.processEvents()
    return widget._lbl_status.text()


def wait_status(qtbot, widget, text: str) -> None:
    qtbot.waitUntil(lambda: widget._lbl_status.text() == text, timeout=1000)


def press_park(widget, presenter):
    """Нажать «Остановить» (сигнал виджета) и вернуть on_result, отданный presenter'у."""
    widget.park_requested.emit()
    return on_result_of(presenter.park)


ACCEPTED_REPLY = {"status": "ok", "accepted": True, "seq": 1}


# =====================================================================
# К1. presenter: адресация
# =====================================================================


def test_presenter_park_routed_to_devices() -> None:
    presenter, sender = make_real_presenter()
    sender.request_command.return_value = {"status": "ok", "accepted": True, "seq": 1}
    results: list[dict] = []
    presenter.park("robot_main", results.append)
    sender.request_command.assert_called_once_with("devices", "robot_park", {"device_id": "robot_main"})
    assert results == [{"status": "ok", "accepted": True, "seq": 1}]


def test_presenter_park_unwraps_response() -> None:
    """on_result получает развёрнутый dict (обёртка {"result": {...}} снимается)."""
    presenter, sender = make_real_presenter()
    sender.request_command.return_value = {"result": {"status": "ok", "accepted": True, "seq": 1}}
    results: list[dict] = []
    presenter.park("robot_main", results.append)
    assert results == [{"status": "ok", "accepted": True, "seq": 1}]


def test_presenter_force_stop_routed_to_devices_hard() -> None:
    presenter, sender = make_real_presenter()
    sender.request_command.return_value = {"status": "ok"}
    results: list[dict] = []
    presenter.force_stop("robot_main", results.append)
    sender.request_command.assert_called_once_with(
        "devices", "robot_stop", {"device_id": "robot_main", "level": "HARD"}
    )
    assert results == [{"status": "ok"}]


# =====================================================================
# К2. отказ park
# =====================================================================


def test_park_error_reply_shows_message(qtbot) -> None:
    widget, _controller, presenter, _b = make_ctl(qtbot)
    cb = press_park(widget, presenter)
    cb({"status": "error", "message": TXT_SHUTTING_DOWN})
    wait_status(qtbot, widget, TXT_SHUTTING_DOWN)
    assert status(widget) == TXT_SHUTTING_DOWN


# =====================================================================
# К3. принято + листья .park -> итог
# =====================================================================


def test_park_accepted_reply_shows_accepted_text(qtbot) -> None:
    widget, _controller, presenter, _b = make_ctl(qtbot)
    cb = press_park(widget, presenter)
    cb(ACCEPTED_REPLY)
    wait_status(qtbot, widget, TXT_ACCEPTED)
    assert status(widget) == TXT_ACCEPTED


def test_park_leaves_done_moved_shows_home_text(qtbot) -> None:
    widget, controller, presenter, _b = make_ctl(qtbot)
    cb = press_park(widget, presenter)
    cb(ACCEPTED_REPLY)
    controller._on_park_push(PARK_SEQ, 1)
    controller._on_park_push(PARK_HOME, "moved")
    controller._on_park_push(PARK_STATE, "done")
    wait_status(qtbot, widget, TXT_DONE_MOVED)
    assert status(widget) == TXT_DONE_MOVED


# =====================================================================
# К4. already / failed / parking
# =====================================================================


def test_park_leaves_done_already_shows_already_home_text(qtbot) -> None:
    widget, controller, presenter, _b = make_ctl(qtbot)
    cb = press_park(widget, presenter)
    cb(ACCEPTED_REPLY)
    controller._on_park_push(PARK_SEQ, 1)
    controller._on_park_push(PARK_HOME, "already")
    controller._on_park_push(PARK_STATE, "done")
    wait_status(qtbot, widget, TXT_DONE_ALREADY)
    assert status(widget) == TXT_DONE_ALREADY


def test_park_leaves_failed_shows_reason(qtbot) -> None:
    """reason приходит листом ДО state=failed (иначе текст без причины невозможен)."""
    widget, controller, presenter, _b = make_ctl(qtbot)
    cb = press_park(widget, presenter)
    cb(ACCEPTED_REPLY)
    controller._on_park_push(PARK_SEQ, 1)
    controller._on_park_push(PARK_REASON, "серво не отвечает")
    controller._on_park_push(PARK_STATE, "failed")
    expected = "Основная остановка не выполнена: серво не отвечает."
    wait_status(qtbot, widget, expected)
    assert status(widget) == expected


def test_park_state_parking_keeps_status(qtbot) -> None:
    widget, controller, presenter, _b = make_ctl(qtbot)
    cb = press_park(widget, presenter)
    cb(ACCEPTED_REPLY)
    wait_status(qtbot, widget, TXT_ACCEPTED)
    controller._on_park_push(PARK_SEQ, 1)
    controller._on_park_push(PARK_STATE, "parking")
    assert status(widget) == TXT_ACCEPTED


# =====================================================================
# К5. чужой seq
# =====================================================================


def test_park_foreign_seq_leaves_do_not_change_status(qtbot) -> None:
    """Запомнен seq=1; листья прошлого запуска (seq=0, state=done) статус не меняют."""
    widget, controller, presenter, _b = make_ctl(qtbot)
    cb = press_park(widget, presenter)
    cb(ACCEPTED_REPLY)
    wait_status(qtbot, widget, TXT_ACCEPTED)
    controller._on_park_push(PARK_SEQ, 0)
    controller._on_park_push(PARK_HOME, "moved")
    controller._on_park_push(PARK_STATE, "done")
    assert status(widget) == TXT_ACCEPTED


# =====================================================================
# К6. «липкий» текст и телеметрия
# =====================================================================


def _park_done(qtbot):
    widget, controller, presenter, _b = make_ctl(qtbot)
    cb = press_park(widget, presenter)
    cb(ACCEPTED_REPLY)
    controller._on_park_push(PARK_SEQ, 1)
    controller._on_park_push(PARK_HOME, "moved")
    controller._on_park_push(PARK_STATE, "done")
    wait_status(qtbot, widget, TXT_DONE_MOVED)
    return widget, controller, presenter


def test_telemetry_does_not_overwrite_park_result(qtbot) -> None:
    widget, controller, _presenter = _park_done(qtbot)
    controller._on_telemetry_push(STATUS_PATH, TELEMETRY_VALUE)
    assert status(widget) == TXT_DONE_MOVED


def test_other_stop_button_releases_sticky_park_text(qtbot) -> None:
    widget, controller, _presenter = _park_done(qtbot)
    find_button(widget, "Стоп: домой").click()
    controller._on_telemetry_push(STATUS_PATH, TELEMETRY_VALUE)
    wait_status(qtbot, widget, TXT_LINK_OK)
    assert status(widget) == TXT_LINK_OK


def test_telemetry_without_park_writes_link_active(qtbot) -> None:
    """Контроль модели: без park телеметрия пишет «Связь с роботом активна.»."""
    widget, controller, _presenter, _b = make_ctl(qtbot)
    controller._on_telemetry_push(STATUS_PATH, TELEMETRY_VALUE)
    assert status(widget) == TXT_LINK_OK


# =====================================================================
# К7. итог целым узлом .park
# =====================================================================


def test_park_whole_node_dict_done(qtbot) -> None:
    widget, controller, presenter, _b = make_ctl(qtbot)
    cb = press_park(widget, presenter)
    cb(ACCEPTED_REPLY)
    controller._on_park_push(PARK_NODE, {"seq": 1, "state": "done", "home": "moved", "reason": ""})
    wait_status(qtbot, widget, TXT_DONE_MOVED)
    assert status(widget) == TXT_DONE_MOVED


def test_park_whole_node_dict_failed_shows_reason(qtbot) -> None:
    """Вариант К7 для отказа: узел целиком с state=failed и reason."""
    widget, controller, presenter, _b = make_ctl(qtbot)
    cb = press_park(widget, presenter)
    cb(ACCEPTED_REPLY)
    controller._on_park_push(PARK_NODE, {"seq": 1, "state": "failed", "home": "", "reason": "таймаут хода"})
    expected = "Основная остановка не выполнена: таймаут хода."
    wait_status(qtbot, widget, expected)
    assert status(widget) == expected


# =====================================================================
# К8. старый итог в сторе, новый park seq=2
# =====================================================================


def test_stale_done_in_store_does_not_finish_new_park(qtbot) -> None:
    widget, controller, presenter, _b = make_ctl(qtbot)
    # в сторе уже лежит итог прошлого запуска
    controller._on_park_push(PARK_SEQ, 1)
    controller._on_park_push(PARK_STATE, "done")
    cb = press_park(widget, presenter)
    cb({"status": "ok", "accepted": True, "seq": 2})
    wait_status(qtbot, widget, TXT_ACCEPTED)
    # пришла дельта нового seq, а state в сторе всё ещё старый "done"
    controller._on_park_push(PARK_SEQ, 2)
    assert status(widget) == TXT_ACCEPTED
    # новый итог
    controller._on_park_push(PARK_HOME, "moved")
    controller._on_park_push(PARK_STATE, "done")
    wait_status(qtbot, widget, TXT_DONE_MOVED)
    assert status(widget) == TXT_DONE_MOVED


# =====================================================================
# К9. листья пришли ДО ответа
# =====================================================================


def test_leaves_before_reply_are_applied_on_reply(qtbot) -> None:
    widget, controller, presenter, _b = make_ctl(qtbot)
    cb = press_park(widget, presenter)
    controller._on_park_push(PARK_SEQ, 3)
    controller._on_park_push(PARK_HOME, "moved")
    controller._on_park_push(PARK_STATE, "done")
    cb({"status": "ok", "accepted": True, "seq": 3})
    wait_status(qtbot, widget, TXT_DONE_MOVED)
    assert status(widget) == TXT_DONE_MOVED


# =====================================================================
# К10. force_stop
# =====================================================================


def test_force_stop_calls_presenter_with_device(qtbot) -> None:
    widget, _controller, presenter, _b = make_ctl(qtbot)
    widget.force_stop_requested.emit()
    assert presenter.force_stop.call_args.args[0] == "robot_main"


def test_force_stop_ok_reply_shows_hard_text(qtbot) -> None:
    widget, _controller, presenter, _b = make_ctl(qtbot)
    widget.force_stop_requested.emit()
    on_result_of(presenter.force_stop)({"status": "ok"})
    wait_status(qtbot, widget, TXT_FORCE_OK)
    assert status(widget) == TXT_FORCE_OK


def test_park_calls_presenter_with_device(qtbot) -> None:
    widget, _controller, presenter, _b = make_ctl(qtbot)
    widget.park_requested.emit()
    assert presenter.park.call_args.args[0] == "robot_main"
    presenter.force_stop.assert_not_called()


# =====================================================================
# К11. подписка
# =====================================================================


def _bind_calls(bindings):
    result = []
    for call in bindings.bind_fanout.call_args_list:
        pattern = call.args[0] if call.args else call.kwargs["pattern"]
        handler = call.args[1] if len(call.args) > 1 else call.kwargs["handler"]
        result.append((pattern, handler, call.kwargs.get("owner")))
    return result


def test_subscribes_to_park_subtree_with_widget_owner(qtbot) -> None:
    widget, _controller, _presenter, bindings = make_ctl(qtbot)
    calls = _bind_calls(bindings)
    park = [c for c in calls if c[0] == "devices.state.robot_main.park.**"]
    assert len(park) == 1, [c[0] for c in calls]
    assert park[0][2] is widget


def test_status_subscription_kept_next_to_park(qtbot) -> None:
    _widget, _controller, _presenter, bindings = make_ctl(qtbot)
    patterns = [c[0] for c in _bind_calls(bindings)]
    assert any("robot_main.status" in p for p in patterns), patterns


def test_subscribed_handler_drives_status(qtbot) -> None:
    """Обработчик, реально отданный в bind_fanout для .park.**, доводит park до итога."""
    widget, controller, presenter, bindings = make_ctl(qtbot)
    handler = [c[1] for c in _bind_calls(bindings) if c[0] == "devices.state.robot_main.park.**"][0]
    cb = press_park(widget, presenter)
    cb(ACCEPTED_REPLY)
    handler(PARK_SEQ, 1)
    handler(PARK_HOME, "moved")
    handler(PARK_STATE, "done")
    wait_status(qtbot, widget, TXT_DONE_MOVED)
    assert status(widget) == TXT_DONE_MOVED


# =====================================================================
# К12. старые кнопки стопа + новые кнопки в виджете
# =====================================================================


@pytest.mark.parametrize(
    ("attr", "mode"),
    [("_btn_stop1", 1), ("_btn_stop2", 2), ("_btn_stop3", 3)],
)
def test_old_stop_buttons_still_emit_stop_requested(qtbot, attr: str, mode: int) -> None:
    widget = RobotControlWidget()
    qtbot.addWidget(widget)
    got: list[tuple] = []
    widget.stop_requested.connect(lambda *a: got.append(a))
    getattr(widget, attr).click()
    assert got == [(mode,)]


def test_new_buttons_exist_next_to_old_stop_buttons(qtbot) -> None:
    widget = RobotControlWidget()
    qtbot.addWidget(widget)
    park_btn = find_button(widget, "Остановить")
    force_btn = find_button(widget, "Остановить принудительно")
    assert park_btn is not force_btn
    # в одном ряду со старыми стопами (общий родитель-контейнер)
    assert park_btn.parentWidget() is widget._btn_stop1.parentWidget()
    assert force_btn.parentWidget() is widget._btn_stop1.parentWidget()


def test_park_button_click_emits_park_requested_only(qtbot) -> None:
    widget = RobotControlWidget()
    qtbot.addWidget(widget)
    got_park: list[tuple] = []
    got_force: list[tuple] = []
    widget.park_requested.connect(lambda *a: got_park.append(a))
    widget.force_stop_requested.connect(lambda *a: got_force.append(a))
    find_button(widget, "Остановить").click()
    assert got_park == [()]
    assert got_force == []


def test_force_button_click_emits_force_stop_requested_only(qtbot) -> None:
    widget = RobotControlWidget()
    qtbot.addWidget(widget)
    got_park: list[tuple] = []
    got_force: list[tuple] = []
    widget.park_requested.connect(lambda *a: got_park.append(a))
    widget.force_stop_requested.connect(lambda *a: got_force.append(a))
    find_button(widget, "Остановить принудительно").click()
    assert got_force == [()]
    assert got_park == []


def test_buttons_reach_presenter_through_controller(qtbot) -> None:
    """Сквозной путь: клик по кнопкам виджета -> контроллер -> presenter."""
    widget, _controller, presenter, _b = make_ctl(qtbot)
    find_button(widget, "Остановить").click()
    assert presenter.park.call_args.args[0] == "robot_main"
    find_button(widget, "Остановить принудительно").click()
    assert presenter.force_stop.call_args.args[0] == "robot_main"


# =====================================================================
# Пограничное: нет device_id
# =====================================================================


def test_park_without_device_sends_nothing(qtbot) -> None:
    widget = RobotControlWidget()
    qtbot.addWidget(widget)
    presenter = MagicMock()
    controller = RobotWidgetController(widget, presenter, bindings=MagicMock())
    controller.set_device(None)
    widget.park_requested.emit()
    presenter.park.assert_not_called()


def test_force_stop_without_device_sends_nothing(qtbot) -> None:
    widget = RobotControlWidget()
    qtbot.addWidget(widget)
    presenter = MagicMock()
    controller = RobotWidgetController(widget, presenter, bindings=MagicMock())
    controller.set_device(None)
    widget.force_stop_requested.emit()
    presenter.force_stop.assert_not_called()
