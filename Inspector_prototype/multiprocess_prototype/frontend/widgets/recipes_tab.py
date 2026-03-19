# multiprocess_prototype/frontend/widgets/recipes_tab.py
"""
RecipesTabWidget — вкладка рецептов.

Заглушка: QLabel. Позже — таблица из полей с recipe_field.
"""

from typing import Any, Optional

from frontend_module.components import BaseTab
from frontend_module.core.qt_imports import QLabel, QVBoxLayout, QWidget, Qt


class RecipesTabWidget(BaseTab):
    """Вкладка рецептов. Заглушка с QLabel."""

    def __init__(
        self,
        *,
        registers_manager: Optional[Any] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._registers_manager = registers_manager
        layout = QVBoxLayout(self)
        lbl = QLabel("Рецепты")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("font-size: 18px; color: #555;")
        layout.addWidget(lbl)
        layout.addStretch()
