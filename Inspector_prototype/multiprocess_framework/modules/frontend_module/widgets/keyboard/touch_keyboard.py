# -*- coding: utf-8 -*-
"""
Touch keyboard — показ виртуальной клавиатуры для QLineEdit (slider, spinbox, таблицы).

Использует ``TouchKeyboardConfig`` из ``components.base``; виджеты клавиатуры — локально в этом пакете.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from PyQt5.QtCore import QEvent, QObject, Qt

from frontend_module.components.base.touch_keyboard_config import TouchKeyboardConfig
from frontend_module.core.qt_imports import QApplication, QLineEdit, QWidget

from .keyboard import VirtualKeyboard
from .keyboard_mini import VirtualKeyboardMini

_active_keyboard: Optional[QWidget] = None


def _close_active_keyboard() -> None:
    global _active_keyboard
    if _active_keyboard is None:
        return
    w = _active_keyboard
    _active_keyboard = None
    try:
        w.close()
    except Exception:
        pass


def _register_active_keyboard(w: QWidget) -> None:
    global _active_keyboard
    _close_active_keyboard()
    _active_keyboard = w

    def _clear() -> None:
        global _active_keyboard
        if _active_keyboard is w:
            _active_keyboard = None

    w.destroyed.connect(_clear)


def should_show(
    config: TouchKeyboardConfig,
    *,
    screen_height_px: Optional[int] = None,
) -> bool:
    """Показывать ли клавиатуру: режим не off и опционально порог по высоте экрана."""
    if config.mode == "off":
        return False
    h = screen_height_px
    if h is None:
        app = QApplication.instance()
        if app is None:
            return False
        scr = app.primaryScreen()
        if scr is None:
            return False
        h = scr.geometry().height()
    if config.min_screen_height_px is not None and h < config.min_screen_height_px:
        return False
    return True


def show_for_line_edit(
    parent: Optional[QWidget],
    line_edit: QLineEdit,
    config: TouchKeyboardConfig,
    on_enter: Callable[[], None],
    *,
    keyboard_factory: Optional[Callable[[], Any]] = None,
) -> None:
    """
    Открыть клавиатуру для ``line_edit``.

    ``on_enter`` — по Enter на полной клавиатуре или мини (мини также закрывается).
    Перед открытием закрывается предыдущий экземпляр touch-клавиатуры (если был).
    """
    if not should_show(config):
        return

    _close_active_keyboard()

    if keyboard_factory is not None:
        kb = keyboard_factory()
        kb.input = line_edit
        kb.enter = on_enter
        if hasattr(kb, "show"):
            kb.show()
        if hasattr(kb, "raise_"):
            kb.raise_()
        if hasattr(kb, "activateWindow"):
            kb.activateWindow()
        _register_active_keyboard(kb)
        return

    if config.mode == "mini":
        kb = VirtualKeyboardMini(parent)
        kb.input = line_edit
        kb.enter = on_enter
        kb.apply_geometry_for_touch(
            config.mini_width_px,
            config.mini_height_px,
            config.mini_scale,
        )
        kb.show()
        kb.raise_()
        kb.activateWindow()
        _register_active_keyboard(kb)
        return

    if config.mode == "full":
        kb = VirtualKeyboard()
        kb.input = line_edit
        kb.enter = on_enter
        kb.apply_geometry_for_touch(config.keyboard_height_fraction)
        kb.show()
        kb.raise_()
        kb.activateWindow()
        _register_active_keyboard(kb)


class LineEditTouchKeyboardFilter(QObject):
    """Фильтр: по ЛКМ на ``QLineEdit`` открывает touch-клавиатуру."""

    def __init__(
        self,
        host: QWidget,
        line_edit: QLineEdit,
        config: TouchKeyboardConfig,
        on_enter: Callable[[], None],
        keyboard_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        super().__init__(host)
        self._line_edit = line_edit
        self._config = config
        self._on_enter = on_enter
        self._keyboard_factory = keyboard_factory

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if obj is not self._line_edit:
            return False
        et = event.type()
        if et == QEvent.MouseButtonPress:
            if event.button() != Qt.LeftButton:
                return False
        elif et == QEvent.TouchBegin:
            pass
        else:
            return False
        show_for_line_edit(
            self.parent() if isinstance(self.parent(), QWidget) else None,
            self._line_edit,
            self._config,
            self._on_enter,
            keyboard_factory=self._keyboard_factory,
        )
        return False


def install_touch_keyboard_on_line_edit(
    host: QWidget,
    line_edit: QLineEdit,
    config: Optional[TouchKeyboardConfig],
    on_enter: Callable[[], None],
    *,
    keyboard_factory: Optional[Callable[[], Any]] = None,
) -> None:
    """
    Подключить открытие клавиатуры по клику на поле ввода.

    Если задан только ``touch_keyboard_factory`` (legacy), используется режим mini
    для проверки ``should_show``; при ``config.mode == "off"`` фабрика всё равно вызывается.
    """
    if config is None and keyboard_factory is None:
        return
    if keyboard_factory is not None:
        eff: TouchKeyboardConfig
        if config is None:
            eff = TouchKeyboardConfig(mode="mini")
        elif config.mode == "off":
            eff = TouchKeyboardConfig(mode="mini")
        else:
            eff = config
    else:
        if config is None or config.mode == "off":
            return
        eff = config
    filt = LineEditTouchKeyboardFilter(
        host, line_edit, eff, on_enter, keyboard_factory=keyboard_factory
    )
    line_edit.installEventFilter(filt)
    setattr(host, "_touch_keyboard_filter", filt)
    # Иначе на части панелей TouchBegin не доходит до QLineEdit (только синтетическая мышь).
    line_edit.setAttribute(Qt.WA_AcceptTouchEvents, True)
