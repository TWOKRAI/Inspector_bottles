# -*- coding: utf-8 -*-
"""Секция «Робот Delta» вкладки Services — ручное управление роботом.

Фаза 4 device-hub: команды → процесс ``devices`` (DeviceHubPlugin);
группа ПЧ вынесена в отдельную вкладку; DeviceComboController (kind=robot).
"""

from .section import build_robot_section

__all__ = ["build_robot_section"]
