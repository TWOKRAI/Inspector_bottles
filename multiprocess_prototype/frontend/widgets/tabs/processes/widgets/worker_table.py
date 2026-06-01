# -*- coding: utf-8 -*-
"""WorkerTable — таблица воркеров одного процесса (компактная, 3-4 строки + скролл).

Колонки: Имя · Приоритет(combo) · Режим(combo) · Интервал, мс(spin) · Цикл, мс ·
Статус · Гц. Inline-редактирование приоритета/режима/интервала эмитит
``changed(worker_name, field, value)``. Выбор строки эмитит
``selection_changed(worker_name | None)`` — левая панель вкладки на его основе
включает/выключает кнопки Удалить/Запустить/Остановить (worker-scope).

Создание/удаление/старт/стоп воркера живут в ЛЕВОЙ панели вкладки (не в таблице) —
таблица только показывает воркеров и отдаёт наружу выбор + protected-флаг.

Защищённый воркер (message_processor): inline-редактирование заблокировано
(он — IPC-lifeline процесса; пересоздание убило бы приём команд).

GUI работает с dict (не SchemaBase). Per-row виджеты статуса/Гц/цикла экспонируются
через ``telemetry_widgets(worker_name)`` для GuiStateBindings.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..data import WORKER_EXECUTION_MODES, WORKER_PRIORITIES

_COLUMNS = ["Имя", "Приоритет", "Режим", "Интервал, мс", "Цикл, мс", "Статус", "Гц"]
(
    _COL_NAME,
    _COL_PRIORITY,
    _COL_MODE,
    _COL_INTERVAL,
    _COL_CYCLE,
    _COL_STATUS,
    _COL_HZ,
) = range(7)
# Максимум интервала цикла (мс). 0 = «по приоритету» (special value «—»).
_INTERVAL_MAX = 600_000
# Высота окна таблицы фиксирована под это число строк (видно 5-6 воркеров,
# при меньшем количестве — пустое место снизу; при большем — скролл).
_VISIBLE_ROWS = 6


class WorkerTable(QWidget):
    """Компактная таблица воркеров процесса (read + inline-edit + выбор строки)."""

    selection_changed = Signal(object)  # worker_name (str) | None
    changed = Signal(str, str, object)  # (worker_name, field, value)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._populating = False
        # worker_name → {"status": QLabel, "hz": QLabel, "cycle": QLabel} для биндингов.
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
        vheader = self._table.verticalHeader()
        if vheader is not None:
            vheader.setVisible(False)
        header = self._table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
            for col in (_COL_PRIORITY, _COL_MODE, _COL_INTERVAL, _COL_CYCLE, _COL_STATUS, _COL_HZ):
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        # Высота фиксируется по содержимому (до _VISIBLE_ROWS), без растягивания.
        self._table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        root.addWidget(self._table)

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
        self._apply_height()

    def telemetry_widgets(self, worker_name: str) -> dict[str, QWidget]:
        """Per-row виджеты {"status", "hz", "cycle"} для GuiStateBindings."""
        return self._telemetry.get(worker_name, {})

    def worker_names(self) -> list[str]:
        """Имена воркеров в порядке строк."""
        return list(self._row_names)

    def selected_worker(self) -> str | None:
        """Имя выбранного воркера или None."""
        return self._selected_worker_name()

    def is_worker_protected(self, worker_name: str) -> bool:
        """Защищён ли воркер (по последним загруженным данным)."""
        return bool(self._protected.get(worker_name, False))

    # ------------------------------------------------------------------ #
    #  Высота: компактная, 3-4 строки + скролл                            #
    # ------------------------------------------------------------------ #

    def _row_px(self) -> int:
        vheader = self._table.verticalHeader()
        if vheader is not None and vheader.defaultSectionSize() > 0:
            return vheader.defaultSectionSize()
        return 28

    def _natural_height(self, rows: int) -> int:
        header = self._table.horizontalHeader()
        header_px = header.sizeHint().height() if header is not None else 24
        return header_px + self._row_px() * max(rows, 1) + 2 * self._table.frameWidth() + 2

    def _apply_height(self) -> None:
        """Зафиксировать высоту окна таблицы под _VISIBLE_ROWS строк.

        Высота постоянна независимо от числа воркеров: при меньшем количестве —
        пустое место снизу, при большем (> _VISIBLE_ROWS) — вертикальный скролл.
        """
        height = self._natural_height(_VISIBLE_ROWS)
        self._table.setMinimumHeight(height)
        self._table.setMaximumHeight(height)
        self.updateGeometry()

    def sizeHint(self) -> QSize:  # noqa: N802 — Qt override
        return QSize(super().sizeHint().width(), self._natural_height(_VISIBLE_ROWS))

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
        name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
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

        # Цикл, мс (label, live-телеметрия cycle_duration_ms).
        cycle_label = QLabel("—")
        cycle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setCellWidget(row, _COL_CYCLE, cycle_label)

        # Статус (label, привязывается к телеметрии).
        status_label = QLabel(str(worker.get("status", "—")))
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setCellWidget(row, _COL_STATUS, status_label)

        # Гц (label, привязывается к телеметрии).
        hz_label = QLabel("—")
        hz_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setCellWidget(row, _COL_HZ, hz_label)

        self._telemetry[name] = {"status": status_label, "hz": hz_label, "cycle": cycle_label}

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
        if self._populating:
            return
        self.selection_changed.emit(self._selected_worker_name())

    def _selected_worker_name(self) -> str | None:
        indexes = self._table.selectedIndexes()
        if not indexes:
            return None
        row = indexes[0].row()
        if 0 <= row < len(self._row_names):
            return self._row_names[row]
        return None
