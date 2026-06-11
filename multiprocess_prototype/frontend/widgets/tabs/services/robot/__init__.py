# -*- coding: utf-8 -*-
"""Секция «Робот Delta» вкладки Services — ручное управление роботом и ПЧ.

Паттерн hikvision/: widget (тупой View) + presenter (IPC, без Qt) +
controller (проводка) + section (SectionSpec).
"""

from .section import build_robot_section

__all__ = ["build_robot_section"]
