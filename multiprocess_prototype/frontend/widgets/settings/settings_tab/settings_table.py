# multiprocess_prototype/frontend/widgets/settings_tab/settings_table.py
"""Обёртка AppRecipePanelWidget с поддержкой фильтрации через дерево."""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.core.qt_imports import QVBoxLayout, QWidget


class SettingsTableWrapper(QWidget):
    """Хостит app_panel и фильтрует элементы через tree.invisibleRootItem()."""

    def __init__(self, app_panel: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app_panel = app_panel

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(app_panel, 1)

    def apply_filter(
        self, text: str, category: str, sort_field: str, asc: bool
    ) -> None:
        """Фильтрует элементы дерева в app_panel._tree."""
        tree = getattr(self._app_panel, "_tree", None)
        if tree is None:
            return

        root = tree.invisibleRootItem()
        text_lower = text.lower()

        for gi in range(root.childCount()):
            group_item = root.child(gi)
            group_name = group_item.text(0)

            # Фильтр по категории на уровне группы
            if category and group_name != category:
                group_item.setHidden(True)
                continue

            visible_children = 0
            for ci in range(group_item.childCount()):
                child = group_item.child(ci)
                if not text:
                    child.setHidden(False)
                    visible_children += 1
                    continue

                # Поиск в колонках param (0) и info (2)
                col0 = child.text(0).lower()
                col2 = child.text(2).lower() if child.columnCount() > 2 else ""
                matches = text_lower in col0 or text_lower in col2
                child.setHidden(not matches)
                if matches:
                    visible_children += 1

            group_item.setHidden(visible_children == 0)
