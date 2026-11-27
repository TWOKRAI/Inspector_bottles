# -*- coding: utf-8 -*-
"""Проводка Task 2.8f: комбо и список устройств получают узел ``devices.registry.<id>`` из листьев.

Настоящие ``DataReceiverBridge``, ``TelemetryViewModel``, ``GuiStateBindings`` в порядке
``app.py``; дельты и маркер конца пачки идут через ``GuiProcess._on_state_deltas_to_bridge``.
Из главного потока доставка синхронная. Наблюдается содержимое виджетов.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from multiprocess_framework.modules.frontend_module import TelemetryViewModel
from multiprocess_framework.modules.state_store_module.core.delta import MISSING, Delta
from multiprocess_prototype.frontend.bridge_impl import DataReceiverBridge
from multiprocess_prototype.frontend.process import GuiProcess
from multiprocess_prototype.frontend.state.bindings import GuiStateBindings
from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.combo import (
    DeviceComboController,
)
from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.device_list_panel import (
    DeviceListPanel,
)
from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.tests.test_master_detail import (
    _robot,
    _store,
)


def _wire() -> tuple[DataReceiverBridge, TelemetryViewModel, GuiStateBindings]:
    bridge = DataReceiverBridge()
    vm = TelemetryViewModel()
    bindings = GuiStateBindings(bridge, read_model=vm)
    bridge.add_state_listener(vm.on_state_delta)
    return bridge, vm, bindings


def _send_batch(bridge: DataReceiverBridge, leaves: dict[str, Any]) -> None:
    deltas = [Delta(path=p, old_value=MISSING, new_value=v, source="test") for p, v in leaves.items()]
    GuiProcess._on_state_deltas_to_bridge(SimpleNamespace(_bridge=bridge), deltas)


_REGISTRY_LEAVES = {
    "devices.registry.r1.id": "r1",
    "devices.registry.r1.name": "Робот 1",
    "devices.registry.r1.kind": "robot",
    "devices.registry.r1.transport.port": 502,
}


def test_combo_gets_device_from_leaf_deltas(qtbot) -> None:
    bridge, vm, bindings = _wire()
    combo = DeviceComboController(kind="robot", presenter=MagicMock(), bindings=bindings)
    qtbot.addWidget(combo.widget())
    assert combo._combo.count() == 0

    _send_batch(bridge, _REGISTRY_LEAVES)

    assert combo._combo.count() == 1
    assert combo._combo.currentText() == "Робот 1 (r1) [?]"
    assert combo.current_device_id() == "r1"


def test_device_list_rereads_recipe_on_leaf_deltas(qtbot) -> None:
    bridge, vm, bindings = _wire()
    store = _store([])
    panel = DeviceListPanel(kind="robot", recipe_store=store, bindings=bindings)
    qtbot.addWidget(panel)
    assert panel.current_device_ids() == []

    # Рецепт меняется мимо панели: перечитать его она может только по дельте реестра.
    store.upsert(_robot("r1"))
    _send_batch(bridge, _REGISTRY_LEAVES)

    qtbot.waitUntil(lambda: panel.current_device_ids() == ["r1"], timeout=2000)
