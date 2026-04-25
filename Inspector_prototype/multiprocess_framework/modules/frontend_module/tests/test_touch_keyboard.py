# -*- coding: utf-8 -*-
"""Тесты touch-клавиатуры (без Qt-приложения — только логика конфига)."""
from __future__ import annotations

from multiprocess_framework.modules.frontend_module.components.base.touch_keyboard_config import (
    TouchKeyboardConfig,
    coerce_touch_keyboard,
)
from multiprocess_framework.modules.frontend_module.widgets.keyboard.touch_keyboard import should_show


def test_should_show_off() -> None:
    assert not should_show(TouchKeyboardConfig(mode="off"), screen_height_px=1080)


def test_should_show_mini_no_threshold() -> None:
    assert should_show(TouchKeyboardConfig(mode="mini"), screen_height_px=1080)


def test_should_show_respects_min_screen_height() -> None:
    c = TouchKeyboardConfig(mode="mini", min_screen_height_px=1000)
    assert should_show(c, screen_height_px=1080)
    assert not should_show(c, screen_height_px=800)


def test_coerce_touch_keyboard_from_dict() -> None:
    c = coerce_touch_keyboard(
        {"mode": "full", "min_screen_height_px": 900, "keyboard_height_fraction": 0.25}
    )
    assert c is not None
    assert c.mode == "full"
    assert c.min_screen_height_px == 900
    assert c.keyboard_height_fraction == 0.25


def test_coerce_touch_keyboard_none() -> None:
    assert coerce_touch_keyboard(None) is None
