# -*- coding: utf-8 -*-
"""Общие компоненты для вкладок устройств (combo, editor, presenter).

Реестр устройств живёт в always-on процессе ``devices`` (DeviceHubPlugin).
Компоненты этого пакета — переиспользуемые UI-блоки для вкладок «Робот»,
«ПЧ», «Камеры» и др.
"""

from .combo import DeviceComboController
from .crud_actions import DeviceCrudActions
from .device_list_panel import DeviceListPanel
from .editor_dialog import DeviceEditorDialog
from .master_detail import DeviceDetailPage, DeviceMasterDetail
from .presenter import DevicesPresenter
from .recipe_devices import RecipeDevicesError, RecipeDevicesStore

__all__ = [
    "DeviceComboController",
    "DeviceCrudActions",
    "DeviceDetailPage",
    "DeviceEditorDialog",
    "DeviceListPanel",
    "DeviceMasterDetail",
    "DevicesPresenter",
    "RecipeDevicesError",
    "RecipeDevicesStore",
]
