# multiprocess_prototype/frontend/widgets/recipes_tab/widget.py
"""
RecipesTabWidget — вкладка рецептов.

Заглушка: QLabel. Позже — таблица из полей с recipe_field.
"""

from typing import Any, Optional, Union

from frontend_module.components import BaseTab
from frontend_module.core.qt_imports import QLabel, QVBoxLayout, QWidget, Qt

from .config import RecipesTabConfig


class RecipesTabWidget(BaseTab):
    """Вкладка рецептов. Заглушка с QLabel."""

    def __init__(
        self,
        *,
        registers_manager: Optional[Any] = None,
        ui: Optional[Union[RecipesTabConfig, dict]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._registers_manager = registers_manager
        self._ui = (
            ui
            if isinstance(ui, RecipesTabConfig)
            else RecipesTabConfig.model_validate(ui or {})
        )
        layout = QVBoxLayout(self)
        lbl = QLabel(self._ui.stub_caption)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(self._ui.stub_label_style)
        layout.addWidget(lbl)
        layout.addStretch()
