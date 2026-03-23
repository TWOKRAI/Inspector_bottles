# -*- coding: utf-8 -*-
"""
RAII блокировка сигналов Qt-виджетов.

Использование: ``with block_signals(widget1, widget2): ...``
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any


@contextmanager
def block_signals(*widgets: Any):
    """Блокирует сигналы всех виджетов в блоке, восстанавливает после."""
    for w in widgets:
        if w is not None and hasattr(w, "blockSignals"):
            w.blockSignals(True)
    try:
        yield
    finally:
        for w in widgets:
            if w is not None and hasattr(w, "blockSignals"):
                w.blockSignals(False)
