"""RegisterView — QStackedWidget с двумя страницами (Cards / Table).

Один и тот же list[FieldInfo] рендерится в обоих режимах. Переключение
мгновенное, состояние полей синхронизируется через единый dict[str, FieldEditor]
(cards и table делят редакторы — каждое поле имеет один источник правды).

При переключении режима выполняется reparenting: editor.widget переносится
из одного контейнера в другой через setParent + размещение в layout/cell.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .factory import CardsFieldFactory
from .form_builder import _TABLE_COLUMNS, _editor_key
from .view_mode_toggle import ViewMode, ViewModeToggle

if TYPE_CHECKING:
    from PySide6.QtWidgets import QHeaderView

    from multiprocess_prototype_2.registers.field_info import FieldInfo

    from .field_editor import FieldEditor


class RegisterView(QWidget):
    """Унифицированный виджет: Cards | Table с переключателем.

    Layout:
        QVBoxLayout
          +-- QHBoxLayout (header)
          |     +-- stretch
          |     +-- ViewModeToggle
          +-- QStackedWidget
                +-- page 0: cards (QScrollArea)
                +-- page 1: table (QTableWidget)
    """

    mode_changed = Signal(str)  # ViewMode.value

    def __init__(
        self,
        fields: list[FieldInfo],
        *,
        initial_mode: ViewMode = ViewMode.CARDS,
        category_titles: dict[str, str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._fields = fields
        self._category_titles = category_titles or {}

        # 1. Создать общий набор editors — ОДИН раз
        self._editors: dict[str, FieldEditor] = {}
        for fi in fields:
            key = _editor_key(fi)
            self._editors[key] = CardsFieldFactory.create(fi)

        # 2. Группировка
        self._groups: dict[str, list[FieldInfo]] = {}
        for fi in fields:
            cat = fi.category or ""
            self._groups.setdefault(cat, []).append(fi)

        # 3. Построить структуры обоих представлений
        self._cards_widget = self._build_cards_structure()
        self._table_widget = self._build_table_structure()

        # 4. Layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Header с toggle
        header_layout = QHBoxLayout()
        header_layout.addStretch()
        self._toggle = ViewModeToggle(initial_mode=initial_mode)
        header_layout.addWidget(self._toggle)
        main_layout.addLayout(header_layout)

        # Stacked widget
        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._cards_widget)  # index 0
        self._stack.addWidget(self._table_widget)  # index 1
        main_layout.addWidget(self._stack)

        # 5. Подключить toggle
        self._toggle.mode_changed.connect(self._on_mode_changed)

        # 6. Начальный режим — разместить виджеты в нужной странице
        self._current_mode = initial_mode
        self._place_editors_in_current_mode()
        self._stack.setCurrentIndex(0 if initial_mode == ViewMode.CARDS else 1)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def editors(self) -> dict[str, FieldEditor]:
        """Словарь editors — единый для обоих режимов."""
        return self._editors

    def mode(self) -> ViewMode:
        """Текущий режим отображения."""
        return self._current_mode

    def set_mode(self, mode: ViewMode) -> None:
        """Программно переключить режим (эмитит mode_changed)."""
        self._toggle.set_mode(mode)

    # ------------------------------------------------------------------
    # Построение структур (без размещения editor.widget)
    # ------------------------------------------------------------------

    def _build_cards_structure(self) -> QScrollArea:
        """Создать скелет cards-представления (QGroupBox + QFormLayout).

        QFormLayout-строки создаются пустыми — editor.widget добавляется
        при reparenting в _place_editors_in_cards().
        """
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(4, 4, 4, 4)

        self._cards_form_layouts: dict[str, QFormLayout] = {}
        self._cards_containers: dict[str, QWidget] = {}

        for cat_key, cat_fields in self._groups.items():
            title = self._category_titles.get(cat_key, cat_key) if cat_key else ""

            if title:
                group_box = QGroupBox(title, container)
                form_layout = QFormLayout(group_box)
                container_layout.addWidget(group_box)
                self._cards_containers[cat_key] = group_box
            else:
                form_layout = QFormLayout()
                container_layout.addLayout(form_layout)
                self._cards_containers[cat_key] = container

            self._cards_form_layouts[cat_key] = form_layout

        container_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        return scroll

    def _build_table_structure(self) -> QTableWidget:
        """Создать скелет table-представления (QTableWidget с заголовками)."""
        # Подсчёт строк
        total_rows = 0
        for cat_key, cat_fields in self._groups.items():
            title = self._category_titles.get(cat_key, cat_key) if cat_key else ""
            if title:
                total_rows += 1
            total_rows += len(cat_fields)

        table = QTableWidget(total_rows, len(_TABLE_COLUMNS))
        table.setHorizontalHeaderLabels(_TABLE_COLUMNS)
        table.verticalHeader().setVisible(False)

        # Настройка колонок
        from PySide6.QtWidgets import QHeaderView

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        # Заполнить статические ячейки (Параметр, Единица, Описание)
        row = 0
        self._table_widget_rows: dict[str, int] = {}  # editor_key → row index

        for cat_key, cat_fields in self._groups.items():
            title = self._category_titles.get(cat_key, cat_key) if cat_key else ""

            if title:
                item = QTableWidgetItem(title)
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                table.setItem(row, 0, item)
                table.setSpan(row, 0, 1, len(_TABLE_COLUMNS))
                row += 1

            for fi in cat_fields:
                key = _editor_key(fi)
                self._table_widget_rows[key] = row

                # Колонка 0: Параметр
                table.setItem(row, 0, QTableWidgetItem(fi.title))

                # Колонка 2: Единица
                table.setItem(row, 2, QTableWidgetItem(fi.unit or ""))

                # Колонка 3: Описание
                description = ""
                if fi.meta:
                    description = fi.meta.info or fi.meta.description or ""
                table.setItem(row, 3, QTableWidgetItem(description))

                row += 1

        return table

    # ------------------------------------------------------------------
    # Reparenting
    # ------------------------------------------------------------------

    def _place_editors_in_current_mode(self) -> None:
        """Разместить editor.widget в текущем режиме (cards или table)."""
        if self._current_mode == ViewMode.CARDS:
            self._place_editors_in_cards()
        else:
            self._place_editors_in_table()

    def _place_editors_in_cards(self) -> None:
        """Переместить editor.widget и editor.label в QFormLayout (cards).

        Вместо removeRow (который уничтожает C++ объекты) — используем
        removeWidget + addRow. QFormLayout корректно обрабатывает повторный
        addRow для уже удалённого виджета.
        """
        for cat_key, cat_fields in self._groups.items():
            form_layout = self._cards_form_layouts[cat_key]

            # Убираем все виджеты из layout БЕЗ удаления C++ объектов
            # takeAt(0) изымает QLayoutItem, виджет остаётся живым
            while form_layout.count() > 0:
                item = form_layout.takeAt(0)
                if item and item.widget():
                    item.widget().setParent(None)

            parent_widget = self._cards_containers.get(cat_key, self._cards_widget)
            for fi in cat_fields:
                key = _editor_key(fi)
                editor = self._editors[key]
                # reparent: сначала setParent, потом addRow
                editor.label.setParent(parent_widget)
                editor.widget.setParent(parent_widget)
                form_layout.addRow(editor.label, editor.widget)
                editor.label.show()
                editor.widget.show()

    def _place_editors_in_table(self) -> None:
        """Переместить editor.widget в QTableWidget cells (table)."""
        for fi in self._fields:
            key = _editor_key(fi)
            editor = self._editors[key]
            row = self._table_widget_rows.get(key)
            if row is not None:
                # setCellWidget выполняет reparenting автоматически
                self._table_widget.setCellWidget(row, 1, editor.widget)
                editor.widget.show()

    # ------------------------------------------------------------------
    # Обработчики
    # ------------------------------------------------------------------

    def _on_mode_changed(self, mode_str: str) -> None:
        """Обработчик переключения mode от ViewModeToggle."""
        mode = ViewMode(mode_str)
        if mode == self._current_mode:
            return
        self._current_mode = mode
        self._place_editors_in_current_mode()
        self._stack.setCurrentIndex(0 if mode == ViewMode.CARDS else 1)
        self.mode_changed.emit(mode.value)
