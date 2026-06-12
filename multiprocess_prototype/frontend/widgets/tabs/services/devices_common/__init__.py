# -*- coding: utf-8 -*-
"""Общие компоненты для вкладок устройств (combo, editor, presenter).

Реестр устройств живёт в always-on процессе ``devices`` (DeviceHubPlugin).
Компоненты этого пакета — переиспользуемые UI-блоки для вкладок «Робот»,
«ПЧ», «Камеры» и др.
"""

from .add_page import AddDevicePage
from .combo import DeviceComboController
from .crud_actions import DeviceCrudActions
from .device_form import DeviceFormWidget
from .device_list_panel import DeviceListPanel
from .editor_dialog import DeviceEditorDialog
from .master_detail import DeviceDetailPage, DeviceMasterDetail
from .presenter import DevicesPresenter
from .recipe_devices import RecipeDevicesError, RecipeDevicesStore

__all__ = [
    "AddDevicePage",
    "DeviceComboController",
    "DeviceCrudActions",
    "DeviceDetailPage",
    "DeviceEditorDialog",
    "DeviceFormWidget",
    "DeviceListPanel",
    "DeviceMasterDetail",
    "DevicesPresenter",
    "RecipeDevicesError",
    "RecipeDevicesStore",
]
