# -*- coding: utf-8 -*-
"""
WindowManager — управление жизненным циклом окон.

Реестр окон, показ/скрытие, fullscreen, cursor, access_level.
Приложение регистрирует окна через register().
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from frontend_module.core.qt_imports import QCursor, QObject, Qt, QWidget, pyqtSignal
from frontend_module.core.window_registry import WindowEntry, WindowRegistry


class WindowManager(QObject):
    """
    Управление окнами приложения.
    Сигналы: window_shown, window_hidden.
    """
    window_shown = pyqtSignal(str)
    window_hidden = pyqtSignal(str)

    def __init__(
            self,
            config: Dict[str, Any],
            registers_manager: Any,
            data_manager: Optional[Any] = None,
            parent=None,
    ):
        super().__init__(parent)
        self._config = config
        self._registers = registers_manager
        self._data_manager = data_manager
        self._registry = WindowRegistry()
        self._current_window: Optional[str] = None
        self._access_level: int = 0

    def register(
        self,
        name: str,
        factory: Callable[..., QWidget],
        *,
        singleton: bool = True,
        needs_fullscreen: bool = True,
        needs_cursor: bool = True,
        needs_access_level: bool = True,
        auto_close: int = 0,
    ) -> "WindowManager":
        """Регистрация окна. Chainable."""
        self._registry.register(
            name,
            factory=factory,
            singleton=singleton,
            needs_fullscreen=needs_fullscreen,
            needs_cursor=needs_cursor,
            needs_access_level=needs_access_level,
            auto_close=auto_close,
        )
        return self

    def create(self, name: str, **kwargs: Any) -> Optional[QWidget]:
        """Создать окно по имени."""
        return self._registry.create(name, **kwargs)

    def show_initial_window(self, window_name: str = "main", **kwargs: Any) -> None:
        """Показать начальное окно."""
        self._registry.create(window_name, **kwargs)
        self._show(window_name)
        self._current_window = window_name

    def show_window(self, name: str) -> None:
        """Показать окно по имени."""
        if not self._registry.is_created(name):
            self._registry.create(name)
        self._show(name)
        self._current_window = name
        self.window_shown.emit(name)

    def hide_window(self, name: str) -> None:
        """Скрыть окно."""
        self._hide(name)

    def get_window(self, name: str) -> Optional[QWidget]:
        return self._registry.get(name)

    def get_current_window_name(self) -> Optional[str]:
        return self._current_window

    def close_all(self) -> None:
        self._registry.close_all()
        self._current_window = None

    def set_fullscreen(self, fullscreen: bool) -> None:
        """Установить fullscreen для окон с needs_fullscreen."""
        limit = self._config.get("window", {}).get("limit_fullscreen_resolution", False)
        max_w = self._config.get("window", {}).get("fullscreen_max_width", 1920)
        max_h = self._config.get("window", {}).get("fullscreen_max_height", 1080)
        min_w = self._config.get("window", {}).get("window_min_width", 800)
        min_h = self._config.get("window", {}).get("window_min_height", 600)

        def apply(window: QWidget):
            if fullscreen:
                if limit:
                    window.showNormal()
                    window.setFixedSize(max_w, max_h)
                    screen = window.screen().availableGeometry()
                    x = (screen.width() - max_w) // 2
                    y = (screen.height() - max_h) // 2
                    window.move(x, y)
                else:
                    window.showFullScreen()
            else:
                window.setFixedSize(16777215, 16777215)
                window.setMaximumSize(16777215, 16777215)
                window.setMinimumSize(min_w, min_h)
                window.showNormal()

        names = self._registry.filter_names(needs_fullscreen=True, created_only=True)
        self._registry.apply(names, apply)

    def toggle_cursor(self, visible: bool) -> None:
        cursor = QCursor(Qt.ArrowCursor) if visible else QCursor(Qt.BlankCursor)
        names = self._registry.filter_names(needs_cursor=True, created_only=True)
        self._registry.apply(names, lambda w: w.setCursor(cursor))

    def set_access_level(self, level: int) -> None:
        self._access_level = level

        def apply(window: QWidget):
            if hasattr(window, "update_access_level"):
                window.update_access_level(level)

        names = self._registry.filter_names(needs_access_level=True, created_only=True)
        self._registry.apply(names, apply)

    def _show(self, name: str) -> None:
        window = self._registry.get(name)
        if window:
            window.show()
            window.raise_()
            window.activateWindow()

    def _hide(self, name: str) -> None:
        window = self._registry.get(name)
        if window:
            window.hide()
            self.window_hidden.emit(name)

    def update_config(self, config: Dict[str, Any]) -> None:
        """
        Обновить конфиг (hot-reload).
        Окна с методом apply_config получат новый конфиг.
        """
        self._config.update(config)
        names = self._registry.created_names()
        for name in names:
            w = self._registry.get(name)
            if w and hasattr(w, "apply_config"):
                w.apply_config(config)
