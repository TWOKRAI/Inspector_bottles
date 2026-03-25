# -*- coding: utf-8 -*-
"""
TouchKeyboardConfig — настройки виртуальной клавиатуры для touch-ввода.

Живёт в components/base, чтобы NumericViewConfig не зависел от widgets/keyboard.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Literal, Optional


@dataclass
class TouchKeyboardConfig:
    """Когда и какую клавиатуру показывать; геометрия относительно экрана."""

    mode: Literal["off", "mini", "full"] = "off"
    """off — не показывать; mini — цифровая; full — полная (RU/EN)."""

    min_screen_height_px: Optional[int] = None
    """Если задано, клавиатура только при height экрана >= этого значения."""

    keyboard_height_fraction: float = 1.0 / 3.0
    """Доля высоты экрана под полную клавиатуру (полоса снизу)."""

    mini_width_px: int = 300
    mini_height_px: int = 250
    mini_scale: float = 1.0
    """Множитель к mini_width_px / mini_height_px (например 1.2 на крупных экранах)."""


def coerce_touch_keyboard(raw: Any) -> Optional[TouchKeyboardConfig]:
    """dict или уже TouchKeyboardConfig → TouchKeyboardConfig; иначе None."""
    if raw is None:
        return None
    if isinstance(raw, TouchKeyboardConfig):
        return raw
    if isinstance(raw, dict):
        names = {f.name for f in fields(TouchKeyboardConfig)}
        return TouchKeyboardConfig(**{k: v for k, v in raw.items() if k in names})
    return None
