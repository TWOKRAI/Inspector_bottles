# multiprocess_prototype/frontend/widgets/recipes_tab/widget.py
"""
RecipesTabWidget — вкладка рецептов.

Заглушка: QLabel. Позже — таблица из полей с recipe_field.

Конфиг через coerce_schema_config. registers_manager — IRegistersManagerGui
для единообразия (пока не используется).
"""

from __future__ import annotations

from typing import Optional, Union

from frontend_module.components import BaseTab
from frontend_module.core.qt_imports import QLabel, QVBoxLayout, QWidget, Qt
from frontend_module.core.schema_config import coerce_schema_config
from frontend_module.interfaces import IRegistersManagerGui

from .schemas import RecipesTabConfig


class RecipesTabWidget(BaseTab):
    """Вкладка рецептов. Заглушка с QLabel."""

    def __init__(
        self,
        *,
        registers_manager: Optional[IRegistersManagerGui] = None,
        ui: Optional[Union[RecipesTabConfig, dict]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._registers_manager = registers_manager
        self._ui = coerce_schema_config(ui, RecipesTabConfig)
        self._init_ui()

    @property
    def registers_manager(self) -> Optional[IRegistersManagerGui]:
        return self._registers_manager

    def _init_ui(self) -> None:
        """Заглушка: централизованный QLabel с stub_caption и stub_label_style."""
        layout = QVBoxLayout(self)
        lbl = QLabel(self._ui.stub_caption)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(self._ui.stub_label_style)
        layout.addWidget(lbl)
        layout.addStretch()
