# -*- coding: utf-8 -*-
"""IDisplaysView — Protocol для DisplaysTab (MVP, recipe-scoped).

Определяет контракт между DisplaysPresenter и DisplaysTab.
DisplaysTab реализует этот Protocol через structural subtyping
(не наследование) — ``isinstance(tab, IDisplaysView)`` → True.

Task 5.2: get_form_data возвращает расширенный dict с render-полями
(position, fit, scale, rotate, flip, crop). show_entry заполняет
обе секции формы (базовые + параметры отображения).

Refs: plans/displays-in-recipe/plan.md Task 5.2
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec


@runtime_checkable
class IDisplaysView(Protocol):
    """Контракт вида для таба дисплеев.

    Presenter вызывает эти методы для обновления UI.
    View никогда не вызывает бизнес-логику напрямую — только через presenter.
    """

    def refresh_list(self, specs: "list[DisplaySpec]") -> None:
        """Перестроить nav-список по новым записям реестра.

        Args:
            specs: текущий список ``DisplaySpec`` из store.
        """
        ...

    def show_entry(self, spec: "DisplaySpec | None") -> None:
        """Заполнить форму данными записи или очистить при None.

        Args:
            spec: спецификация дисплея или None для сброса формы.
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
            dict с ключами:
              Базовые: id (str), name (str), width (int), height (int),
                       format (str), fps_limit (float), ring_buffer_blocks (int).
              Render:  position (dict {x,y}), fit (str), scale (int),
                       rotate (int), flip (str), crop (dict {x,y,w,h} | None).
        """
        ...

    def show_error(self, message: str) -> None:
        """Показать пользователю сообщение об ошибке.

        Args:
            message: текст ошибки для отображения в QMessageBox.
        """
        ...
