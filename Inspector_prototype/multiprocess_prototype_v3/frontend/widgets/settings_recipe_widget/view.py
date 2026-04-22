# multiprocess_prototype_v3/frontend/widgets/settings_recipe_widget/view.py
"""Протокол вида для AppRecipePresenter."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class AppRecipePanelViewProtocol(Protocol):
    """Методы виджета app-рецептов, используемые презентером."""

    def parse_slot(self) -> int:
        """Индекс слота рецепта из UI (с ограничениями схемы)."""
        ...

    def refresh_table_rows(self) -> None:
        """Полностью обновить дерево из презентера."""
        ...

    def set_leaf_value_text(self, group_id: str, field_id: str, text: str) -> None:
        """Текст колонки value у листа (откат/синхронизация)."""
        ...
