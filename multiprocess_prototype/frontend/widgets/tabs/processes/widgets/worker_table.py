# -*- coding: utf-8 -*-
"""WorkerTable — таблица управления воркерами одного процесса.

Колонки: Имя · Приоритет(combo) · Режим(combo) · Интервал, мс(spin) · Статус · Гц.
Кнопки «Добавить»/«Удалить». Inline-редактирование приоритета/режима/интервала
эмитит ``changed(worker_name, field, value)``. Добавление эмитит ``add_requested``
(панель показывает диалог имени). Удаление — ``remove_requested(worker_name)``.

Защищённый воркер (message_processor): редактирование и удаление заблокированы
(он — IPC-lifeline процесса; пересоздание убило бы приём команд).

GUI работает с dict (не SchemaBase). Per-row виджеты статуса/Гц экспонируются
через ``telemetry_widgets(worker_name)`` для GuiStateBindings.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..data import WORKER_EXECUTION_MODES, WORKER_PRIORITIES

_COLUMNS = ["Имя", "Приоритет", "Режим", "Интервал, мс", "Статус", "Гц"]
_COL_NAME, _COL_PRIORITY, _COL_MODE, _COL_INTERVAL, _COL_STATUS, _COL_HZ = range(6)
# Максимум интервала цикла (мс). 0 = «по приоритету» (special value «—»).
_INTERVAL_MAX = 600_000


class WorkerTable(QWidget):
    """Таблица CRUD воркеров процесса."""

    add_requested = Signal()
    remove_requested = Signal(str)  # worker_name
    changed = Signal(str, str, object)  # (worker_name, field, value)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._populating = False
        # worker_name → {"status": QLabel, "hz": QLabel} для биндингов телеметрии.
        self._telemetry: dict[str, dict[str, QWidget]] = {}
        # row → worker_name
        self._row_names: list[str] = []
        # worker_name → protected
        self._protected: dict[str, bool] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setObjectName("WorkerTable")
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
            for col in (_COL_PRIORITY, _COL_MODE, _COL_INTERVAL, _COL_STATUS, _COL_HZ):
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        root.addWidget(self._table, stretch=1)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        self._add_btn = QPushButton("Добавить воркер")
        self._add_btn.clicked.connect(self.add_requested)
        self._remove_btn = QPushButton("Удалить")
        self._remove_btn.setEnabled(False)
        self._remove_btn.clicked.connect(self._on_remove_clicked)
        button_row.addWidget(self._add_btn)
        button_row.addWidget(self._remove_btn)
        button_row.addStretch(1)
        root.addLayout(button_row)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def set_workers(self, workers: list[dict[str, Any]]) -> None:
        """Полностью перестроить таблицу из списка dict'ов воркеров."""
        self._populating = True
        try:
            self._telemetry.clear()
            self._row_names.clear()
            self._protected.clear()
            self._table.setRowCount(0)
            for worker in workers:
                self._append_row(worker)
        finally:
            self._populating = False
        self._update_remove_enabled()

    def telemetry_widgets(self, worker_name: str) -> dict[str, QWidget]:
        """Per-row виджеты {"status", "hz"} для GuiStateBindings."""
        return self._telemetry.get(worker_name, {})

    def worker_names(self) -> list[str]:
        """Имена воркеров в порядке строк."""
        return list(self._row_names)

    # ------------------------------------------------------------------ #
    #  Build rows                                                          #
    # ------------------------------------------------------------------ #

    def _append_row(self, worker: dict[str, Any]) -> None:
        name = str(worker.get("worker_name", ""))
        protected = bool(worker.get("protected", False))
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._row_names.append(name)
        self._protected[name] = protected

        # Имя (read-only item).
        name_item = QTableWidgetItem(name)
        name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemIsSelectable)
        if protected:
            name_item.setToolTip("Системный воркер IPC — защищён от изменений")
        self._table.setItem(row, _COL_NAME, name_item)

        # Приоритет (combo).
        priority_combo = QComboBox()
        priority_combo.addItems(WORKER_PRIORITIES)
        priority_combo.setCurrentText(str(worker.get("priority", "NORMAL")))
        priority_combo.setEnabled(not protected)
        priority_combo.currentTextChanged.connect(lambda value, n=name: self._emit_changed(n, "priority", value))
        self._table.setCellWidget(row, _COL_PRIORITY, priority_combo)

        # Режим (combo).
        mode_combo = QComboBox()
        mode_combo.addItems(WORKER_EXECUTION_MODES)
        mode_combo.setCurrentText(str(worker.get("execution_mode", "loop")))
        mode_combo.setEnabled(not protected)
        mode_combo.currentTextChanged.connect(lambda value, n=name: self._emit_changed(n, "execution_mode", value))
        self._table.setCellWidget(row, _COL_MODE, mode_combo)

        # Интервал (spin). 0 → «—» (по приоритету).
        interval_spin = QSpinBox()
        interval_spin.setRange(0, _INTERVAL_MAX)
        interval_spin.setSpecialValueText("—")
        interval_spin.setSuffix(" мс")
        interval_spin.setValue(int(worker.get("target_interval_ms") or 0))
        interval_spin.setEnabled(not protected)
        interval_spin.valueChanged.connect(lambda value, n=name: self._emit_changed(n, "target_interval_ms", value))
        self._table.setCellWidget(row, _COL_INTERVAL, interval_spin)

        # Статус (label, привязывается к телеметрии).
        status_label = QLabel(str(worker.get("status", "—")))
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setCellWidget(row, _COL_STATUS, status_label)

        # Гц (label, привязывается к телеметрии).
        hz_label = QLabel("—")
        hz_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setCellWidget(row, _COL_HZ, hz_label)

        self._telemetry[name] = {"status": status_label, "hz": hz_label}

    # ------------------------------------------------------------------ #
    #  Signals                                                            #
    # ------------------------------------------------------------------ #

    def _emit_changed(self, worker_name: str, field: str, value: Any) -> None:
        if self._populating:
            return
        if self._protected.get(worker_name):
            return
        self.changed.emit(worker_name, field, value)

    def _on_selection_changed(self) -> None:
        self._update_remove_enabled()

    def _on_remove_clicked(self) -> None:
        name = self._selected_worker_name()
        if name and not self._protected.get(name):
            self.remove_requested.emit(name)

    def _selected_worker_name(self) -> str | None:
        indexes = self._table.selectedIndexes()
        if not indexes:
            return None
        row = indexes[0].row()
        if 0 <= row < len(self._row_names):
            return self._row_names[row]
        return None

    def _update_remove_enabled(self) -> None:
        name = self._selected_worker_name()
        self._remove_btn.setEnabled(bool(name) and not self._protected.get(name or "", False))
