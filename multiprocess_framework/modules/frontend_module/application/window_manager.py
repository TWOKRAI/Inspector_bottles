# -*- coding: utf-8 -*-
"""
WindowManager — управление жизненным циклом окон.

Реестр окон, показ/скрытие, fullscreen, cursor, access_level.
Приложение регистрирует окна через register().
Поддерживает IConfig (dot-notation) и Dict для обратной совместимости.
"""
from __future__ import annotations

import warnings
from typing import Any, Callable, Dict, Optional, Union

from multiprocess_framework.modules.frontend_module.core.qt_imports import QCursor, QObject, Qt, QWidget, Signal
from multiprocess_framework.modules.frontend_module.core.window_registry import WindowEntry, WindowRegistry
from multiprocess_framework.modules.frontend_module.managers.access_context import AccessContext


def _config_get(config: Any, key: str, default: Any = None) -> Any:
    """Получить значение по dot-notation. Поддерживает IConfig и Dict."""
    if config is None:
        return default
    if hasattr(config, "get") and not isinstance(config, dict):
        return config.get(key, default)
    if isinstance(config, dict):
        parts = key.split(".")
        obj: Any = config
        for p in parts:
            if isinstance(obj, dict):
                obj = obj.get(p)
            else:
                return default
            if obj is None:
                return default
        return obj if obj is not None else default
    return default


class WindowManager(QObject):
    """
    Управление окнами приложения.
    Сигналы: window_shown, window_hidden, update_access_context.
    """
    window_shown = Signal(str)
    window_hidden = Signal(str)
    # PR1-Group-C: новый сигнал для RBAC — передаёт AccessContext всем подписчикам
    update_access_context = Signal(object)

    def __init__(
            self,
            config: Union[Dict[str, Any], Any],
            registers_manager: Any,
            data_manager: Optional[Any] = None,
            parent=None,
    ):
        super().__init__(parent)
        self._config = config  # IConfig или Dict
        self._registers = registers_manager
        self._data_manager = data_manager
        self._registry = WindowRegistry()
        self._current_window: Optional[str] = None
        self._access_level: int = 0
        # PR1-Group-C: хранение текущего AccessContext
        self._access_context: AccessContext = AccessContext()

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
        limit = _config_get(self._config, "window.limit_fullscreen_resolution", False)
        max_w = _config_get(self._config, "window.fullscreen_max_width", 1920)
        max_h = _config_get(self._config, "window.fullscreen_max_height", 1080)
        min_w = _config_get(self._config, "window.window_min_width", 800)
        min_h = _config_get(self._config, "window.window_min_height", 600)

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

    def set_access_context(self, ctx: AccessContext) -> None:
        """
        Установить новый контекст доступа и распространить на все окна.

        Эмитирует сигнал update_access_context(ctx).
        Окна с методом update_access_context(ctx) получат новый контекст;
        окна со старым методом update_access_level(level) получат ctx.level
        для обратной совместимости.
        """
        self._access_context = ctx
        self._access_level = ctx.level

        def apply(window: QWidget) -> None:
            # Новый путь: окно поддерживает AccessContext
            if hasattr(window, "update_access_context"):
                window.update_access_context(ctx)
            # Legacy fallback: окно знает только числовой level
            elif hasattr(window, "update_access_level"):
                window.update_access_level(ctx.level)

        names = self._registry.filter_names(needs_access_level=True, created_only=True)
        self._registry.apply(names, apply)
        self.update_access_context.emit(ctx)

    def set_access_level(self, level: int) -> None:
        """
        Deprecated: используйте set_access_context(AccessContext(level=...)) вместо этого.

        Сохранён для обратной совместимости. Внутри оборачивает level в AccessContext
        и делегирует в set_access_context().
        """
        warnings.warn(
            "WindowManager.set_access_level(int) is deprecated, "
            "use set_access_context(AccessContext(level=...)) instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.set_access_context(AccessContext(level=level))

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
        if hasattr(self._config, "update"):
            self._config.update(config)
        elif isinstance(self._config, dict):
            self._config.update(config)
        names = self._registry.created_names()
        for name in names:
            w = self._registry.get(name)
            if w and hasattr(w, "apply_config"):
                w.apply_config(config)
