# -*- coding: utf-8 -*-
"""Тесты CalibrationController + resolve_calibration_process (pytest-qt)."""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.frontend.widgets.tabs.services.robot.calibration.controller import (
    CalibrationController,
    build_calibration_controls,
    resolve_calibration_process,
)
from multiprocess_prototype.frontend.widgets.tabs.services.robot.calibration.widget import (
    CalibrationWizardWidget,
)


class FakeBindings:
    """Фейк GuiStateBindings со счётчиками bind/unbind (проверка баланса подписок)."""

    def __init__(self):
        self.fanouts = []
        self.bind_calls = 0
        self.unbind_calls = 0

    def bind_fanout(self, path, cb, owner=None):
        self.bind_calls += 1
        handle = (path, cb, owner)
        self.fanouts.append(handle)
        return handle

    def unbind_fanout(self, handle):
        self.unbind_calls += 1
        if handle in self.fanouts:
            self.fanouts.remove(handle)


class FakeRecipes:
    def __init__(self, active, raw):
        self._active = active
        self._raw = raw

    def get_active(self):
        return self._active

    def read_raw(self, _slug):
        return self._raw


# --- resolve_calibration_process -------------------------------------------
def test_resolve_finds_process():
    raw = {
        "blueprint": {
            "processes": [
                {"process_name": "detector", "plugins": [{"plugin_name": "hsv_mask"}]},
                {"process_name": "cal_node", "plugins": [{"plugin_name": "camera_robot_calibration"}]},
            ]
        }
    }
    assert resolve_calibration_process(FakeRecipes("r1", raw)) == "cal_node"


def test_resolve_fallback_no_match():
    raw = {"blueprint": {"processes": [{"process_name": "x", "plugins": [{"plugin_name": "hsv_mask"}]}]}}
    assert resolve_calibration_process(FakeRecipes("r1", raw)) == "cal"


def test_resolve_fallback_none_recipes():
    assert resolve_calibration_process(None) == "cal"


# --- CalibrationController (Qt) ---------------------------------------------
def _build(qtbot):
    widget = CalibrationWizardWidget()
    qtbot.addWidget(widget)
    presenter = MagicMock()
    bindings = FakeBindings()
    controller = CalibrationController(widget, presenter, bindings=bindings)
    return widget, presenter, bindings, controller


def test_set_device_binds_progress(qtbot):
    widget, presenter, bindings, controller = _build(qtbot)
    controller.set_device("robot_main")
    assert any(p == "calibration.state.cam0.progress" for p, _cb, _o in bindings.fanouts)


def test_rebind_other_robot_no_accumulation(qtbot):
    """Смена робота НЕ копит fanout-подписки: старая телеметрия снимается."""
    widget, presenter, bindings, controller = _build(qtbot)
    controller.set_device("robot_a")
    controller.set_device("robot_b")
    tlm_paths = [p for p, _cb, _o in bindings.fanouts if p.startswith("devices.state.")]
    assert tlm_paths == ["devices.state.robot_b.status"]  # только новая подписка
    # Всего активных: 1 прогресс (cam0, дедуп по камере) + 1 телеметрия.
    assert len(bindings.fanouts) == 2


def test_set_same_device_twice_no_extra_binds(qtbot):
    """Повторный set_device того же робота — дедуп-гарды, новых bind нет."""
    widget, presenter, bindings, controller = _build(qtbot)
    controller.set_device("robot_main")
    calls_after_first = bindings.bind_calls
    controller.set_device("robot_main")
    assert bindings.bind_calls == calls_after_first


def test_begin_other_camera_no_accumulation(qtbot):
    """begin с другой камерой перепривязывает прогресс без накопления подписок."""
    widget, presenter, bindings, controller = _build(qtbot)
    controller.set_device("robot_main")
    widget.begin_requested.emit("cam7", "vfd_belt")
    progress_paths = [p for p, _cb, _o in bindings.fanouts if p.startswith("calibration.state.")]
    assert progress_paths == ["calibration.state.cam7.progress"]  # старая cam0 снята


def test_unbind_balances_all_subscriptions(qtbot):
    """unbind() снимает ОБЕ подписки (прогресс + телеметрия), баланс bind/unbind = 0."""
    widget, presenter, bindings, controller = _build(qtbot)
    controller.set_device("robot_main")
    controller.unbind()
    assert bindings.fanouts == []
    assert bindings.bind_calls == bindings.unbind_calls
    # Метки сброшены — повторный set_device привяжет заново.
    assert controller._camera_id is None
    assert controller._robot_tlm_id is None
    assert controller._progress_owner_path is None


def test_unbind_idempotent(qtbot):
    """Повторный unbind() — не падает и не уводит счётчики в минус."""
    widget, presenter, bindings, controller = _build(qtbot)
    controller.set_device("robot_main")
    controller.unbind()
    controller.unbind()  # хэндлы уже None → unbind_fanout не зовётся
    assert bindings.bind_calls == bindings.unbind_calls


def test_rebind_after_unbind_works(qtbot):
    """После unbind() новый set_device снова подписывает (метки сброшены)."""
    widget, presenter, bindings, controller = _build(qtbot)
    controller.set_device("robot_main")
    controller.unbind()
    controller.set_device("robot_main")
    paths = sorted(p for p, _cb, _o in bindings.fanouts)
    assert paths == ["calibration.state.cam0.progress", "devices.state.robot_main.status"]


def test_begin_includes_robot_id(qtbot):
    widget, presenter, bindings, controller = _build(qtbot)
    controller.set_device("robot_main")
    presenter.begin.reset_mock()  # set_device авто-стартует сессию — сбрасываем счётчик
    widget.begin_requested.emit("cam7", "vfd_belt")
    presenter.begin.assert_called_once_with("cam7", "robot_main", "vfd_belt")


def test_set_device_auto_begins(qtbot):
    widget, presenter, bindings, controller = _build(qtbot)
    controller.set_device("robot_main")
    presenter.begin.assert_called_once_with("cam0", "robot_main", "vfd_belt")


def test_set_point_writes_robot_only(qtbot):
    """Шаг 2 «Точка N» пишет ТОЛЬКО координаты робота + энкодер (px — это Шаг 1)."""
    widget, presenter, bindings, controller = _build(qtbot)
    controller.set_device("robot_main")
    # Push-телеметрия робота (как ручная вкладка)
    controller._on_robot_status(
        "devices.state.robot_main.status",
        {"telemetry": {"x_mm": 12.0, "y_mm": 34.0}, "encoder": 555},
    )
    widget.set_point_requested.emit(2)
    presenter.set_point.assert_called_once_with(2, mm=[12.0, 34.0], enc=555)
    presenter.set_robot_point.assert_not_called()  # сломанный pull НЕ используется


def test_capture_button_triggers_capture(qtbot):
    """Шаг 1 «Зафиксировать» → presenter.capture_image (снимок px + E0)."""
    widget, presenter, bindings, controller = _build(qtbot)
    controller.set_device("robot_main")
    widget.capture_requested.emit()
    presenter.capture_image.assert_called_once_with()


def test_progress_step3_shows_new_robot(qtbot):
    """Шаг 3: новые координаты робота репера (belt_mm2) и E2 попадают в метки."""
    widget, presenter, bindings, controller = _build(qtbot)
    controller.set_device("robot_main")
    controller._on_progress_push(
        "calibration.state.cam0.progress",
        {
            "captured": True,
            "px": [[1, 2], [3, 4], [5, 6], [7, 8], [9, 10]],
            "belt_ref": 0,
            "belt_mm2": [88.5, 12.3],
            "e2": 1300,
        },
    )
    assert "88.5" in widget._lbl_step3_robot.text()
    assert "1300" in widget._lbl_e2.text()
    assert "точка 1" in widget._lbl_step3_px.text()


def test_set_point_without_telemetry_no_call(qtbot):
    widget, presenter, bindings, controller = _build(qtbot)
    controller.set_device("robot_main")
    widget.set_point_requested.emit(0)  # телеметрии ещё не было
    presenter.set_point.assert_not_called()


class FakeRobotPresenter:
    """Синхронный pull: get_telemetry сразу зовёт callback с заранее заданным ответом."""

    def __init__(self, telemetry):
        self._tlm = telemetry
        self.calls = []

    def get_telemetry(self, device_id, on_result):
        self.calls.append(device_id)
        on_result(self._tlm)


def test_set_point_pulls_robot_on_button(qtbot):
    """«Точка N» делает свежий pull робота и пишет mm/enc из ответа (не из push-кэша)."""
    widget = CalibrationWizardWidget()
    qtbot.addWidget(widget)
    presenter = MagicMock()
    robot = FakeRobotPresenter({"telemetry": {"x_mm": 12.0, "y_mm": 34.0}, "encoder": 555})
    controller = CalibrationController(widget, presenter, bindings=FakeBindings(), robot_presenter=robot)
    controller.set_device("robot_main")  # разовый pull → «Робот сейчас» заполнена
    assert "robot_main" in robot.calls
    widget.set_point_requested.emit(2)
    presenter.set_point.assert_called_once_with(2, mm=[12.0, 34.0], enc=555)


def test_set_point_pull_empty_telemetry_no_write(qtbot):
    """Пустой ответ робота → точку не пишем, статус об отсутствии телеметрии."""
    widget = CalibrationWizardWidget()
    qtbot.addWidget(widget)
    presenter = MagicMock()
    robot = FakeRobotPresenter({"status": "ok"})  # пусто (как сломанный pull)
    controller = CalibrationController(widget, presenter, bindings=FakeBindings(), robot_presenter=robot)
    controller.set_device("robot_main")
    widget.set_point_requested.emit(0)
    presenter.set_point.assert_not_called()


def test_progress_push_updates_widget(qtbot):
    widget, presenter, bindings, controller = _build(qtbot)
    controller.set_device("robot_main")
    snap = {
        "phase": "saved",
        "message": "Готово",
        "error": None,
        "captured": True,
        "live_found": 5,
        "expected_points": 5,
        "points_collected": 5,
        "scale_done": True,
        "mm_per_count": 0.05,
        "belt_dir": [1.0, 0.0],
        "reproj": {"center": 0.4, "mean": 0.3, "max": 0.5},
        "passed": True,
        "saved_path": "config/calibration/cam0.yaml",
        "reproj_threshold_mm": 2.0,
    }
    controller._on_progress_push("calibration.state.cam0.progress", snap)
    assert widget._btn_save.isEnabled()  # passed → save активна
    assert "0.4" in widget._lbl_reproj.text()
    assert "cam0.yaml" in widget._lbl_saved.text()


def test_build_calibration_controls_wires(qtbot):
    runtime = MagicMock()
    runtime.command_sender = MagicMock()
    widget, controller, presenter = build_calibration_controls(
        runtime=runtime, request_runner=MagicMock(), bindings=FakeBindings(), target_process="cal_node"
    )
    qtbot.addWidget(widget)
    assert presenter._target == "cal_node"
    assert isinstance(controller, CalibrationController)
