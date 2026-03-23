# -*- coding: utf-8 -*-
"""
Каркас MVP для вкладок: общий презентер и маркер вью.

Презентер не импортирует Qt; конкретная вкладка задаёт свой Protocol (методы вью)
и наследует TabPresenterBase, добавляя колбэки и доменную логику.

Порядок в обработчиках (см. TAB_STRUCTURE.md, PLAN_TABS_PRESENTERS_REGISTERS):
обновить регистр / состояние → при необходимости вызвать колбэк → обновить вью.
"""
from __future__ import annotations

from typing import Generic, Optional, TypeVar, Protocol

from frontend_module.interfaces import IRegistersManagerGui

TView = TypeVar("TView")
TUi = TypeVar("TUi")


class TabViewProtocol(Protocol):
    """
    Маркер: вью вкладки, с которой работает презентер без импорта Qt.

    Конкретная вкладка объявляет свой Protocol с нужными методами
    (например CameraTabView) и реализует его виджетом.
    """


class TabPresenterBase(Generic[TView, TUi]):
    """
    Общее хранение зависимостей презентера вкладки.

    Подклассы добавляют колбэки, доменное состояние и методы-обработчики.
    """

    def __init__(
        self,
        *,
        view: TView,
        rm: Optional[IRegistersManagerGui],
        ui: TUi,
    ) -> None:
        self._view = view
        self._rm = rm
        self._ui = ui
