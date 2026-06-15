"""interfaces.py — публичные типы сервиса control_panel (зависимости через них).

Тонкий фасад: переэкспорт ControlSpec/ControlType. GUI-слой и плагин зависят
от этого модуля, а не от внутренней структуры ``controls.py``.
"""

from __future__ import annotations

from Services.control_panel.controls import ControlSpec, ControlType

__all__ = ["ControlSpec", "ControlType"]
