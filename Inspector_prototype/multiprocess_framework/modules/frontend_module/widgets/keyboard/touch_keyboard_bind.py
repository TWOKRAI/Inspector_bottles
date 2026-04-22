# frontend_module/widgets/keyboard/touch_keyboard_bind.py
"""Подключение touch-клавиатуры к QLineEdit из глобального dict конфига (Dict at Boundary)."""

from __future__ import annotations

from typing import Any

from frontend_module.components.base.touch_keyboard_config import coerce_touch_keyboard
from frontend_module.core.qt_imports import QLineEdit, QWidget
from frontend_module.widgets.keyboard.touch_keyboard import install_touch_keyboard_on_line_edit


def merge_touch_keyboard_dicts(*parts: Any | None) -> Any | None:
    """
    Склеить несколько dict (override правее перекрывает ключи левее).

    Удобно: глобальный ``FrontendConfig.touch_keyboard`` + секция вкладки / компонента.
    """
    out: dict[str, Any] = {}
    for p in parts:
        if isinstance(p, dict):
            out = {**out, **p}
    return out if out else None


def bind_touch_keyboard_line_edit(
    host: QWidget,
    line_edit: QLineEdit,
    touch_keyboard: Any | None,
) -> None:
    """
    Если ``touch_keyboard`` после coerce не None и не mode=off — вешает открытие клавиатуры по клику.

    ``host`` — родитель для ``QObject`` фильтра (обычно панель с полем).
    """
    cfg = coerce_touch_keyboard(touch_keyboard)
    if cfg is None:
        return
    install_touch_keyboard_on_line_edit(
        host,
        line_edit,
        cfg,
        lambda: line_edit.clearFocus(),
    )
