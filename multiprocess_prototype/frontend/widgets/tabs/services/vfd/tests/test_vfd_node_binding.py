# -*- coding: utf-8 -*-
"""Приёмочные тесты Task 2.8f, REDS 11: после смены устройства старое не доходит до виджета.

Настоящие ``DataReceiverBridge``, ``GuiStateBindings``, ``TelemetryViewModel``, контроллер
и виджет ПЧ; подменён только presenter (команды наружу). Наблюдается то, что получил
виджет: вызовы ``set_status``. В каждом тесте есть контроль - новое устройство доходит
тем же путём, иначе «0 вызовов» ничего бы не значило.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.frontend_module import TelemetryViewModel
from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta
from multiprocess_prototype.frontend.bridge_impl import DataReceiverBridge
from multiprocess_prototype.frontend.state.bindings import GuiStateBindings
from multiprocess_prototype.frontend.state.delta_message import state_delta_message
from multiprocess_prototype.frontend.widgets.tabs.services.vfd.controller import (
    VfdWidgetController,
)
from multiprocess_prototype.frontend.widgets.tabs.services.vfd.widget import (
    VfdControlWidget,
)


@pytest.fixture
def switched(qtbot) -> Iterator[SimpleNamespace]:
    """Контроллер, переключённый с устройства "old" на "new"; вызовы set_status пишутся."""
    bridge = DataReceiverBridge()
    vm = TelemetryViewModel()
    bindings = GuiStateBindings(bridge, read_model=vm)
    bridge.add_state_listener(vm.on_state_delta)

    widget = VfdControlWidget()
    qtbot.addWidget(widget)
    statuses: list[str] = []
    real_set_status = widget.set_status

    def recording_set_status(text: str) -> None:
        statuses.append(text)
        real_set_status(text)

    widget.set_status = recording_set_status  # type: ignore[method-assign]
    controller = VfdWidgetController(widget, MagicMock(), bindings=bindings)
    controller.set_device("old")
    controller.set_device("new")
    statuses.clear()

    def put(path: str, value: Any) -> None:
        delta = Delta(path=path, old_value=MISSING, new_value=value, source="test")
        bridge.dispatch(state_delta_message(delta))

    def end() -> None:
        bridge.dispatch({"data_type": "state_batch_end"})

    yield SimpleNamespace(put=put, end=end, statuses=statuses, keep=(bridge, vm, bindings, controller))
    controller.unbind()


def test_old_device_leaf_delta_does_not_reach_widget(switched: SimpleNamespace) -> None:
    switched.put("devices.state.old.status.x", 1)
    switched.end()
    assert switched.statuses == []

    switched.put("devices.state.new.status.running", True)
    switched.end()
    assert len(switched.statuses) == 1
    assert "RUN" in switched.statuses[0]


def test_old_device_exact_node_set_does_not_reach_widget(switched: SimpleNamespace) -> None:
    switched.put("devices.state.old.status", {"running": True})
    switched.end()
    assert switched.statuses == []

    switched.put("devices.state.new.status", {"running": True})
    switched.end()
    assert len(switched.statuses) == 1
    assert "RUN" in switched.statuses[0]
