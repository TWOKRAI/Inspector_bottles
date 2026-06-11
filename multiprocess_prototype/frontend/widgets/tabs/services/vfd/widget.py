# -*- coding: utf-8 -*-
"""VfdControlWidget — поля управления частотным преобразователем.

Виджет — «тупой» (View): только сигналы наружу + сеттеры состояния.
Вся логика (IPC к процессу devices) — в VfdPresenter, проводка — в
VfdWidgetController.

UX-ограничения (выставляются контроллером через сеттеры):
- кнопки disabled в DRAW-режиме робота-носителя (Lua не обслуживает VFD_FLAG).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class VfdControlWidget(QWidget):
    """Панели: управление ПЧ (частота, пуск/стоп, аварии) + статус."""

    # --- сигналы наружу (controller подключается) ---
    run_requested = Signal(float, bool)  # freq_hz, reverse
    set_freq_requested = Signal(float)
    stop_requested = Signal()
    reset_fault_requested = Signal()
    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Placeholder для DeviceComboController — вставляется контроллером
        self._combo_placeholder = QVBoxLayout()
        root.addLayout(self._combo_placeholder)

        root.addWidget(self._build_control_group())
        root.addWidget(self._build_status_group())
        root.addStretch(1)

    def add_combo_widget(self, widget: QWidget) -> None:
        """Вставить виджет DeviceComboController в placeholder."""
        self._combo_placeholder.addWidget(widget)

    # ------------------------------------------------------------------ #
    # Сборка групп
    # ------------------------------------------------------------------ #

    def _build_control_group(self) -> QGroupBox:
        group = QGroupBox("Управление ПЧ")
        grid = QGridLayout(group)

        grid.addWidget(QLabel("Частота, Гц:"), 0, 0)
        self._spin_freq = QDoubleSpinBox()
        self._spin_freq.setRange(0.0, 400.0)
        self._spin_freq.setDecimals(2)
        self._spin_freq.setValue(10.0)
        grid.addWidget(self._spin_freq, 0, 1)

        self._btn_run = QPushButton("Пуск")
        self._btn_run.clicked.connect(lambda: self.run_requested.emit(self._spin_freq.value(), False))
        self._btn_run_rev = QPushButton("Пуск (реверс)")
        self._btn_run_rev.clicked.connect(lambda: self.run_requested.emit(self._spin_freq.value(), True))
        self._btn_set_freq = QPushButton("Сменить частоту")
        self._btn_set_freq.clicked.connect(lambda: self.set_freq_requested.emit(self._spin_freq.value()))
        self._btn_stop = QPushButton("Стоп")
        self._btn_stop.clicked.connect(self.stop_requested.emit)
        self._btn_reset = QPushButton("Сброс аварии")
        self._btn_reset.clicked.connect(self.reset_fault_requested.emit)

        for col, btn in enumerate(
            (self._btn_run, self._btn_run_rev, self._btn_set_freq, self._btn_stop, self._btn_reset),
            start=2,
        ):
            grid.addWidget(btn, 0, col)

        return group

    def _build_status_group(self) -> QGroupBox:
        group = QGroupBox("Состояние ПЧ")
        layout = QVBoxLayout(group)

        self._lbl_status = QLabel("ПЧ: —")
        self._lbl_status.setWordWrap(True)
        layout.addWidget(self._lbl_status)

        self._lbl_quality = QLabel("")
        self._lbl_quality.setWordWrap(True)
        layout.addWidget(self._lbl_quality)

        self._lbl_conn = QLabel("Подключение: —")
        layout.addWidget(self._lbl_conn)

        self._lbl_error = QLabel("")
        self._lbl_error.setWordWrap(True)
        layout.addWidget(self._lbl_error)

        self._lbl_hint = QLabel("")
        self._lbl_hint.setWordWrap(True)
        layout.addWidget(self._lbl_hint)

        row = QHBoxLayout()
        self._btn_refresh = QPushButton("Обновить")
        self._btn_refresh.clicked.connect(self.refresh_requested.emit)
        row.addWidget(self._btn_refresh)
        row.addStretch(1)
        layout.addLayout(row)
        return group

    # ------------------------------------------------------------------ #
    # Сеттеры состояния (controller)
    # ------------------------------------------------------------------ #

    def set_freq_range(self, min_hz: float, max_hz: float) -> None:
        """Установить лимиты частоты из protocol meta."""
        self._spin_freq.setRange(min_hz, max_hz)

    def set_status(self, text: str) -> None:
        """Строка статуса ПЧ (running/freq/current/etc)."""
        self._lbl_status.setText(text)

    def set_quality(self, text: str) -> None:
        """Индикатор quality (good/stale/bad)."""
        self._lbl_quality.setText(text)

    def set_conn(self, text: str) -> None:
        """Строка состояния подключения."""
        self._lbl_conn.setText(text)

    def set_error(self, text: str) -> None:
        """Последняя ошибка."""
        self._lbl_error.setText(text)

    def set_controls_enabled(self, enabled: bool, hint: str = "") -> None:
        """Включить/выключить кнопки управления (gating DRAW/conn)."""
        for btn in (self._btn_run, self._btn_run_rev, self._btn_set_freq, self._btn_stop, self._btn_reset):
            btn.setEnabled(enabled)
        self._lbl_hint.setText(hint)
