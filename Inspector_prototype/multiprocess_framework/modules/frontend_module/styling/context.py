# -*- coding: utf-8 -*-
"""Поиск StyleSession у предков (атрибут `style_session`)."""
from __future__ import annotations

from typing import Any, Optional


def get_style_session_from_parent(widget: Any, max_depth: int = 12) -> Optional[Any]:
    """
    Найти `StyleSession`: сначала у верхнего окна (`window()`), затем вверх по `parent()`.

    В QMainWindow родитель центрального виджета — не само QMainWindow, а внутренний
    контейнер; без `window()` сессия не находилась.
    """
    if widget is None:
        return None
    top = widget.window() if hasattr(widget, "window") else None
    if top is not None:
        ss = getattr(top, "style_session", None)
        if ss is not None and hasattr(ss, "register"):
            return ss
    current = widget.parent() if hasattr(widget, "parent") else None
    if callable(current):
        current = current()
    depth = 0
    while current is not None and depth < max_depth:
        ss = getattr(current, "style_session", None)
        if ss is not None and hasattr(ss, "register"):
            return ss
        nxt = getattr(current, "parent", None)
        current = nxt() if callable(nxt) else None
        depth += 1
    return None
