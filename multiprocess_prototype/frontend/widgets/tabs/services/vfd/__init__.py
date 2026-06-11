# -*- coding: utf-8 -*-
"""Секция «ПЧ (частотный преобразователь)» вкладки Services.

Паттерн hikvision/: widget (тупой View) + presenter (IPC, без Qt) +
controller (проводка) + section (SectionSpec). Устройства — через
DeviceComboController (devices_common).
"""

from .section import build_vfd_section

__all__ = ["build_vfd_section"]
