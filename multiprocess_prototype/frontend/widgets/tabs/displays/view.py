# -*- coding: utf-8 -*-
"""IDisplaysView — Protocol для DisplaysTab (MVP).

Определяет контракт между DisplaysPresenter и DisplaysTab.
DisplaysTab реализует этот Protocol через structural subtyping
(не наследование) — ``isinstance(tab, IDisplaysView)`` → True.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from multiprocess_framework.modules.display_module import DisplayEntry


@runtime_checkable
class IDisplaysView(Protocol):
    """Контракт вида для таба дисплеев.

    Presenter вызывает эти методы для обновления UI.
    View никогда не вызывает бизнес-логику напрямую — только через presenter.
    """

    def refresh_list(self, entries: "list[DisplayEntry]") -> None:
        """Перестроить nav-список по новым записям реестра.

        Args:
            entries: текущий список ``DisplayEntry`` из реестра.
        """
        ...

    def show_entry(self, entry: "DisplayEntry | None") -> None:
        """Заполнить форму данными записи или очистить при None.

        Args:
            entry: запись дисплея или None для сброса формы.
        """
        ...

    def set_buttons_state(self, has_selection: bool) -> None:
        """Включить/выключить кнопки мутации в зависимости от выбора.

        Args:
            has_selection: True — запись выбрана, кнопки активны.
        """
        ...

    def get_form_data(self) -> dict:
        """Собрать текущие данные формы в словарь.

        Returns:
            dict с ключами: id (str), name (str), width (int), height (int),
            format (str), fps_limit (float), ring_buffer_blocks (int).
        """
        ...

    def show_error(self, message: str) -> None:
        """Показать пользователю сообщение об ошибке.

        Args:
            message: текст ошибки для отображения в QMessageBox.
        """
        ...
