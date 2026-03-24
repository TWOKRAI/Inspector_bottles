# -*- coding: utf-8 -*-
"""Тонкая обёртка над QWidget.setStyleSheet (единая точка применения QSS)."""
from __future__ import annotations

from frontend_module.core.qt_imports import QWidget


def apply_stylesheet(widget: QWidget, qss: str) -> None:
    widget.setStyleSheet(qss)
