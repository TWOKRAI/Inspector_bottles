"""Утилита Qt thread safety для debug-режима.
Активация: установить переменную окружения INSPECTOR_DEBUG_QT=1.
В prod (_DEBUG_QT=False) декоратор — zero-overhead wrapper.
"""

import os
import functools
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

_DEBUG_QT: bool = os.environ.get("INSPECTOR_DEBUG_QT", "0") == "1"


def ensure_main_thread(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if _DEBUG_QT:
            app = QApplication.instance()
            if app is not None:
                assert QThread.currentThread() == app.thread(), (
                    f"{func.__qualname__} вызван не из main thread! "
                    f"Текущий поток: {QThread.currentThread()}"
                )
        return func(*args, **kwargs)
    return wrapper


__all__ = ["ensure_main_thread"]
