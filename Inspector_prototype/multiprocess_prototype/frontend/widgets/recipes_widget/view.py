# multiprocess_prototype/frontend/widgets/recipes_widget/view.py
"""Протокол вида для RegisterRecipePresenter."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class RegisterRecipePanelViewProtocol(Protocol):
    """Методы виджета регистровых рецептов, используемые презентером."""

    def parse_slot(self) -> int:
        """Индекс слота рецепта регистров."""
        ...

    def refresh_table_rows(self) -> None:
        """Обновить дерево из build_rows."""
        ...

    def set_leaf_value_text(self, group_id: str, field_id: str, text: str) -> None:
        """Текст колонки value у листа (откат/синхронизация после set_field_value)."""
        ...
