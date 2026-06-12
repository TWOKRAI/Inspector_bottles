# -*- coding: utf-8 -*-
"""Тесты DeviceListPanel + DeviceMasterDetail (pytest-qt, Фаза C).

Список строится из рецепта; «+ Добавить» — последний; выбор устройства строит
страницу (lazy) и переключает стек; удаление из рецепта → выбор сбрасывается.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QWidget

from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.device_list_panel import (
    DeviceListPanel,
)
from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.master_detail import (
    DeviceMasterDetail,
    _render_device_io,
)
from multiprocess_prototype.frontend.widgets.tabs.services.devices_common.recipe_devices import (
    RecipeDevicesStore,
)


class _DictRecipeStore:
    def __init__(self, active="demo", devices=None):
        self._active = active
        self._data = {"demo": {"devices": list(devices or [])}}

    def get_active(self):
        return self._active

    def read_raw(self, slug):
        return self._data.get(slug)

    def save_raw(self, slug, data):
        self._data.setdefault(slug, {}).update(data)


def _robot(dev_id):
    return {"id": dev_id, "name": dev_id.upper(), "kind": "robot"}


def _store(devices=None, active="demo"):
    return RecipeDevicesStore(_DictRecipeStore(active=active, devices=devices))


class TestDeviceListPanel:
    def test_lists_devices_plus_add_last(self, qtbot):
        panel = DeviceListPanel(kind="robot", recipe_store=_store([_robot("r1"), _robot("r2")]))
        qtbot.addWidget(panel)
        # 2 устройства + строка добавления
        assert panel._list.count() == 3
        assert panel._list.item(2).text() == "+ Добавить устройство"
        assert panel.current_device_ids() == ["r1", "r2"]

    def test_filters_by_kind(self, qtbot):
        devices = [_robot("r1"), {"id": "v1", "name": "VFD", "kind": "vfd"}]
        panel = DeviceListPanel(kind="vfd", recipe_store=_store(devices))
        qtbot.addWidget(panel)
        assert panel.current_device_ids() == ["v1"]

    def test_no_active_recipe_only_add_row(self, qtbot):
        panel = DeviceListPanel(kind="robot", recipe_store=_store(active=None))
        qtbot.addWidget(panel)
        assert panel._list.count() == 1  # только «+ Добавить»
        assert panel.current_device_ids() == []

    def test_device_selected_signal(self, qtbot):
        panel = DeviceListPanel(kind="robot", recipe_store=_store([_robot("r1")]))
        qtbot.addWidget(panel)
        with qtbot.waitSignal(panel.device_selected) as blocker:
            panel._on_item_clicked(panel._list.item(0))
        assert blocker.args == ["r1"]

    def test_add_requested_signal(self, qtbot):
        panel = DeviceListPanel(kind="robot", recipe_store=_store([_robot("r1")]))
        qtbot.addWidget(panel)
        with qtbot.waitSignal(panel.add_requested):
            panel._on_item_clicked(panel._list.item(1))

    def test_refresh_preserves_selection(self, qtbot):
        store = _store([_robot("r1"), _robot("r2")])
        panel = DeviceListPanel(kind="robot", recipe_store=store)
        qtbot.addWidget(panel)
        panel.select_device("r2")
        panel.refresh()
        assert panel._selected_device_id() == "r2"


class TestDeviceMasterDetail:
    def test_select_builds_page_and_switches(self, qtbot):
        built = []

        def factory(device_id):
            built.append(device_id)
            w = QLabel(f"page {device_id}")
            return w

        md = DeviceMasterDetail(
            kind="robot",
            recipe_store=_store([_robot("r1")]),
            device_page_factory=factory,
        )
        qtbot.addWidget(md)
        md.select_device("r1")
        assert built == ["r1"]
        assert md._stack.currentIndex() != 0  # не заглушка

    def test_page_built_once(self, qtbot):
        built = []
        md = DeviceMasterDetail(
            kind="robot",
            recipe_store=_store([_robot("r1")]),
            device_page_factory=lambda d: (built.append(d), QWidget())[1],
        )
        qtbot.addWidget(md)
        md.select_device("r1")
        md._show_device("r1")  # повторный выбор
        assert built == ["r1"]  # фабрика вызвана один раз

    def test_removed_device_falls_back_to_placeholder(self, qtbot):
        dict_store = _DictRecipeStore(devices=[_robot("r1")])
        store = RecipeDevicesStore(dict_store)
        md = DeviceMasterDetail(kind="robot", recipe_store=store, device_page_factory=lambda d: QLabel(d))
        qtbot.addWidget(md)
        md.select_device("r1")
        assert md._stack.currentIndex() != 0
        # удаляем r1 из рецепта и refresh
        dict_store.save_raw("demo", {"devices": []})
        md.refresh()
        assert md._stack.currentIndex() == 0  # заглушка

    def test_add_requested_invokes_on_add(self, qtbot):
        called = []
        md = DeviceMasterDetail(
            kind="robot",
            recipe_store=_store([_robot("r1")]),
            device_page_factory=lambda d: QWidget(),
            on_add=lambda: called.append(True),
        )
        qtbot.addWidget(md)
        md._show_add()
        assert called == [True]  # «+ Добавить» вызвал диалог-обработчик

    def test_placeholder_text_without_active(self, qtbot):
        md = DeviceMasterDetail(kind="robot", recipe_store=_store(active=None), device_page_factory=lambda d: QWidget())
        qtbot.addWidget(md)
        assert "Активируйте рецепт" in md._placeholder.text()


class TestDeviceIoRender:
    def test_render_shows_tx_rx_registers(self):
        value = {
            "method": "modbus",
            "input": {"op": "read_holding", "reg": "0x1130", "values": [3000, 63436]},
            "output": {"op": "write_register", "reg": "0x1106", "value": 2},
        }
        status, in_text, out_text = _render_device_io(value)
        assert "0x1130" in status and "0x1106" in status
        assert "3000" in in_text and "63436" in in_text
        assert "0x1106" in out_text

    def test_render_empty_placeholders(self):
        status, in_text, out_text = _render_device_io({"input": None, "output": None})
        assert "нет чтений" in in_text
        assert "нет записей" in out_text
