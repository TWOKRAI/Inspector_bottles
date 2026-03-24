# multiprocess_prototype/frontend/styles/legacy_app_style.py
"""
Обратная совместимость: алиасы к встроенным стилям ``frontend_module.styling``.

QSS и дефолтные токены живут во фреймворке (рядом с виджетами/компонентами).
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from frontend_module.styling import (
    apply_ui_theme_dict,
    create_app_style_session,
    style_ids_legacy_map,
)

STYLE_IDS: Dict[str, Tuple[str, Dict[str, Any]]] = style_ids_legacy_map()

_m = STYLE_IDS
TOKENS_KEYBOARD_MINI = dict(_m["app_keyboard_mini"][1])
TOKENS_SLIDER_HANDLE = dict(_m["app_slider_handle"][1])
TOKENS_TAB_MAIN = dict(_m["app_tab_main"][1])
TOKENS_TAB_TOGGLE = dict(_m["app_tab_toggle"][1])
TOKENS_TAB_SCROLLBAR = dict(_m["app_tab_scrollbar"][1])
TOKENS_HEADER_BUTTON = dict(_m["app_header_button"][1])
TOKENS_CHECKBOX_INDICATOR = dict(_m["app_checkbox_indicator"][1])


def create_legacy_app_style_session(
    ui_theme: Dict[str, Any] | None = None,
):
    """См. :func:`frontend_module.styling.create_app_style_session`."""
    return create_app_style_session(ui_theme)
