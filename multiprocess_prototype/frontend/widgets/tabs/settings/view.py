# -*- coding: utf-8 -*-
"""SettingsView — Protocol вью для SettingsPresenter.

После миграции SettingsTab на BaseTreeNavTab presenter вызывает только
методы навигации (set_content_index, set_action_index, select_tree_key,
create_lazy_section), унаследованные от TabViewProtocol.

Методы add_*_page, build_nav_tree, set_undo_enabled/set_redo_enabled —
удалены: BaseTreeNavTab инкапсулирует их.

См. ADR-126.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from multiprocess_framework.modules.frontend_module.widgets.tabs import TabViewProtocol


@runtime_checkable
class SettingsView(TabViewProtocol, Protocol):
    """Protocol вью для SettingsPresenter.

    Реализует SettingsTab (через BaseTreeNavTab) — presenter работает
    только через этот интерфейс.
    """

    # ------------------------------------------------------------------
    # Стек контента и действий
    # ------------------------------------------------------------------

    def set_content_index(self, index: int) -> None:
        """Переключить content stack на указанный индекс."""
        ...

    def set_action_index(self, index: int) -> None:
        """Переключить action stack на указанный индекс."""
        ...

    # ------------------------------------------------------------------
    # Навигационное дерево
    # ------------------------------------------------------------------

    def select_tree_key(self, key: str) -> None:
        """Выбрать элемент nav-дерева по ключу."""
        ...

    def create_lazy_section(self, key: str) -> None:
        """Создать ленивую секцию по ключу (вызывается presenter'ом)."""
        ...
