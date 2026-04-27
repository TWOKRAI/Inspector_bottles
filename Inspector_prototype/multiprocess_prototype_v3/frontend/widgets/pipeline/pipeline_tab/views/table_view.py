"""PipelineTableView — табличное представление списка нод одной region.

Отображает ноды в плоском QTreeView (без иерархии — flat).
Поддерживает inline-редактирование process_id и enabled.
Bulk-edit: при выделении нескольких нод изменение применяется ко всем.
Все мутации идут через ActionBus (GRAPH_NODE_MODIFY).
Показывает linearity warning под таблицей при нелинейном графе.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from frontend.actions.builder import ActionBuilder
from frontend.actions.bus import ActionBus
from ..canvas.linearity_check import get_linearity_warning
from ..canvas.model import GraphEditorModel
from registers.processor.catalog.schemas import ProcessingOperationDef

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Индексы колонок
# ---------------------------------------------------------------------------

COL_ENABLED = 0
COL_NAME = 1
COL_OPERATION = 2
COL_PROCESS_ID = 3
COL_DISPLAYS = 4
COL_POSITION = 5

COL_HEADERS = [
    "Включено",
    "Имя ноды",
    "Операция",
    "process_id",
    "Дисплеи",
    "Позиция",
]

# UserRole для хранения node_id в 0-й колонке
_ROLE_NODE_ID = Qt.UserRole


# ---------------------------------------------------------------------------
# Delegate для process_id (QComboBox)
# ---------------------------------------------------------------------------


class _ProcessIdDelegate(QtWidgets.QStyledItemDelegate):
    """Delegate для колонки process_id — показывает QComboBox.

    Список вариантов берётся из known_processes_provider().
    Если выбран sentinel «+ Новый процесс…» — показывает QInputDialog.
    Изменение применяется через _apply_callback(node_id, new_value).
    """

    _SENTINEL = "+ Новый процесс…"

    def __init__(
        self,
        known_processes_provider: Callable[[], list[str]],
        apply_callback: Callable[[str, str], None],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._known_processes_provider = known_processes_provider
        self._apply_callback = apply_callback

    def createEditor(
        self,
        parent: QtWidgets.QWidget,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> QtWidgets.QWidget:
        """Создать QComboBox с известными процессами + sentinel."""
        combo = QtWidgets.QComboBox(parent)
        processes = self._known_processes_provider()
        for p in processes:
            combo.addItem(p)
        combo.addItem(self._SENTINEL)
        return combo

    def setEditorData(
        self,
        editor: QtWidgets.QWidget,
        index: QtCore.QModelIndex,
    ) -> None:
        """Установить текущее значение в редакторе."""
        current = index.data(Qt.DisplayRole)
        combo: QtWidgets.QComboBox = editor  # type: ignore[assignment]
        idx = combo.findText(current)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def setModelData(
        self,
        editor: QtWidgets.QWidget,
        model: QtCore.QAbstractItemModel,
        index: QtCore.QModelIndex,
    ) -> None:
        """Применить изменение: получить node_id, вызвать callback."""
        combo: QtWidgets.QComboBox = editor  # type: ignore[assignment]
        chosen = combo.currentText()

        if chosen == self._SENTINEL:
            # Диалог ввода нового process_id
            name, ok = QtWidgets.QInputDialog.getText(
                None,
                "Новый процесс",
                "Имя процесса:",
            )
            if not ok or not name.strip():
                return
            chosen = name.strip()

        # node_id хранится в COL_ENABLED (0) через UserRole
        node_id_idx = model.index(index.row(), COL_ENABLED)
        node_id = node_id_idx.data(_ROLE_NODE_ID)
        if node_id:
            self._apply_callback(node_id, chosen)

    def updateEditorGeometry(
        self,
        editor: QtWidgets.QWidget,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        editor.setGeometry(option.rect)


# ---------------------------------------------------------------------------
# PipelineTableView
# ---------------------------------------------------------------------------


class PipelineTableView(QtWidgets.QWidget):
    """Табличный вид нод одной region с bulk-edit и linearity warning.

    Signals:
        selection_changed(str): node_id при смене выделения, "" при пустой.
        node_modified(str, dict): (node_id, fields_changed) — для тестов и sync.
    """

    selection_changed = QtCore.Signal(str)
    node_modified = QtCore.Signal(str, dict)

    def __init__(
        self,
        *,
        model: GraphEditorModel,
        action_bus: ActionBus,
        catalog: dict[str, ProcessingOperationDef],
        region_id: str,
        known_processes_provider: Callable[[], list[str]],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._model = model
        self._action_bus = action_bus
        self._catalog = catalog
        self._region_id = region_id
        self._known_processes_provider = known_processes_provider

        # Блокировка обратных сигналов при programmatic selection
        self._suppress_selection = False

        # Последнее выделение (для восстановления после refresh)
        self._last_selected_id: str | None = None

        self._build_ui()
        self._action_bus.add_change_callback(self._on_action_bus_changed)

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Создать layout: QTreeView + warning bar."""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Модель данных
        self._item_model = QtGui.QStandardItemModel(0, len(COL_HEADERS), self)
        self._item_model.setHorizontalHeaderLabels(COL_HEADERS)
        self._item_model.itemChanged.connect(self._on_item_changed)

        # QTreeView (flat — без иерархии)
        self._tree = QtWidgets.QTreeView(self)
        self._tree.setRootIsDecorated(False)
        self._tree.setModel(self._item_model)
        self._tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._tree.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._tree.setAlternatingRowColors(True)
        self._tree.header().setStretchLastSection(True)

        # Delegate для process_id
        self._process_delegate = _ProcessIdDelegate(
            known_processes_provider=self._known_processes_provider,
            apply_callback=self._on_process_id_changed_from_delegate,
            parent=self,
        )
        self._tree.setItemDelegateForColumn(COL_PROCESS_ID, self._process_delegate)

        # Подключение сигнала выделения
        self._tree.selectionModel().selectionChanged.connect(
            self._on_selection_changed
        )

        layout.addWidget(self._tree)

        # Warning bar (linearity)
        self._warning_label = QtWidgets.QLabel(self)
        self._warning_label.setWordWrap(True)
        self._warning_label.setStyleSheet(
            "QLabel { background-color: #FFF3CD; color: #856404; "
            "border: 1px solid #FFE69C; border-radius: 3px; padding: 4px; }"
        )
        self._warning_label.hide()
        layout.addWidget(self._warning_label)

    # ------------------------------------------------------------------
    # Публичное API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Перезаполнить таблицу из model.nodes. Восстанавливает выделение."""
        # Отключаем сигналы itemChanged на время заполнения
        self._item_model.itemChanged.disconnect(self._on_item_changed)
        self._item_model.removeRows(0, self._item_model.rowCount())

        nodes = self._model.nodes

        for node_id, node in nodes.items():
            op_def = self._catalog.get(node.operation_ref)
            row = self._make_row(node_id, node, op_def)
            self._item_model.appendRow(row)

        # Linearity warning
        warning = get_linearity_warning(nodes)
        if warning:
            self._warning_label.setText(warning)
            self._warning_label.show()
        else:
            self._warning_label.hide()

        # Подключаем обратно
        self._item_model.itemChanged.connect(self._on_item_changed)

        # Восстановить выделение
        if self._last_selected_id is not None:
            self._suppress_selection = True
            self._select_row_by_node_id(self._last_selected_id)
            self._suppress_selection = False

    def select_node(self, node_id: str | None) -> None:
        """Программно выделить ноду. Подавляет обратный сигнал."""
        self._suppress_selection = True
        try:
            if not node_id:
                self._tree.clearSelection()
                self._last_selected_id = None
            else:
                self._last_selected_id = node_id
                self._select_row_by_node_id(node_id)
        finally:
            self._suppress_selection = False

    def selected_node_ids(self) -> list[str]:
        """Вернуть список node_id всех выделенных строк."""
        result: list[str] = []
        for index in self._tree.selectionModel().selectedRows():
            nid = self._item_model.item(index.row(), COL_ENABLED)
            if nid is not None:
                node_id = nid.data(_ROLE_NODE_ID)
                if node_id:
                    result.append(node_id)
        return result

    # ------------------------------------------------------------------
    # Внутренние вспомогательные методы
    # ------------------------------------------------------------------

    def _make_row(
        self,
        node_id: str,
        node: Any,
        op_def: ProcessingOperationDef | None,
    ) -> list[QtGui.QStandardItem]:
        """Создать список QStandardItem для одной строки таблицы."""
        # Колонка 0: Включено (checkbox)
        enabled_item = QtGui.QStandardItem()
        enabled_item.setCheckable(True)
        enabled_item.setCheckState(
            Qt.CheckState.Checked if node.enabled else Qt.CheckState.Unchecked
        )
        enabled_item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsUserCheckable
        )
        # Храним node_id в UserRole
        enabled_item.setData(node_id, _ROLE_NODE_ID)

        # Колонка 1: Имя ноды
        display_name = (op_def.name if op_def else None) or node_id[:8]
        name_item = QtGui.QStandardItem(display_name)
        name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

        # Колонка 2: Операция (type_key)
        op_item = QtGui.QStandardItem(node.operation_ref)
        op_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

        # Колонка 3: process_id (редактируемое)
        pid_item = QtGui.QStandardItem(node.process_id)
        pid_item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEditable
        )

        # Колонка 4: Дисплеи (read-only CSV)
        displays_str = ", ".join(node.display_targets) if node.display_targets else "—"
        disp_item = QtGui.QStandardItem(displays_str)
        disp_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

        # Колонка 5: Позиция (read-only)
        if node.position:
            pos_str = f"({node.position[0]:.0f}, {node.position[1]:.0f})"
        else:
            pos_str = "—"
        pos_item = QtGui.QStandardItem(pos_str)
        pos_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

        return [enabled_item, name_item, op_item, pid_item, disp_item, pos_item]

    def _select_row_by_node_id(self, node_id: str) -> None:
        """Найти строку с node_id и выделить её."""
        for row in range(self._item_model.rowCount()):
            item = self._item_model.item(row, COL_ENABLED)
            if item and item.data(_ROLE_NODE_ID) == node_id:
                index = self._item_model.index(row, 0)
                self._tree.selectionModel().select(
                    self._item_model.index(row, 0),
                    QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect
                    | QtCore.QItemSelectionModel.SelectionFlag.Rows,
                )
                self._tree.scrollTo(index)
                return

    def _get_node_id_at_row(self, row: int) -> str | None:
        """Вернуть node_id строки row."""
        item = self._item_model.item(row, COL_ENABLED)
        if item:
            return item.data(_ROLE_NODE_ID)
        return None

    # ------------------------------------------------------------------
    # Bulk-edit: применить изменение поля ко всем выделенным + clicked
    # ------------------------------------------------------------------

    def _apply_bulk_modify(
        self,
        clicked_node_id: str,
        field: str,
        value: Any,
    ) -> None:
        """Применить изменение поля ко всем выделенным нодам.

        Логика: set(selected_ids) | {clicked_node_id}.
        Для каждой ноды — отдельный GRAPH_NODE_MODIFY action.

        Args:
            clicked_node_id: Нода, которую непосредственно изменили.
            field: Поле ('process_id' или 'enabled').
            value: Новое значение поля.
        """
        selected_ids = set(self.selected_node_ids())
        selected_ids.add(clicked_node_id)

        nodes = self._model.nodes

        for nid in selected_ids:
            if nid not in nodes:
                continue

            node = nodes[nid]
            old_value = getattr(node, field, None)

            # Пропускаем если значение не изменилось
            if old_value == value:
                continue

            nodes_before = deepcopy(self._model.nodes)
            try:
                fields_before, fields_after = self._model.modify_node(nid, {field: value})
            except (KeyError, ValueError) as exc:
                logger.warning("modify_node(%s, %s=%r) ошибка: %s", nid, field, value, exc)
                continue
            nodes_after = deepcopy(self._model.nodes)

            action = ActionBuilder.graph_node_modify(
                region_id=self._region_id,
                node_id=nid,
                fields_before=fields_before,
                fields_after=fields_after,
                nodes_before=nodes_before,
                nodes_after=nodes_after,
            )
            self._action_bus.record(action)
            self.node_modified.emit(nid, {field: value})

        self.refresh()

    # ------------------------------------------------------------------
    # Обработчики изменений
    # ------------------------------------------------------------------

    def _on_item_changed(self, item: QtGui.QStandardItem) -> None:
        """Обработать изменение ячейки (checkbox enabled)."""
        if item.column() != COL_ENABLED:
            return

        node_id = item.data(_ROLE_NODE_ID)
        if not node_id:
            return

        new_enabled = item.checkState() == Qt.CheckState.Checked
        self._apply_bulk_modify(node_id, "enabled", new_enabled)

    def _on_process_id_changed_from_delegate(
        self,
        node_id: str,
        new_process_id: str,
    ) -> None:
        """Вызывается из _ProcessIdDelegate при подтверждении нового process_id."""
        self._apply_bulk_modify(node_id, "process_id", new_process_id)

    def _on_selection_changed(
        self,
        selected: QtCore.QItemSelection,
        deselected: QtCore.QItemSelection,
    ) -> None:
        """Обработать изменение выделения в QTreeView."""
        if self._suppress_selection:
            return

        rows = self._tree.selectionModel().selectedRows()
        if not rows:
            self._last_selected_id = None
            self.selection_changed.emit("")
            return

        # Берём первую выделенную строку
        row = rows[0].row()
        node_id = self._get_node_id_at_row(row)
        if node_id:
            self._last_selected_id = node_id
            self.selection_changed.emit(node_id)
        else:
            self._last_selected_id = None
            self.selection_changed.emit("")

    def _on_action_bus_changed(self) -> None:
        """При undo/redo от ActionBus — обновить таблицу."""
        self.refresh()

    # ------------------------------------------------------------------
    # Метод для прямой установки данных (для тестов bulk-edit)
    # ------------------------------------------------------------------

    def apply_field_change(
        self,
        node_id: str,
        field: str,
        value: Any,
    ) -> None:
        """Применить изменение поля напрямую (API для тестов).

        Использует ту же bulk-edit логику.
        """
        self._apply_bulk_modify(node_id, field, value)


__all__ = ["PipelineTableView"]
