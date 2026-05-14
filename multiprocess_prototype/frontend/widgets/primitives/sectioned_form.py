"""Форма с именованными секциями в QScrollArea.

Виджет не знает об AppContext — принимает чистые данные,
не импортирует ничего из multiprocess_prototype.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class SectionedForm(QScrollArea):
    """Форма с именованными секциями в QScrollArea.

    Каждая секция — QGroupBox с произвольным содержимым.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Контейнер, который будет скроллироваться
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(8)

        # Stretch в конце — секции «прижимаются» к верху
        self._layout.addStretch()

        self._sections: list[QGroupBox] = []

        # Настройки QScrollArea
        self.setWidget(self._container)
        self.setWidgetResizable(True)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def add_section(self, title: str, widget: QWidget) -> QGroupBox:
        """Добавить именованную секцию с виджетом.

        Args:
            title:  заголовок секции (QGroupBox title).
            widget: содержимое секции.

        Returns:
            Созданный QGroupBox.
        """
        group_box = QGroupBox(title)
        inner_layout = QVBoxLayout(group_box)
        inner_layout.setContentsMargins(4, 8, 4, 4)
        inner_layout.addWidget(widget)

        # Вставить перед последним stretch (индекс = count - 1)
        insert_pos = self._layout.count() - 1
        self._layout.insertWidget(insert_pos, group_box)

        self._sections.append(group_box)
        return group_box

    def clear_sections(self) -> None:
        """Удалить все секции."""
        for group_box in self._sections:
            self._layout.removeWidget(group_box)
            group_box.deleteLater()
        self._sections.clear()

    def section_count(self) -> int:
        """Вернуть количество секций."""
        return len(self._sections)
