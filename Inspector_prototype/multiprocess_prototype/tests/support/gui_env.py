# multiprocess_prototype/tests/support/gui_env.py
"""Условия запуска тестов, которым нужен Qt / «дисплей»."""

from __future__ import annotations

import os
import sys


def gui_display_available() -> bool:
    """
    True, если разумно ожидать работу QWidget (локальная сессия или headless Qt).

    - Windows: обычно есть рабочий стол (DISPLAY не используется).
    - Unix: нужен DISPLAY или QT_QPA_PLATFORM=offscreen (CI).
    """
    if sys.platform == "win32":
        return True
    if os.environ.get("QT_QPA_PLATFORM", "").strip().lower() == "offscreen":
        return True
    return bool(os.environ.get("DISPLAY", "").strip())
