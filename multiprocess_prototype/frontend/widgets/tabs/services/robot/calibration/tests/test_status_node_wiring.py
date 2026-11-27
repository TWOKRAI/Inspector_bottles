# -*- coding: utf-8 -*-
"""Проводка Task 2.8f: калибровка робота получает узел ``devices.state.<id>.status`` из листьев.

Настоящие ``DataReceiverBridge``, ``TelemetryViewModel``, ``GuiStateBindings`` в порядке
``app.py``; дельты и маркер конца пачки идут через ``GuiProcess._on_state_deltas_to_bridge``.
Подменён только presenter (команды наружу). Наблюдается метка «Робот сейчас».
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from multiprocess_framework.modules.frontend_module import TelemetryViewModel
from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta
from multiprocess_prototype.frontend.bridge_impl import DataReceiverBridge
from multiprocess_prototype.frontend.process import GuiProcess
from multiprocess_prototype.frontend.state.bindings import GuiStateBindings
from multiprocess_prototype.frontend.widgets.tabs.services.robot.calibration.controller import (
    CalibrationController,
)
from multiprocess_prototype.frontend.widgets.tabs.services.robot.calibration.widget import (
    CalibrationWizardWidget,
)


def test_robot_live_label_follows_leaf_deltas(qtbot) -> None:
    bridge = DataReceiverBridge()
    vm = TelemetryViewModel()
    bindings = GuiStateBindings(bridge, read_model=vm)
    bridge.add_state_listener(vm.on_state_delta)
    widget = CalibrationWizardWidget()
    qtbot.addWidget(widget)
    controller = CalibrationController(widget, MagicMock(), bindings=bindings)
    controller.set_device("r1")
    assert widget._lbl_robot_live.text() == "Робот сейчас: —"

    leaves = {
        "devices.state.r1.status.telemetry.x_mm": 12.5,
        "devices.state.r1.status.telemetry.y_mm": -3.0,
        "devices.state.r1.status.encoder": 4100,
    }
    deltas = [Delta(path=p, old_value=MISSING, new_value=v, source="test") for p, v in leaves.items()]
    GuiProcess._on_state_deltas_to_bridge(SimpleNamespace(_bridge=bridge), deltas)

    assert widget._lbl_robot_live.text() == "Робот сейчас: X=12.5  Y=-3.0  энкодер=4100"
    controller.unbind()
