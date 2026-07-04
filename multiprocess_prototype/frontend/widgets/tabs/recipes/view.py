# -*- coding: utf-8 -*-
"""IRecipesView — Protocol для RecipesTab (MVP).

Определяет контракт между RecipesPresenter и RecipesTab.
RecipesTab реализует этот Protocol через structural subtyping
(не наследование) — ``isinstance(tab, IRecipesView)`` → True.

Refs: plans/prototype-skeleton-2026-05/phase-5-recipes-manager-v2.md Task 5.6
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class IRecipesView(Protocol):
    """Контракт вида для таба рецептов.

    Presenter вызывает эти методы для обновления UI.
    View никогда не вызывает бизнес-логику напрямую — только через presenter.
    """

    def refresh_list(self, slugs: list[str]) -> None:
        """Перестроить nav-список по slug'ам рецептов.

        Args:
            slugs: актуальный список slug'ов (имён файлов без .yaml).
        """
        ...

    def show_recipe(self, slug: str | None, data: dict | None) -> None:
        """Заполнить правую панель метаданными рецепта или очистить при None.

        Args:
            slug: имя рецепта (для заголовка/выбора).
            data: dict с YAML-данными рецепта v2 или None для сброса формы.
        """
        ...

    def set_buttons_state(self, has_selection: bool, is_active: bool) -> None:
        """Включить/выключить кнопки мутации.

        Args:
            has_selection: True → Дублировать/Удалить/Активировать активны.
            is_active: True → кнопка «Сделать активным» отключена (уже активен).
        """
        ...

    def show_active_recipe(self, slug: str | None) -> None:
        """Показать, какой рецепт сейчас загружен (активен) в системе.

        Args:
            slug: slug активного рецепта или None если активного нет.
        """
        ...

    def show_error(self, message: str) -> None:
        """Показать пользователю сообщение об ошибке.

        Args:
            message: текст ошибки для отображения в QMessageBox.
        """
        ...

    def set_switch_busy(self, busy: bool) -> None:
        """Busy-состояние применения рецепта к backend (async topology.apply).

        True — переключение в полёте: кнопка «Загрузить» блокируется,
        повторный клик невозможен. False — результат получен, UI разблокирован
        (enabled-состояние кнопок восстанавливает set_buttons_state).

        Args:
            busy: True на время ожидания результата PM.
        """
        ...

    def confirm_delete(self, slug: str) -> bool:
        """Показать диалог подтверждения удаления рецепта.

        Args:
            slug: имя рецепта, который предлагается удалить.

        Returns:
            True если пользователь подтвердил удаление.
        """
        ...
