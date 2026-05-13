# -*- coding: utf-8 -*-
"""
SectionProtocol — единый контракт секции для вкладок с tree-навигацией.

Секция — логическая единица контента внутри таба (например, «Настройки системы»,
«Оформление», «История»). Presenter таба работает с секциями через этот Protocol,
не зная их конкретных реализаций.

Использование:
    class MySection:
        @property
        def key(self) -> str: return "my_section"
        @property
        def title(self) -> str: return "Моя секция"
        def widget(self) -> QWidget: return self._widget
        def action_buttons(self) -> list[QWidget]: return [self._btn]
        def on_activated(self) -> None: ...
        def on_deactivated(self) -> None: ...
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


@runtime_checkable
class SectionProtocol(Protocol):
    """Контракт секции для вкладок с tree-навигацией.

    Атрибуты:
        key:   уникальный строковый идентификатор (для маппинга в nav-tree и content stack)
        title: отображаемое название (для UI)

    Методы:
        widget():          корневой QWidget секции
        action_buttons():  список кнопок для action-колонки (пустой если нет)
        on_activated():    вызывается при переключении на эту секцию
        on_deactivated():  вызывается при уходе с этой секции
    """

    @property
    def key(self) -> str: ...

    @property
    def title(self) -> str: ...

    def widget(self) -> QWidget: ...

    def action_buttons(self) -> list[QWidget]: ...

    def on_activated(self) -> None: ...

    def on_deactivated(self) -> None: ...
