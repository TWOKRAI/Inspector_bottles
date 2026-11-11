# -*- coding: utf-8 -*-
"""Тесты RobotWidgetController — проводка и UX-ограничения (pytest-qt).

Фаза 4 device-hub: все команды с device_id, ПЧ-группа убрана.
"""

from __future__ import annotations

import time
from collections import Counter
from unittest.mock import MagicMock

import pytest
import shiboken6

from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
from multiprocess_framework.modules.telemetry_readmodel_module.telemetry_read_model import TelemetryReadModel
from multiprocess_prototype.frontend.state.bindings import DELETED, GuiStateBindings
from multiprocess_prototype.frontend.widgets.tabs.services.robot import controller as controller_module
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

    def __init__(self, qtbot, *, start: bool = True) -> None:
        self.store = TreeStore()
        self.read_model = TelemetryReadModel()
        self.bindings = GuiStateBindings(MagicMock(), read_model=self.read_model)
        self.widget = RobotControlWidget()
        qtbot.addWidget(self.widget)
        self.presenter = make_presenter()
        if start:
            self.start()

    def start(self) -> None:
        """Создать контроллер и выбрать robot_main (после этого replay кэша уже сработал)."""
        self.controller = RobotWidgetController(self.widget, self.presenter, bindings=self.bindings)
        self.controller.set_device("robot_main")

    def hub_merge(self, value: dict, path: str = _PARK) -> None:
        """Как Plugins/hub/device_hub/plugin.py:_publish_state -> state_proxy.merge -> листовые дельты."""
        for delta in self.store.merge(path, value):
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


# --- T5.3e.6: вид ``.status`` собирается из листовых дельт; текст кнопок и итог park живут против пушей ---

_DEADLINE_TXT = "Основная остановка: итог не получен за {} с. Проверьте робота."


def _hub_status(x: float = 300.0, y: float = 200.0, *, free: bool = True, ts: float | None = None) -> dict:
    """Снимок статуса в форме хаба (Plugins/hub/device_hub/plugin.py:_publish_state)."""
    return {
        "quality": "good",
        "ts": time.time() if ts is None else ts,
        "stats": {"jobs_done": 3},
        "queue_len": 0,
        "telemetry": {"x_mm": x, "y_mm": y, "z_mm": 50.0, "rz_deg": 0.0, "servo": True},
        "free": free,
        "encoder": 5,
    }


def _accept_with_timeout(widget: RobotControlWidget, presenter: MagicMock, reply: dict) -> float:
    """Клик «Остановить» + ответ хаба; вернуть момент ответа (time.monotonic)."""
    press_park(widget, presenter)(reply)
    return time.monotonic()


def _wait_to(qtbot, t0: float, at_s: float) -> None:
    """Дожить в цикле событий Qt до at_s секунд после t0."""
    left_ms = int((at_s - (time.monotonic() - t0)) * 1000)
    if left_ms > 0:
        qtbot.wait(left_ms)


def _wait_text_by(qtbot, widget: RobotControlWidget, t0: float, latest_s: float, text: str) -> None:
    """Дождаться точного статуса не позже latest_s после t0 (явный timeout)."""
    left_ms = int((latest_s - (time.monotonic() - t0)) * 1000)
    qtbot.waitUntil(lambda: widget._lbl_status.text() == text, timeout=max(left_ms, 1))


# REDS


def test_real_chain_status_merge_updates_telemetry(qtbot) -> None:
    chain = _RealChain(qtbot)
    chain.hub_merge(_hub_status(x=300.0), path=_STATUS)
    chain.hub_merge(_hub_status(x=310.0), path=_STATUS)
    assert "X=310.0" in chain.widget._lbl_telemetry.text()


def test_real_chain_status_partial_merge_keeps_view(qtbot) -> None:
    """Вторая публикация отличается только free: приходит один лист, вид от первой сохраняется."""
    chain = _RealChain(qtbot)
    base = time.time()
    chain.hub_merge(_hub_status(x=300.0, free=False, ts=base), path=_STATUS)
    assert not chain.widget._combo_mode.isEnabled()
    chain.hub_merge(_hub_status(x=300.0, free=True, ts=base), path=_STATUS)
    assert chain.widget._combo_mode.isEnabled()
    assert "X=300.0" in chain.widget._lbl_telemetry.text()


def test_set_device_releases_previous_subscriptions(qtbot) -> None:
    ensured: list[str] = []
    released: list[str] = []
    bindings = GuiStateBindings(
        MagicMock(),
        read_model=TelemetryReadModel(),
        ensure_subscription=ensured.append,
        release_subscription=released.append,
    )
    widget = RobotControlWidget()
    qtbot.addWidget(widget)
    controller = RobotWidgetController(widget, make_presenter(), bindings=bindings)
    controller.set_device("robot_main")
    main_patterns = {p for p in ensured if "robot_main" in p}
    assert main_patterns, "set_device('robot_main') не оформил подписок на robot_main"
    controller.set_device("robot_2")
    assert main_patterns <= set(released)


def test_stale_then_push_restores_park_text(qtbot, monkeypatch) -> None:
    widget, controller, presenter = make_park_controller(qtbot)
    _accept(widget, presenter, 1)
    controller._on_park_push(_PARK, {"seq": 1, "state": "done", "home": "moved", "reason": ""})
    controller._on_telemetry_push(_STATUS, {**_TELEMETRY, "ts": time.time()})
    assert widget._lbl_status.text() == _TXT_DONE
    real_time = time.time
    monkeypatch.setattr(controller_module.time, "time", lambda: real_time() + 5.0)
    controller._check_stale()
    assert widget._lbl_status.text().startswith("Нет связи с hub")
    controller._on_telemetry_push(_STATUS, {**_TELEMETRY, "ts": time.time()})  # свежий пуш (часы тоже сдвинуты)
    assert widget._lbl_status.text() == _TXT_DONE


def test_push_keeps_button_text_while_link_ok(qtbot) -> None:
    widget, controller, _presenter = make_park_controller(qtbot)
    controller._on_telemetry_push(_STATUS, {**_TELEMETRY, "ts": time.time()})
    assert widget._lbl_status.text() == _TXT_LINK
    controller._on_send_job(1.0, 2.0, 0.0)
    assert widget._lbl_status.text() == "Тест-job X=1.0 Y=2.0 Z=0.0 отправлен."
    controller._on_telemetry_push(f"{_STATUS}.ts", time.time())
    assert widget._lbl_status.text() == "Тест-job X=1.0 Y=2.0 Z=0.0 отправлен."


@pytest.mark.parametrize(
    ("timeout_s", "not_yet_s", "latest_s", "shown_s"),
    [
        pytest.param(1, 3.5, 4.6, 4, id="timeout_1"),
        pytest.param(1.5, 4.0, 5.1, 5, id="timeout_1_5_rounds_up"),
    ],
)
@pytest.mark.timeout(30)
def test_park_deadline_shows_no_result_text(qtbot, timeout_s, not_yet_s, latest_s, shown_s) -> None:
    widget, _controller, presenter = make_park_controller(qtbot)
    t0 = _accept_with_timeout(widget, presenter, {"status": "ok", "accepted": True, "seq": 1, "timeout_s": timeout_s})
    _wait_to(qtbot, t0, not_yet_s)
    assert widget._lbl_status.text() == _TXT_ACCEPTED
    _wait_text_by(qtbot, widget, t0, latest_s, _DEADLINE_TXT.format(shown_s))


@pytest.mark.parametrize(
    "reply_extra",
    [
        pytest.param({}, id="no_timeout_s"),
        pytest.param({"timeout_s": True}, id="bool_timeout_s"),
        pytest.param({"timeout_s": 0}, id="zero"),
        pytest.param({"timeout_s": -1}, id="negative"),
        pytest.param({"timeout_s": 61}, id="above_hub_ceiling"),
        pytest.param({"timeout_s": "30"}, id="string"),
        pytest.param({"timeout_s": None}, id="none"),
        pytest.param({"timeout_s": float("nan")}, id="nan"),
    ],
)
@pytest.mark.timeout(30)
def test_park_deadline_fallback_when_timeout_missing(qtbot, monkeypatch, reply_extra) -> None:
    monkeypatch.setattr(controller_module, "_PARK_TIMEOUT_FALLBACK_S", 1.0)
    widget, _controller, presenter = make_park_controller(qtbot)
    t0 = _accept_with_timeout(widget, presenter, {"status": "ok", "accepted": True, "seq": 1, **reply_extra})
    _wait_text_by(qtbot, widget, t0, 4.6, _DEADLINE_TXT.format(4))


def test_warm_cache_select_shows_cached_telemetry(qtbot) -> None:
    """Снимки прошли до создания контроллера: set_device показывает кэш, дельта одного листа вид не стирает."""
    chain = _RealChain(qtbot, start=False)
    base = time.time()
    chain.hub_merge(_hub_status(x=300.0, ts=base), path=_STATUS)
    chain.hub_merge(_hub_status(x=310.0, ts=base), path=_STATUS)
    chain.start()
    assert chain.widget._lbl_status.text() == _TXT_LINK
    assert "X=310.0" in chain.widget._lbl_telemetry.text()
    chain.hub_merge(_hub_status(x=310.0, y=222.0, ts=base), path=_STATUS)  # изменился только y_mm
    assert "X=310.0" in chain.widget._lbl_telemetry.text()
    assert chain.widget._combo_mode.isEnabled()


# GUARDS


def test_status_foreign_device_leaf_ignored(qtbot) -> None:
    widget, controller, _presenter = make_park_controller(qtbot)
    controller.set_device("robot_2")
    before = widget._lbl_telemetry.text()
    controller._on_telemetry_push("devices.state.robot_main.status.telemetry.x_mm", 999.0)
    assert widget._lbl_telemetry.text() == before


@pytest.mark.timeout(30)
def test_park_deadline_cancelled_by_terminal(qtbot) -> None:
    widget, controller, presenter = make_park_controller(qtbot)
    t0 = _accept_with_timeout(widget, presenter, {"status": "ok", "accepted": True, "seq": 1, "timeout_s": 1})
    controller._on_park_push(_PARK, {"seq": 1, "state": "done", "home": "moved", "reason": ""})
    _wait_to(qtbot, t0, 4.6)
    assert widget._lbl_status.text() == _TXT_DONE


@pytest.mark.timeout(30)
def test_park_deadline_cancelled_by_unbind(qtbot) -> None:
    widget, controller, presenter = make_park_controller(qtbot)
    with qtbot.capture_exceptions() as exceptions:
        t0 = _accept_with_timeout(widget, presenter, {"status": "ok", "accepted": True, "seq": 1, "timeout_s": 1})
        controller.unbind()
        _wait_to(qtbot, t0, 4.6)
        assert "итог не получен" not in widget._lbl_status.text()
    assert exceptions == []


@pytest.mark.timeout(30)
def test_park_late_terminal_overrides_deadline(qtbot) -> None:
    widget, controller, presenter = make_park_controller(qtbot)
    t0 = _accept_with_timeout(widget, presenter, {"status": "ok", "accepted": True, "seq": 1, "timeout_s": 1})
    _wait_text_by(qtbot, widget, t0, 4.6, _DEADLINE_TXT.format(4))
    controller._on_park_push(_PARK, {"seq": 1, "state": "done", "home": "moved", "reason": ""})
    assert widget._lbl_status.text() == _TXT_DONE


@pytest.mark.timeout(30)
def test_timers_after_widget_destroyed_no_error(qtbot) -> None:
    """Виджет удалён (shiboken6.delete, не deleteLater): _check_stale и срок park не трогают его."""
    widget = RobotControlWidget()  # без qtbot.addWidget: иначе teardown закрывает уже удалённый C++-объект
    presenter = make_presenter()
    controller = RobotWidgetController(widget, presenter, bindings=MagicMock())
    controller.set_device("robot_main")
    controller._on_telemetry_push(_STATUS, {**_TELEMETRY, "ts": time.time()})
    press_park(widget, presenter)({"status": "ok", "accepted": True, "seq": 1, "timeout_s": 1})
    with qtbot.capture_exceptions() as exceptions:
        shiboken6.delete(widget)
        qtbot.wait(5000)
    controller.unbind()
    assert exceptions == []


def test_status_deleted_drops_leaf(qtbot) -> None:
    widget, controller, _presenter = make_park_controller(qtbot)
    controller._on_telemetry_push(_STATUS, _hub_status(x=300.0, free=True))
    assert "X=300.0" in widget._lbl_telemetry.text()
    # (а) удалён лист x_mm: подпись в этот момент не меняется, со следующей дельтой берётся умолчание
    controller._on_telemetry_push(f"{_STATUS}.telemetry.x_mm", DELETED)
    assert "X=300.0" in widget._lbl_telemetry.text()
    controller._on_telemetry_push(f"{_STATUS}.ts", time.time())
    assert "X=0.0" in widget._lbl_telemetry.text()
    # (б) удалён весь узел: вид пуст, подпись телеметрии не меняется, переключатель режима недоступен
    controller._on_telemetry_push(_STATUS, _hub_status(x=300.0, free=True))
    assert widget._combo_mode.isEnabled()
    controller._on_telemetry_push(_STATUS, DELETED)
    after_delete = widget._lbl_telemetry.text()
    controller._on_telemetry_push(f"{_STATUS}.ts", time.time())
    assert widget._lbl_telemetry.text() == after_delete
    assert not widget._combo_mode.isEnabled()


# --- T5.3e.6, ревью стадии 5 (раунд 1): сторожа на подписки, порядок срока, сброс при смене устройства ---


def _ledger_controller(qtbot) -> tuple[RobotWidgetController, list[str], list[str]]:
    """Контроллер на настоящем GuiStateBindings; списки ensure / release подписок."""
    ensured: list[str] = []
    released: list[str] = []
    bindings = GuiStateBindings(
        MagicMock(),
        read_model=TelemetryReadModel(),
        ensure_subscription=ensured.append,
        release_subscription=released.append,
    )
    widget = RobotControlWidget()
    qtbot.addWidget(widget)
    controller = RobotWidgetController(widget, make_presenter(), bindings=bindings)
    controller.set_device("robot_main")
    assert ensured, "set_device('robot_main') не оформил подписок"
    return controller, ensured, released


def test_unbind_releases_every_subscription(qtbot) -> None:
    controller, ensured, released = _ledger_controller(qtbot)
    controller.unbind()
    assert Counter(ensured) == Counter(released)


def test_set_device_none_releases_every_subscription(qtbot) -> None:
    controller, ensured, released = _ledger_controller(qtbot)
    controller.set_device(None)
    assert Counter(ensured) == Counter(released)


@pytest.mark.timeout(30)
def test_terminal_before_reply_not_overwritten_by_deadline(qtbot) -> None:
    """Итог пришёл раньше ответа: срок взводится до _render_park, итог аннулирует его и не затирается текстом срока."""
    widget, controller, presenter = make_park_controller(qtbot)
    reply = press_park(widget, presenter)
    controller._on_park_push(_PARK, {"seq": 1, "state": "done", "home": "moved", "reason": ""})
    reply({"status": "ok", "accepted": True, "seq": 1, "timeout_s": 1})
    t0 = time.monotonic()
    assert widget._lbl_status.text() == _TXT_DONE
    _wait_to(qtbot, t0, 4.6)
    assert widget._lbl_status.text() == _TXT_DONE


def test_set_device_resets_view_and_link_state(qtbot) -> None:
    """Вид и признак связи прошлого устройства не переходят на новое."""
    chain = _RealChain(qtbot)
    chain.hub_merge(_hub_status(x=300.0, free=True), path=_STATUS)
    assert chain.widget._lbl_status.text() == _TXT_LINK
    assert chain.widget._combo_mode.isEnabled()
    # в кэше robot_2 только quality и ts: без telemetry и free
    chain.hub_merge({"quality": "good", "ts": time.time()}, path="devices.state.robot_2.status")
    chain.controller.set_device("robot_2")
    assert not chain.widget._combo_mode.isEnabled()  # free прошлого вида не перенесён
    assert chain.widget._lbl_status.text() != _TXT_LINK
    chain.hub_merge(_hub_status(x=111.0, free=True), path="devices.state.robot_2.status")
    assert chain.widget._lbl_status.text() == _TXT_LINK  # переход в ok на новом устройстве снова пишет текст


def test_set_device_resets_status_timestamp(qtbot, monkeypatch) -> None:
    """Время последнего пуша прошлого устройства не даёт «Нет связи» на новом."""
    chain = _RealChain(qtbot)
    chain.hub_merge(_hub_status(), path=_STATUS)
    chain.controller.set_device("robot_2")  # кэша robot_2 нет
    real_time = time.time
    monkeypatch.setattr(controller_module.time, "time", lambda: real_time() + 10.0)
    chain.controller._check_stale()
    assert "Нет связи" not in chain.widget._lbl_status.text()


def test_stale_ts_then_fresh_push_restores_link_text(qtbot) -> None:
    """Хаб жив, устройство замёрзло (ts встал): после свежего ts текст связи возвращается."""
    chain = _RealChain(qtbot)
    now = time.time()
    chain.hub_merge(_hub_status(ts=now), path=_STATUS)
    assert chain.widget._lbl_status.text() == _TXT_LINK
    chain.hub_merge(_hub_status(ts=now - 10.0), path=_STATUS)
    assert chain.widget._lbl_status.text().startswith("Нет связи с hub")
    chain.hub_merge(_hub_status(ts=now + 1.0), path=_STATUS)
    assert chain.widget._lbl_status.text() == _TXT_LINK


def test_refresh_then_pull_response_restores_link_text(qtbot) -> None:
    widget, controller, _presenter = make_park_controller(qtbot)
    controller._on_telemetry_push(_STATUS, {**_TELEMETRY, "ts": time.time()})
    assert widget._lbl_status.text() == _TXT_LINK
    controller._on_refresh()
    assert widget._lbl_status.text() == "Опрос робота…"
    controller._on_telemetry_response({**_TELEMETRY, "ts": time.time()})
    assert widget._lbl_status.text() == _TXT_LINK


def test_empty_pull_response_then_live_push_restores_link_text(qtbot) -> None:
    widget, controller, _presenter = make_park_controller(qtbot)
    controller._on_telemetry_push(_STATUS, {**_TELEMETRY, "ts": time.time()})
    controller._on_telemetry_response({})
    assert widget._lbl_status.text() == "Робот не отвечает (телеметрия пуста)."
    controller._on_telemetry_push(f"{_STATUS}.ts", time.time())
    assert widget._lbl_status.text() == _TXT_LINK
