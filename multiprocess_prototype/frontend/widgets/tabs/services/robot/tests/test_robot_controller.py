# -*- coding: utf-8 -*-
"""Тесты RobotWidgetController — проводка и UX-ограничения (pytest-qt).

Фаза 4 device-hub: все команды с device_id, ПЧ-группа убрана.
"""

from __future__ import annotations

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


def make_presenter() -> MagicMock:
    presenter = MagicMock()
    presenter.send_test_job = MagicMock()
    presenter.abort = MagicMock()
    presenter.set_mode = MagicMock()
    presenter.set_servo = MagicMock()
    presenter.set_manual_mode = MagicMock()
    presenter.draw_circle = MagicMock()
    presenter.draw_square = MagicMock()
    presenter.abort_draw = MagicMock()
    presenter.set_pen = MagicMock()
    presenter.set_draw_speed = MagicMock()
    presenter.set_overlap = MagicMock()
    presenter.get_telemetry = MagicMock()
    presenter.get_draw_progress = MagicMock()
    return presenter


def make_controller(qtbot) -> tuple[RobotControlWidget, RobotWidgetController, MagicMock]:
    widget = RobotControlWidget()
    qtbot.addWidget(widget)
    presenter = make_presenter()
    controller = RobotWidgetController(widget, presenter)
    return widget, controller, presenter


def test_no_device_shows_hint(qtbot) -> None:
    """Без выбранного устройства — подсказка."""
    widget, controller, _presenter = make_controller(qtbot)
    controller.set_device(None)
    assert "не выбрано" in widget._lbl_status.text()
    assert not widget._combo_mode.isEnabled()


def test_set_device_updates_status(qtbot) -> None:
    widget, controller, _presenter = make_controller(qtbot)
    controller.set_device("robot_main")
    assert "robot_main" in widget._lbl_status.text()


def test_telemetry_enables_mode_when_free(qtbot) -> None:
    widget, controller, _presenter = make_controller(qtbot)
    controller._device_id = "robot_main"
    controller._apply_telemetry(
        {
            "telemetry": {"x_mm": 1.0, "servo": True},
            "free": True,
            "encoder": 5,
            "queue_len": 0,
        }
    )
    assert widget._combo_mode.isEnabled()
    assert "X=1.0" in widget._lbl_telemetry.text()


def test_telemetry_busy_locks_mode_switch(qtbot) -> None:
    """Lua применяет режим только в idle — при занятом роботе переключатель заблокирован."""
    widget, controller, _presenter = make_controller(qtbot)
    controller._device_id = "robot_main"
    controller._apply_telemetry(
        {
            "telemetry": {"x_mm": 0.0},
            "free": False,
            "encoder": 0,
            "queue_len": 1,
        }
    )
    assert not widget._combo_mode.isEnabled()


def test_send_job_passes_device_id(qtbot) -> None:
    widget, controller, presenter = make_controller(qtbot)
    controller.set_device("robot_main")
    widget._spin_x.setValue(12.5)
    widget._spin_y.setValue(-7.0)
    widget._btn_send_job.click()
    # z_mm добавлен в 81664569 (режимы робота): контроллер шлёт третью координату (0.0 без спина z)
    presenter.send_test_job.assert_called_once_with("robot_main", 12.5, -7.0, 0.0)


def test_stop_passes_device_id(qtbot) -> None:
    widget, controller, presenter = make_controller(qtbot)
    controller.set_device("robot_main")
    widget._btn_stop3.click()
    presenter.abort.assert_called_with("robot_main", 3)


def test_draw_abort_passes_device_id(qtbot) -> None:
    widget, controller, presenter = make_controller(qtbot)
    controller.set_device("robot_main")
    widget._btn_draw_abort.click()
    presenter.abort_draw.assert_called_once_with("robot_main")


def test_no_vfd_group(qtbot) -> None:
    """Виджет робота не содержит ПЧ-группу (Фаза 4: отдельная вкладка)."""
    widget = RobotControlWidget()
    qtbot.addWidget(widget)
    # Нет атрибутов ПЧ
    assert not hasattr(widget, "_btn_vfd_run")
    assert not hasattr(widget, "_lbl_vfd")
    assert not hasattr(widget, "vfd_run_requested")


def test_refresh_calls_telemetry_and_draw(qtbot) -> None:
    """Кнопка Обновить вызывает get_telemetry и get_draw_progress."""
    widget, controller, presenter = make_controller(qtbot)
    controller.set_device("robot_main")
    widget._btn_refresh.click()
    presenter.get_telemetry.assert_called_once()
    presenter.get_draw_progress.assert_called_once()
    # Проверить device_id в первом аргументе
    assert presenter.get_telemetry.call_args[0][0] == "robot_main"


def test_jog_forwards_to_presenter(qtbot) -> None:
    """«Ехать» (jog) → presenter.jog(device_id, dx, dy, spd, absolute)."""
    widget, controller, presenter = make_controller(qtbot)
    controller.set_device("robot_main")
    widget.jog_requested.emit(15.0, -20.0, 30, False)
    presenter.jog.assert_called_once_with("robot_main", 15.0, -20.0, 30, False)


def test_jog_abort_forwards_to_presenter(qtbot) -> None:
    """«Стоп» jog → presenter.jog_abort(device_id)."""
    widget, controller, presenter = make_controller(qtbot)
    controller.set_device("robot_main")
    widget.jog_abort_requested.emit()
    presenter.jog_abort.assert_called_once_with("robot_main")


# --- T5.3e.4: «Остановить» (robot_park) — итог собирается из дельт devices.state.<id>.park.* ---

_PARK = "devices.state.robot_main.park"
_TXT_ACCEPTED = "Основная остановка принята: домой, затем серво OFF…"
_TXT_DONE = "Робот дома, серво выключено."
_TXT_LINK = "Связь с роботом активна."
_TELEMETRY = {"telemetry": {"x_mm": 1.0, "servo": True}, "free": True, "encoder": 5, "queue_len": 0}


def make_park_controller(qtbot) -> tuple[RobotControlWidget, RobotWidgetController, MagicMock]:
    widget = RobotControlWidget()
    qtbot.addWidget(widget)
    presenter = make_presenter()
    controller = RobotWidgetController(widget, presenter, bindings=MagicMock())
    controller.set_device("robot_main")
    return widget, controller, presenter


def press_park(widget: RobotControlWidget, presenter: MagicMock):
    """Клик «Остановить»: вернуть on_result, отданный presenter.park."""
    widget.park_requested.emit()
    return presenter.park.call_args.args[1]


def test_park_accepted_then_done_from_state(qtbot) -> None:
    widget, controller, presenter = make_park_controller(qtbot)
    reply = press_park(widget, presenter)
    reply({"status": "ok", "accepted": True, "seq": 1})
    assert widget._lbl_status.text() == _TXT_ACCEPTED
    controller._on_park_push(f"{_PARK}.seq", 1)
    controller._on_park_push(f"{_PARK}.home", "moved")
    assert widget._lbl_status.text() == _TXT_ACCEPTED  # без state итога нет
    controller._on_park_push(f"{_PARK}.state", "done")
    assert widget._lbl_status.text() == _TXT_DONE


def test_park_refusal_message_shown(qtbot) -> None:
    widget, _controller, presenter = make_park_controller(qtbot)
    reply = press_park(widget, presenter)
    reply({"status": "error", "message": "идёт отключение робота"})
    assert widget._lbl_status.text() == "идёт отключение робота"


def test_park_state_with_other_seq_ignored(qtbot) -> None:
    widget, controller, presenter = make_park_controller(qtbot)
    reply = press_park(widget, presenter)
    reply({"status": "ok", "accepted": True, "seq": 1})
    controller._on_park_push(f"{_PARK}.seq", 0)
    controller._on_park_push(f"{_PARK}.home", "moved")
    controller._on_park_push(f"{_PARK}.state", "done")
    assert widget._lbl_status.text() == _TXT_ACCEPTED


def test_park_status_survives_telemetry_push(qtbot) -> None:
    widget, controller, presenter = make_park_controller(qtbot)
    reply = press_park(widget, presenter)
    reply({"status": "ok", "accepted": True, "seq": 1})
    controller._on_park_push(f"{_PARK}.seq", 1)
    controller._on_park_push(f"{_PARK}.home", "moved")
    controller._on_park_push(f"{_PARK}.state", "done")
    controller._on_telemetry_push("devices.state.robot_main.status", _TELEMETRY)
    assert widget._lbl_status.text() == _TXT_DONE
    # телеметрия при этом всё равно применена к остальным полям
    assert "X=1.0" in widget._lbl_telemetry.text()


def test_park_first_publication_as_whole_dict(qtbot) -> None:
    widget, controller, presenter = make_park_controller(qtbot)
    reply = press_park(widget, presenter)
    reply({"status": "ok", "accepted": True, "seq": 1})
    controller._on_park_push(_PARK, {"seq": 1, "state": "done", "home": "moved", "reason": ""})
    assert widget._lbl_status.text() == _TXT_DONE


def test_park_second_run_stale_state_not_shown(qtbot) -> None:
    widget, controller, presenter = make_park_controller(qtbot)
    # итог первого запуска лежит в виде
    controller._on_park_push(f"{_PARK}.seq", 1)
    controller._on_park_push(f"{_PARK}.state", "done")
    reply = press_park(widget, presenter)
    reply({"status": "ok", "accepted": True, "seq": 2})
    controller._on_park_push(f"{_PARK}.seq", 2)  # новый seq, state в сторе ещё старый
    assert widget._lbl_status.text() == _TXT_ACCEPTED
    controller._on_park_push(f"{_PARK}.state", "done")
    assert widget._lbl_status.text() == _TXT_DONE


def test_park_terminal_before_reply_shown(qtbot) -> None:
    widget, controller, presenter = make_park_controller(qtbot)
    reply = press_park(widget, presenter)
    controller._on_park_push(f"{_PARK}.seq", 3)
    controller._on_park_push(f"{_PARK}.home", "moved")
    controller._on_park_push(f"{_PARK}.state", "done")
    reply({"status": "ok", "accepted": True, "seq": 3})
    assert widget._lbl_status.text() == _TXT_DONE


def test_park_nested_dropped_whole_dict_and_leaf_merge(qtbot) -> None:
    """dropped приходит целым словарём, затем лист dropped.jobs — оба ложатся в вид, итог не ломается."""
    widget, controller, presenter = make_park_controller(qtbot)
    press_park(widget, presenter)({"status": "ok", "accepted": True, "seq": 1})
    controller._on_park_push(f"{_PARK}.seq", 1)
    controller._on_park_push(f"{_PARK}.dropped", {"jobs": 2, "queue": 1})
    controller._on_park_push(f"{_PARK}.dropped.jobs", 5)
    assert controller._park_view == {"seq": 1, "dropped": {"jobs": 5, "queue": 1}}
    controller._on_park_push(f"{_PARK}.home", "already")
    controller._on_park_push(f"{_PARK}.state", "done")
    assert widget._lbl_status.text() == "Робот уже дома, серво выключено."


def test_park_failed_without_reason_has_no_dangling_colon(qtbot) -> None:
    widget, controller, presenter = make_park_controller(qtbot)
    press_park(widget, presenter)({"status": "ok", "accepted": True, "seq": 1})
    controller._on_park_push(_PARK, {"seq": 1, "state": "failed", "home": "", "reason": ""})
    assert widget._lbl_status.text() == "Основная остановка не выполнена."


def test_park_repeat_press_ignores_previous_run_until_reply(qtbot) -> None:
    """Второй клик: итог прошлого seq в виде не показывается как итог нового запуска до ответа."""
    widget, controller, presenter = make_park_controller(qtbot)
    press_park(widget, presenter)({"status": "ok", "accepted": True, "seq": 1})
    controller._on_park_push(_PARK, {"seq": 1, "state": "done", "home": "moved", "reason": ""})
    assert widget._lbl_status.text() == _TXT_DONE
    widget._lbl_status.setText("ожидание")  # второй клик ещё без ответа
    widget.park_requested.emit()
    controller._on_park_push(f"{_PARK}.dropped.jobs", 1)  # любая дельта до ответа
    assert widget._lbl_status.text() == "ожидание"


def test_park_set_device_resets_view_and_ignores_old_device_pushes(qtbot) -> None:
    widget, controller, presenter = make_park_controller(qtbot)
    press_park(widget, presenter)({"status": "ok", "accepted": True, "seq": 1})
    controller._on_park_push(f"{_PARK}.seq", 1)
    controller.set_device("robot_2")
    assert controller._park_view == {}
    assert controller._park_seq is None
    assert controller._park_text is None
    # bindings старого устройства не снимаются (дескрипторы не хранятся) — дельты чужого пути игнорируются
    controller._on_park_push(f"{_PARK}.seq", 1)
    controller._on_park_push(f"{_PARK}.state", "done")
    assert controller._park_view == {}
    assert "robot_2" in widget._lbl_status.text()


def test_park_reply_for_previous_device_ignored(qtbot) -> None:
    widget, controller, presenter = make_park_controller(qtbot)
    reply = press_park(widget, presenter)
    controller.set_device("robot_2")
    reply({"status": "ok", "accepted": True, "seq": 1})
    assert controller._park_seq is None
    assert "Основная остановка" not in widget._lbl_status.text()


def test_park_text_kept_by_refresh_responses(qtbot) -> None:
    """_on_telemetry_response и _on_draw_progress липкий текст не снимают."""
    widget, controller, presenter = make_park_controller(qtbot)
    press_park(widget, presenter)({"status": "ok", "accepted": True, "seq": 1})
    controller._on_telemetry_response(_TELEMETRY)
    controller._on_draw_progress({"state": "idle"})
    assert widget._lbl_status.text() == _TXT_ACCEPTED


def test_force_stop_without_ok_shows_message(qtbot) -> None:
    widget, _controller, presenter = make_park_controller(qtbot)
    widget.force_stop_requested.emit()
    presenter.force_stop.call_args.args[1]({"status": "error", "message": "нет связи с роботом"})
    assert widget._lbl_status.text() == "нет связи с роботом"


# --- T5.3e.4, раунд 1 ---

_STATUS = "devices.state.robot_main.status"


def _accept(widget: RobotControlWidget, presenter: MagicMock, seq: int) -> None:
    press_park(widget, presenter)({"status": "ok", "accepted": True, "seq": seq})


def test_park_new_seq_drops_other_stale_leaves(qtbot) -> None:
    """Правило 3 сбрасывает не только state, но и home прошлого запуска."""
    widget, controller, presenter = make_park_controller(qtbot)
    controller._on_park_push(f"{_PARK}.seq", 1)
    controller._on_park_push(f"{_PARK}.home", "already")
    controller._on_park_push(f"{_PARK}.state", "done")
    _accept(widget, presenter, 2)
    controller._on_park_push(f"{_PARK}.seq", 2)
    controller._on_park_push(f"{_PARK}.state", "done")  # home нового запуска ещё не пришёл
    assert widget._lbl_status.text() == _TXT_DONE  # не «Робот уже дома…»


def test_park_double_click_refusal_keeps_first_run_result(qtbot) -> None:
    """Клик -> принято -> parking -> второй клик, отказ «уже идёт» -> итог первого запуска не теряется."""
    widget, controller, presenter = make_park_controller(qtbot)
    _accept(widget, presenter, 1)
    controller._on_park_push(f"{_PARK}.seq", 1)
    controller._on_park_push(f"{_PARK}.state", "parking")
    press_park(widget, presenter)({"status": "error", "message": "основная остановка уже идёт"})
    assert widget._lbl_status.text() == "основная остановка уже идёт"
    controller._on_park_push(f"{_PARK}.home", "moved")
    controller._on_park_push(f"{_PARK}.state", "done")
    assert widget._lbl_status.text() == _TXT_DONE


def test_park_same_seq_after_restart_waits_for_fresh_state(qtbot) -> None:
    """Вид {seq:1, state:done} от прошлой жизни devices; новый ответ seq=1 -> «принята…», а не сразу итог."""
    widget, controller, presenter = make_park_controller(qtbot)
    controller._on_park_push(f"{_PARK}.seq", 1)
    controller._on_park_push(f"{_PARK}.state", "done")
    _accept(widget, presenter, 1)
    assert widget._lbl_status.text() == _TXT_ACCEPTED
    controller._on_park_push(f"{_PARK}.state", "parking")
    assert widget._lbl_status.text() == _TXT_ACCEPTED
    controller._on_park_push(f"{_PARK}.state", "done")
    assert widget._lbl_status.text() == _TXT_DONE


_RELEASING = [
    pytest.param(lambda c: c._on_send_job(1.0, 2.0, 3.0), id="send_job"),
    pytest.param(lambda c: c._on_stop(1), id="stop"),
    pytest.param(lambda c: c._on_mode("cvt"), id="mode"),
    pytest.param(lambda c: c._on_servo(True), id="servo"),
    pytest.param(lambda c: c._on_manual(True), id="manual"),
    pytest.param(lambda c: c._on_jog(1.0, 2.0, 30, False), id="jog"),
    pytest.param(lambda c: c._on_jog_abort(), id="jog_abort"),
    pytest.param(lambda c: c._on_draw_circle(1.0, 2.0, 3.0, 4.0), id="draw_circle"),
    pytest.param(lambda c: c._on_draw_square(1.0, 2.0, 3.0, 4.0, 5.0), id="draw_square"),
    pytest.param(lambda c: c._on_draw_abort(), id="draw_abort"),
    pytest.param(lambda c: c._on_park(), id="park"),
    pytest.param(lambda c: c._on_force_stop(), id="force_stop"),
]
_KEEPING = [
    pytest.param(lambda c: c._on_telemetry_push(_STATUS, _TELEMETRY), id="telemetry_push"),
    pytest.param(lambda c: c._on_telemetry_response(_TELEMETRY), id="telemetry_response"),
    pytest.param(lambda c: c._on_draw_progress({"state": "idle"}), id="draw_progress"),
    pytest.param(lambda c: c._on_refresh(), id="refresh"),
]


def _park_done_controller(qtbot):
    widget, controller, presenter = make_park_controller(qtbot)
    _accept(widget, presenter, 1)
    controller._on_park_push(_PARK, {"seq": 1, "state": "done", "home": "moved", "reason": ""})
    assert widget._lbl_status.text() == _TXT_DONE
    return widget, controller


@pytest.mark.parametrize("handler", _RELEASING)
def test_robot_button_handlers_release_sticky_park_text(qtbot, handler) -> None:
    widget, controller = _park_done_controller(qtbot)
    handler(controller)
    controller._on_telemetry_push(_STATUS, _TELEMETRY)
    assert widget._lbl_status.text() == _TXT_LINK


@pytest.mark.parametrize("handler", _KEEPING)
def test_refresh_and_telemetry_handlers_keep_sticky_park_text(qtbot, handler) -> None:
    widget, controller = _park_done_controller(qtbot)
    handler(controller)
    assert widget._lbl_status.text() == _TXT_DONE  # «Опрос робота…» итог не затирает
    controller._on_telemetry_push(_STATUS, _TELEMETRY)
    assert widget._lbl_status.text() == _TXT_DONE


def test_set_device_subscribes_park_subtree_and_handler_drives_status(qtbot) -> None:
    widget = RobotControlWidget()
    qtbot.addWidget(widget)
    presenter = make_presenter()
    bindings = MagicMock()
    controller = RobotWidgetController(widget, presenter, bindings=bindings)
    controller.set_device("robot_main")
    park_calls = [c for c in bindings.bind_fanout.call_args_list if c.args[0] == "devices.state.robot_main.park.**"]
    assert len(park_calls) == 1
    assert park_calls[0].kwargs["owner"] is widget
    handler = park_calls[0].args[1]
    _accept(widget, presenter, 1)
    handler(f"{_PARK}.seq", 1)
    handler(f"{_PARK}.home", "moved")
    handler(f"{_PARK}.state", "done")
    assert widget._lbl_status.text() == _TXT_DONE


# --- реальная цепочка: TreeStore.merge -> дельты -> GuiStateBindings -> контроллер ---


class _RealChain:
    """Настоящие TreeStore / TelemetryReadModel / GuiStateBindings; презентер и мост — моки."""

    def __init__(self, qtbot) -> None:
        self.store = TreeStore()
        self.read_model = TelemetryReadModel()
        self.bindings = GuiStateBindings(MagicMock(), read_model=self.read_model)
        self.widget = RobotControlWidget()
        qtbot.addWidget(self.widget)
        self.presenter = make_presenter()
        self.controller = RobotWidgetController(self.widget, self.presenter, bindings=self.bindings)
        self.controller.set_device("robot_main")

    def hub_merge(self, value: dict) -> None:
        """Как Plugins/hub/device_hub/plugin.py:_publish_state -> state_proxy.merge -> листовые дельты."""
        for delta in self.store.merge(_PARK, value):
            self.read_model.ingest(delta.path, delta.new_value)
            self.bindings._on_state_msg({"data_type": "state_delta", "path": delta.path, "value": delta.new_value})


def _hub_park(seq: int, state: str, step: str, home=None, servo=None, dropped=None, reason=None, elapsed=None) -> dict:
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


def test_real_chain_park_done_moved(qtbot) -> None:
    chain = _RealChain(qtbot)
    _accept(chain.widget, chain.presenter, 1)
    chain.hub_merge(_hub_park(1, "parking", "activity"))
    chain.hub_merge(_hub_park(1, "parking", "home"))
    chain.hub_merge(_hub_park(1, "parking", "servo", home="moved"))
    assert chain.widget._lbl_status.text() == _TXT_ACCEPTED
    chain.hub_merge(
        _hub_park(1, "done", "servo", home="moved", servo=False, dropped={"jobs": 0, "returns": 0}, elapsed=5.1)
    )
    assert chain.widget._lbl_status.text() == _TXT_DONE


def test_real_chain_park_failed_with_reason(qtbot) -> None:
    """В порядке листьев хаба state приходит раньше reason — итоговый текст всё равно с причиной."""
    chain = _RealChain(qtbot)
    _accept(chain.widget, chain.presenter, 1)
    chain.hub_merge(_hub_park(1, "parking", "activity"))
    chain.hub_merge(_hub_park(1, "failed", "home", dropped={"jobs": 0, "returns": 0}, reason="срок вышел", elapsed=5.1))
    assert chain.widget._lbl_status.text() == "Основная остановка не выполнена: срок вышел."


def test_jog_button_click_emits(qtbot) -> None:
    """Клик по «Ехать» с полей виджета доходит до presenter."""
    widget, controller, presenter = make_controller(qtbot)
    controller.set_device("robot_main")
    widget._jog_dx.setValue(10.0)
    widget._jog_dy.setValue(5.0)
    widget._jog_spd.setValue(25)
    widget._btn_jog.click()
    presenter.jog.assert_called_once_with("robot_main", 10.0, 5.0, 25, False)
