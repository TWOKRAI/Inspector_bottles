"""NodeInspectorPanel — панель параметров выбранного узла pipeline."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QFrame,
    QFormLayout,
    QLineEdit,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Цвета категорий (повтор из constants — для badge)
CATEGORY_COLORS: dict[str, str] = {
    "source": "#4caf50",
    "processing": "#2196f3",
    "output": "#ff9800",
    "rendering": "#e91e63",
    "control": "#9c27b0",
    "utility": "#9e9e9e",
    "service": "#00bcd4",
}


class NodeInspectorPanel(QWidget):
    """Панель параметров выбранного узла pipeline.

    Показывает: имя процесса, категория, список плагинов, параметры.
    При отсутствии выбора — placeholder.

    Signals:
        field_changed(process_name, field_name, value): параметр изменён пользователем.
    """

    # Signal: (process_name, field_name, new_value)
    field_changed = Signal(str, str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_process: str = ""
        self._suppress_changes: bool = False
        self._field_editors: dict[str, QLineEdit] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Placeholder
        self._placeholder = QLabel("Выберите узел")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #888; font-style: italic; padding: 20px;")
        layout.addWidget(self._placeholder)

        # Content container (скрыт когда нет выбора)
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)

        # Заголовок: имя процесса
        self._title = QLabel()
        self._title.setStyleSheet("font-size: 14px; font-weight: bold; color: #fff;")
        content_layout.addWidget(self._title)

        # Badge: категория
        self._category_badge = QLabel()
        self._category_badge.setStyleSheet("font-size: 11px; padding: 2px 6px; border-radius: 3px;")
        content_layout.addWidget(self._category_badge)

        # Разделитель
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #555;")
        content_layout.addWidget(line)

        # Scroll area для параметров
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._params_widget = QWidget()
        self._params_layout = QFormLayout(self._params_widget)
        self._params_layout.setContentsMargins(0, 4, 0, 4)
        self._params_layout.setSpacing(6)
        self._scroll.setWidget(self._params_widget)
        content_layout.addWidget(self._scroll, stretch=1)

        self._content.setVisible(False)
        layout.addWidget(self._content, stretch=1)

    def show_node(
        self,
        process_name: str,
        category: str = "utility",
        plugins: list[dict[str, Any]] | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Показать параметры узла.

        Args:
            process_name: имя процесса.
            category: категория плагина.
            plugins: список плагинов [{plugin_name, ...}].
            params: dict параметров {field_name: value}.
        """
        self._suppress_changes = True
        try:
            self._current_process = process_name
            self._placeholder.setVisible(False)
            self._content.setVisible(True)

            # Заголовок
            self._title.setText(process_name)

            # Badge
            color = CATEGORY_COLORS.get(category, "#9e9e9e")
            self._category_badge.setText(category)
            self._category_badge.setStyleSheet(
                f"font-size: 11px; padding: 2px 6px; border-radius: 3px; "
                f"background-color: {color}; color: #fff;"
            )

            # Очистить параметры
            self._clear_params()

            # Плагины
            if plugins:
                for p in plugins:
                    pname = p.get("plugin_name", "") if isinstance(p, dict) else str(p)
                    label = QLabel(pname)
                    label.setStyleSheet("font-weight: bold; color: #ccc; margin-top: 4px;")
                    self._params_layout.addRow(label)

            # Параметры
            if params:
                for field_name, value in params.items():
                    editor = QLineEdit(str(value))
                    editor.setProperty("field_name", field_name)
                    editor.editingFinished.connect(
                        lambda fn=field_name, ed=editor: self._on_field_edited(fn, ed)
                    )
                    self._field_editors[field_name] = editor
                    self._params_layout.addRow(field_name, editor)
        finally:
            self._suppress_changes = False

    def clear(self) -> None:
        """Очистить inspector (показать placeholder)."""
        self._current_process = ""
        self._placeholder.setVisible(True)
        self._content.setVisible(False)
        self._clear_params()

    def update_field(self, field_name: str, value: Any) -> None:
        """Обновить значение поля programmatically (undo/redo).

        Использует signal suppression чтобы не тригерить field_changed.
        """
        self._suppress_changes = True
        try:
            editor = self._field_editors.get(field_name)
            if editor:
                editor.setText(str(value))
        finally:
            self._suppress_changes = False

    @property
    def current_process(self) -> str:
        """Имя текущего отображаемого процесса."""
        return self._current_process

    def _on_field_edited(self, field_name: str, editor: QLineEdit) -> None:
        """Обработчик изменения поля пользователем."""
        if self._suppress_changes:
            return
        value = editor.text()
        self.field_changed.emit(self._current_process, field_name, value)

    def _clear_params(self) -> None:
        """Удалить все виджеты параметров."""
        self._field_editors.clear()
        while self._params_layout.count():
            item = self._params_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
