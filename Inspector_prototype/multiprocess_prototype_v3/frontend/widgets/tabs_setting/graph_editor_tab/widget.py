# multiprocess_prototype_v3/frontend/widgets/tabs_setting/graph_editor_tab/widget.py
"""GraphEditorTabWidget — вкладка с ViewSwitchWidget (табличный/графовый вид)."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QVBoxLayout, QWidget

from multiprocess_prototype_v3.frontend.widgets.graph_editor import ViewSwitchWidget


class GraphEditorTabWidget(QWidget):
    """Вкладка графового редактора цепочки обработки.

    Оборачивает ViewSwitchWidget, предоставляя доступ к графу
    через свойство view_switch.
    """

    def __init__(self, *, action_bus: Any | None = None, parent: Any | None = None) -> None:
        super().__init__(parent)
        self._action_bus = action_bus

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._view_switch = ViewSwitchWidget(parent=self)
        layout.addWidget(self._view_switch)

    @property
    def view_switch(self) -> ViewSwitchWidget:
        """Доступ к ViewSwitchWidget для set_data и управления режимом."""
        return self._view_switch
