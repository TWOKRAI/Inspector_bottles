"""Табличный виджет редактора цепочки обработки."""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    Qt,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    Signal,
)
from registers.pipeline.processing_node import ProcessingNode
from registers.processor.catalog.schemas import ProcessingOperationDef
from services.processor.chain.autofill import autofill_inputs

from .schemas import ChainEditorUiConfig

# Индексы колонок таблицы
_COL_ORDER = 0
_COL_OPERATION = 1
_COL_PARAMS = 2
_COL_ENABLED = 3
_COL_PROCESS = 4
_COL_WORKER = 5
_NUM_COLS = 6


class ChainEditorWidget(QWidget):
    """Табличный редактор цепочки узлов обработки для одного региона.

    Не наследует BaseWidget — не привязан к регистрам напрямую.
    Управляет порядком, включением и операциями узлов через QTableWidget.

    Signal nodes_changed эмитируется при любом изменении цепочки.
    """

    # Эмитируется после каждого изменения таблицы
    nodes_changed = Signal()

    def __init__(
        self,
        *,
        ui: ChainEditorUiConfig | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Инициализация: создать layout, таблицу и кнопки управления."""
        super().__init__(parent)
        self._ui = ui or ChainEditorUiConfig()

        # Внутреннее состояние
        self._nodes: dict[str, ProcessingNode] = {}
        self._catalog: dict[str, ProcessingOperationDef] = {}
        self._region_id: str = ""
        # Количество воркеров — задаёт варианты в dropdown колонки Worker
        self._worker_count: int = 2
        # Флаг блокировки сигналов при программном заполнении таблицы
        self._updating: bool = False

        self._build_ui()

    # --- Публичный API ---

    def set_data(
        self,
        nodes: dict[str, ProcessingNode],
        catalog: dict[str, ProcessingOperationDef],
        region_id: str,
    ) -> None:
        """Заполнить таблицу данными из внешнего источника.

        nodes    — текущие узлы региона (node_id → ProcessingNode)
        catalog  — доступные операции (type_key → ProcessingOperationDef)
        region_id — идентификатор региона
        """
        self._catalog = catalog
        self._region_id = region_id
        # autofill_inputs гарантирует корректные inputs для линейной цепочки
        self._nodes = autofill_inputs(nodes)
        self._refresh_table()

    def get_nodes(self) -> dict[str, ProcessingNode]:
        """Собрать текущее состояние из таблицы.

        Читает operation_ref, enabled, process_id, worker_id из виджетов строк.
        Inputs пересчитываются через autofill_inputs.
        """
        nodes: dict[str, ProcessingNode] = {}

        for row in range(self._table.rowCount()):
            node_id = self._get_node_id_by_row(row)
            if node_id is None:
                continue

            # Операция из QComboBox
            combo = self._table.cellWidget(row, _COL_OPERATION)
            operation_ref = combo.currentData() if combo else ""

            # Флаг enabled из QCheckBox
            enabled_widget = self._table.cellWidget(row, _COL_ENABLED)
            enabled = enabled_widget.isChecked() if enabled_widget else True

            # process_id из QLabel (readonly)
            process_label = self._table.cellWidget(row, _COL_PROCESS)
            process_id = process_label.text() if process_label else "processor"

            # worker_id из QComboBox: "auto" → None, иначе — текст напрямую
            worker_combo = self._table.cellWidget(row, _COL_WORKER)
            worker_text = worker_combo.currentText() if worker_combo else "auto"
            worker_id = None if worker_text == "auto" else worker_text

            # Оригинальные params сохраняем из внутреннего состояния
            original = self._nodes.get(node_id)
            params = original.params if original else {}

            node = ProcessingNode(
                node_id=node_id,
                operation_ref=operation_ref,
                params=params,
                enabled=enabled,
                process_id=process_id,
                worker_id=worker_id,
            )
            nodes[node_id] = node

        return autofill_inputs(nodes)

    # --- Построение UI ---

    def _build_ui(self) -> None:
        """Создать главный layout: таблица + панель кнопок."""
        layout = QVBoxLayout(self)

        # Таблица
        self._table = QTableWidget(0, _NUM_COLS)
        self._table.setHorizontalHeaderLabels([
            self._ui.col_order,
            self._ui.col_operation,
            self._ui.col_params,
            self._ui.col_enabled,
            self._ui.col_process,
            self._ui.col_worker,
        ])
        # Растянуть колонку операции, остальные — по содержимому
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(_COL_ORDER, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_OPERATION, QHeaderView.Stretch)
        header.setSectionResizeMode(_COL_PARAMS, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_ENABLED, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_PROCESS, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_WORKER, QHeaderView.ResizeToContents)

        # Запрет прямого редактирования ячеек (только через виджеты)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        # Выделение строки целиком
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)

        layout.addWidget(self._table)

        # Панель кнопок
        btn_layout = QHBoxLayout()
        self._btn_add = QPushButton(self._ui.btn_add)
        self._btn_remove = QPushButton(self._ui.btn_remove)
        self._btn_up = QPushButton(self._ui.btn_up)
        self._btn_down = QPushButton(self._ui.btn_down)

        btn_layout.addWidget(self._btn_add)
        btn_layout.addWidget(self._btn_remove)
        btn_layout.addWidget(self._btn_up)
        btn_layout.addWidget(self._btn_down)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Подключение сигналов кнопок
        self._btn_add.clicked.connect(self._on_add)
        self._btn_remove.clicked.connect(self._on_remove)
        self._btn_up.clicked.connect(self._on_move_up)
        self._btn_down.clicked.connect(self._on_move_down)

    # --- Заполнение таблицы ---

    def _refresh_table(self) -> None:
        """Перерисовать таблицу из self._nodes.

        Блокирует emitting nodes_changed на время программного заполнения.
        """
        self._updating = True
        ordered = list(self._nodes.items())

        self._table.setRowCount(len(ordered))

        for row, (node_id, node) in enumerate(ordered):
            self._fill_row(row, node_id, node)

        self._updating = False

    def _fill_row(self, row: int, node_id: str, node: ProcessingNode) -> None:
        """Заполнить одну строку таблицы виджетами."""
        # Колонка #: номер строки (1-based), в UserRole — node_id
        order_item = QTableWidgetItem(str(row + 1))
        order_item.setData(Qt.ItemDataRole.UserRole, node_id)
        order_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setItem(row, _COL_ORDER, order_item)

        # Колонка Операция: QComboBox из каталога
        combo = QComboBox()
        for type_key, op_def in self._catalog.items():
            combo.addItem(op_def.name, type_key)
        # Выбрать текущую операцию
        idx = combo.findData(node.operation_ref)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.currentIndexChanged.connect(self._on_operation_changed)
        self._table.setCellWidget(row, _COL_OPERATION, combo)

        # Колонка Параметры: кнопка "..."
        btn_params = QPushButton("...")
        btn_params.setToolTip("Редактировать параметры")
        # Phase 5a: редактор параметров не реализован, кнопка-заглушка
        self._table.setCellWidget(row, _COL_PARAMS, btn_params)

        # Колонка Вкл: QCheckBox по центру
        checkbox = QCheckBox()
        checkbox.setChecked(node.enabled)
        checkbox.setStyleSheet("margin-left: auto; margin-right: auto;")
        checkbox.stateChanged.connect(self._on_enabled_changed)
        self._table.setCellWidget(row, _COL_ENABLED, checkbox)

        # Колонка Процесс: readonly QLabel
        process_label = QLabel(node.process_id)
        process_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setCellWidget(row, _COL_PROCESS, process_label)

        # Колонка Worker: QComboBox — "auto" или worker_0..worker_N
        worker_combo = QComboBox()
        worker_combo.addItem("auto")
        for i in range(self._worker_count):
            worker_combo.addItem(f"worker_{i}")
        # Выбрать текущее значение: None → "auto", иначе точное совпадение
        if node.worker_id is None:
            worker_combo.setCurrentText("auto")
        else:
            idx = worker_combo.findText(node.worker_id)
            worker_combo.setCurrentIndex(idx if idx >= 0 else 0)
        worker_combo.currentTextChanged.connect(self._on_worker_changed)
        self._table.setCellWidget(row, _COL_WORKER, worker_combo)

    # --- Обработчики кнопок ---

    def _on_add(self) -> None:
        """Добавить новый узел с первой операцией из каталога."""
        if not self._catalog:
            return

        # Первая операция в каталоге
        first_type_key = next(iter(self._catalog))
        from uuid import uuid4
        node_id = str(uuid4())
        node = ProcessingNode(node_id=node_id, operation_ref=first_type_key)
        self._nodes[node_id] = node
        self._apply_autofill_and_emit()

    def _on_remove(self) -> None:
        """Удалить выделенную строку."""
        row = self._get_selected_row()
        if row is None:
            return

        node_id = self._get_node_id_by_row(row)
        if node_id is None:
            return

        self._nodes.pop(node_id, None)
        self._apply_autofill_and_emit()

    def _on_move_up(self) -> None:
        """Переместить выделенный узел на одну позицию вверх."""
        row = self._get_selected_row()
        if row is None or row == 0:
            return

        node_id = self._get_node_id_by_row(row)
        if node_id is None:
            return

        self._swap_nodes_by_row(row, row - 1)
        self._apply_autofill_and_emit()
        # Сохранить выделение на перемещённой строке
        self._table.selectRow(row - 1)

    def _on_move_down(self) -> None:
        """Переместить выделенный узел на одну позицию вниз."""
        row = self._get_selected_row()
        if row is None or row >= self._table.rowCount() - 1:
            return

        node_id = self._get_node_id_by_row(row)
        if node_id is None:
            return

        self._swap_nodes_by_row(row, row + 1)
        self._apply_autofill_and_emit()
        # Сохранить выделение на перемещённой строке
        self._table.selectRow(row + 1)

    # --- Обработчики изменений в ячейках ---

    def _on_operation_changed(self) -> None:
        """Синхронизировать operation_ref в self._nodes при смене комбобокса."""
        if self._updating:
            return

        # Найти строку по sender (QComboBox)
        sender_combo = self.sender()
        for row in range(self._table.rowCount()):
            widget = self._table.cellWidget(row, _COL_OPERATION)
            if widget is sender_combo:
                node_id = self._get_node_id_by_row(row)
                if node_id and node_id in self._nodes:
                    new_op = sender_combo.currentData()
                    self._nodes[node_id] = self._nodes[node_id].model_copy(
                        update={"operation_ref": new_op}
                    )
                break

        self._apply_autofill_and_emit()

    def _on_enabled_changed(self) -> None:
        """Синхронизировать enabled в self._nodes при изменении чекбокса."""
        if self._updating:
            return

        sender_cb = self.sender()
        for row in range(self._table.rowCount()):
            widget = self._table.cellWidget(row, _COL_ENABLED)
            if widget is sender_cb:
                node_id = self._get_node_id_by_row(row)
                if node_id and node_id in self._nodes:
                    self._nodes[node_id] = self._nodes[node_id].model_copy(
                        update={"enabled": sender_cb.isChecked()}
                    )
                break

        self._apply_autofill_and_emit()

    def set_worker_count(self, count: int) -> None:
        """Установить количество воркеров и перестроить все dropdown Worker.

        Обновляет _worker_count и перезаполняет варианты в каждой строке таблицы.
        Текущий выбор сохраняется, если такой воркер есть в новом списке.
        """
        self._worker_count = count
        self._updating = True
        for row in range(self._table.rowCount()):
            worker_combo = self._table.cellWidget(row, _COL_WORKER)
            if worker_combo is None:
                continue
            # Сохранить текущий выбор перед перестройкой
            current_text = worker_combo.currentText()
            # Блокируем сигнал на время перестройки вариантов
            worker_combo.blockSignals(True)
            worker_combo.clear()
            worker_combo.addItem("auto")
            for i in range(self._worker_count):
                worker_combo.addItem(f"worker_{i}")
            # Восстановить выбор или сбросить на "auto"
            idx = worker_combo.findText(current_text)
            worker_combo.setCurrentIndex(idx if idx >= 0 else 0)
            worker_combo.blockSignals(False)
        self._updating = False

    def _on_worker_changed(self) -> None:
        """Синхронизировать worker_id в self._nodes при смене dropdown Worker."""
        if self._updating:
            return

        sender_combo = self.sender()
        for row in range(self._table.rowCount()):
            widget = self._table.cellWidget(row, _COL_WORKER)
            if widget is sender_combo:
                node_id = self._get_node_id_by_row(row)
                if node_id and node_id in self._nodes:
                    text = sender_combo.currentText()
                    # "auto" означает worker_id = None
                    new_worker_id = None if text == "auto" else text
                    self._nodes[node_id] = self._nodes[node_id].model_copy(
                        update={"worker_id": new_worker_id}
                    )
                break

        if not self._updating:
            self.nodes_changed.emit()

    # --- Вспомогательные методы ---

    def _apply_autofill_and_emit(self) -> None:
        """Применить autofill_inputs, перерисовать таблицу, эмитировать nodes_changed."""
        self._nodes = autofill_inputs(self._nodes)
        self._refresh_table()
        self.nodes_changed.emit()

    def _get_selected_row(self) -> int | None:
        """Вернуть индекс выделенной строки или None если ничего не выделено."""
        selected = self._table.selectedItems()
        if not selected:
            return None
        return selected[0].row()

    def _get_node_id_by_row(self, row: int) -> str | None:
        """Получить node_id из UserRole колонки #."""
        item = self._table.item(row, _COL_ORDER)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _swap_nodes_by_row(self, row_a: int, row_b: int) -> None:
        """Поменять местами два узла в self._nodes по номерам строк."""
        node_id_a = self._get_node_id_by_row(row_a)
        node_id_b = self._get_node_id_by_row(row_b)
        if node_id_a is None or node_id_b is None:
            return

        ordered = list(self._nodes.items())
        # Найти позиции по node_id
        idx_a = next((i for i, (k, _) in enumerate(ordered) if k == node_id_a), None)
        idx_b = next((i for i, (k, _) in enumerate(ordered) if k == node_id_b), None)
        if idx_a is None or idx_b is None:
            return

        ordered[idx_a], ordered[idx_b] = ordered[idx_b], ordered[idx_a]
        self._nodes = dict(ordered)
