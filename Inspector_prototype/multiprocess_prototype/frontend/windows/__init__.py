# multiprocess_prototype/frontend/windows/__init__.py
"""Окна frontend (feature-пакеты: main_window, loading, …)."""

from .loading import LoadingWindowConfig
from .main_window import MainWindow

__all__ = ["MainWindow", "LoadingWindowConfig"]
