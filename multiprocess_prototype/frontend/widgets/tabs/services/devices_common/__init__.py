# -*- coding: utf-8 -*-
"""Общие компоненты для вкладок устройств (combo, editor, presenter).

Реестр устройств живёт в always-on процессе ``devices`` (DeviceHubPlugin).
Компоненты этого пакета — переиспользуемые UI-блоки для вкладок «Робот»,
«ПЧ», «Камеры» и др.
"""

from .combo import DeviceComboController
from .editor_dialog import DeviceEditorDialog
from .presenter import DevicesPresenter

__all__ = ["DeviceComboController", "DeviceEditorDialog", "DevicesPresenter"]
