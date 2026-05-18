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
    from multiprocess_prototype.frontend.app_context import AppContext
    from multiprocess_prototype.frontend.forms.field_editor import FieldEditor

from ..graph.constants import CATEGORY_COLORS

logger = logging.getLogger(__name__)


class NodeInspectorPanel(QWidget):
    """Панель параметров выбранного узла pipeline.

    Показывает: имя процесса, категория, список плагинов, параметры.
    Если RegistersManager доступен — создаёт типизированные виджеты
    через CardsFieldFactory. Иначе — QLineEdit (fallback).

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
        # Хранит и QLineEdit (fallback) и FieldEditor (cards-режим)
        self._field_editors: dict[str, Any] = {}
        # Флаг: используем типизированные виджеты из CardsFieldFactory
        self._use_cards: bool = False
        # AppContext — задаётся через set_context()
        self._ctx: AppContext | None = None
        self._init_ui()

    def set_context(self, ctx: "AppContext") -> None:
        """Передать AppContext для доступа к RegistersManager."""
        self._ctx = ctx

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Placeholder
        self._placeholder = QLabel("Выберите узел")
        self._placeholder.setObjectName("InspectorPlaceholder")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._placeholder)

        # Content container (скрыт когда нет выбора)
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)

        # Заголовок: имя процесса
        self._title = QLabel()
        self._title.setObjectName("InspectorTitle")
        content_layout.addWidget(self._title)

        # Badge: категория
        self._category_badge = QLabel()
        self._category_badge.setObjectName("InspectorCategoryBadge")
        content_layout.addWidget(self._category_badge)

        # Разделитель
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("InspectorDivider")
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

        Если AppContext + RegistersManager доступны — создаёт типизированные
        виджеты через CardsFieldFactory. Иначе fallback на QLineEdit.

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
            self._category_badge.setStyleSheet(f"background-color: {color}; color: #fff;")

            # Очистить параметры
            self._clear_params()

            # Плагины
            if plugins:
                for p in plugins:
                    pname = p.get("plugin_name", "") if isinstance(p, dict) else str(p)
                    label = QLabel(pname)
                    label.setProperty("role", "plugin-name")
                    self._params_layout.addRow(label)

            # Попытаться получить FieldInfo из RegistersManager
            fields_used = self._try_build_cards_editors(process_name, params)
            self._use_cards = bool(fields_used)

            # Fallback: QLineEdit если CardsFieldFactory не применился
            if not self._use_cards and params:
                self._build_lineedit_editors(params)

        finally:
            self._suppress_changes = False

    def _try_build_cards_editors(
        self,
        process_name: str,
        params: dict[str, Any] | None,
    ) -> bool:
        """Попытаться создать типизированные виджеты через CardsFieldFactory.

        Returns:
            True если виджеты успешно созданы, False — нужен fallback.
        """
        if self._ctx is None:
            return False

        rm = self._ctx.registers_manager()
        if rm is None:
            return False

        # Получить FieldInfo из RegistersManager по имени процесса
        fields = rm.get_fields(process_name)
        if not fields:
            return False

        from multiprocess_prototype.frontend.forms.factory import CardsFieldFactory

        # Получить form_ctx для binding-aware editors (plugin-bound узлы pipeline).
        # Если AppContext не содержит RM/ActionBus — form_ctx=None → legacy путь.
        form_ctx = self._ctx.form_context()

        for field_info in fields:
            editor = CardsFieldFactory.create(
                field_info,
                parent=self._params_widget,
                form_ctx=form_ctx,
            )

            # Установить значение из params если передан
            if params and field_info.field_name in params:
                try:
                    editor.setter(params[field_info.field_name])
                except Exception:
                    logger.debug(
                        "Не удалось установить значение '%s' для поля '%s'",
                        params[field_info.field_name],
                        field_info.field_name,
                    )

            # Подключить сигнал изменения если есть
            if editor.change_signal is not None:
                fn = field_info.field_name
                editor.change_signal.connect(lambda *_args, _fn=fn, _ed=editor: self._on_field_editor_changed(_fn, _ed))

            self._field_editors[field_info.field_name] = editor
            self._params_layout.addRow(editor.label, editor.widget)

        return True

    def _build_lineedit_editors(self, params: dict[str, Any]) -> None:
        """Создать QLineEdit-редакторы (fallback если CardsFieldFactory недоступен)."""
        for field_name, value in params.items():
            editor = QLineEdit(str(value))
            editor.setProperty("field_name", field_name)
            editor.editingFinished.connect(lambda fn=field_name, ed=editor: self._on_field_edited(fn, ed))
            self._field_editors[field_name] = editor
            self._params_layout.addRow(field_name, editor)

    def clear(self) -> None:
        """Очистить inspector (показать placeholder)."""
        self._current_process = ""
        self._placeholder.setVisible(True)
        self._content.setVisible(False)
        self._clear_params()

    def update_field(self, field_name: str, value: Any) -> None:
        """Обновить значение поля programmatically (undo/redo).

        Использует signal suppression чтобы не тригерить field_changed.
        Работает для обоих типов редакторов: FieldEditor и QLineEdit.
        """
        self._suppress_changes = True
        try:
            editor = self._field_editors.get(field_name)
            if editor is None:
                return

            if isinstance(editor, QLineEdit):
                # Fallback-режим: QLineEdit
                editor.setText(str(value))
            else:
                # Cards-режим: FieldEditor с setter
                try:
                    editor.setter(value)
                except Exception:
                    logger.warning(
                        "update_field: не удалось установить значение '%s' для поля '%s'",
                        value,
                        field_name,
                    )
        finally:
            self._suppress_changes = False

    @property
    def current_process(self) -> str:
        """Имя текущего отображаемого процесса."""
        return self._current_process

    def _on_field_edited(self, field_name: str, editor: QLineEdit) -> None:
        """Обработчик изменения поля пользователем (QLineEdit fallback)."""
        if self._suppress_changes:
            return
        value = editor.text()
        self.field_changed.emit(self._current_process, field_name, value)

    def _on_field_editor_changed(self, field_name: str, editor: "FieldEditor") -> None:
        """Обработчик изменения поля через FieldEditor (cards-режим).

        Args:
            field_name: имя поля.
            editor: FieldEditor, у которого сработал change_signal.
        """
        if self._suppress_changes:
            return
        value = editor.getter()
        self.field_changed.emit(self._current_process, field_name, value)

    def _clear_params(self) -> None:
        """Удалить все виджеты параметров.

        Для FieldEditor: отключаем change_signal перед удалением
        чтобы избежать утечек сигналов при переключении нод.
        """
        for field_name, editor in self._field_editors.items():
            if not isinstance(editor, QLineEdit):
                # FieldEditor — отключаем change_signal
                try:
                    if editor.change_signal is not None:
                        editor.change_signal.disconnect()
                except (RuntimeError, TypeError):
                    pass  # Уже отключён или C++ объект удалён

        self._field_editors.clear()
        self._use_cards = False

        while self._params_layout.count():
            item = self._params_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
