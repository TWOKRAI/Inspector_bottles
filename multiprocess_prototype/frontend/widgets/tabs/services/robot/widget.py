# -*- coding: utf-8 -*-
"""RobotControlWidget — поля ручного управления роботом Delta и ПЧ.

Виджет — «тупой» (View): только сигналы наружу + сеттеры состояния. Вся
логика (IPC к плагинам) — в RobotPresenter, проводка — в RobotWidgetController.

UX-ограничения протокола (выставляются контроллером через сеттеры):
- переключатель CVT/DRAW активен только при free=1;
- VFD-кнопки дизейблятся в DRAW-режиме (Lua не обслуживает VFD_FLAG в DRAW).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


def _dspin(minimum: float, maximum: float, value: float, decimals: int = 1) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(decimals)
    box.setValue(value)
    return box


class RobotControlWidget(QWidget):
    """Панели: телеметрия, робот (CVT), рисование, ПЧ (лента)."""

    # --- сигналы наружу (controller подключается) ---
    refresh_requested = Signal()
    send_job_requested = Signal(float, float)  # x, y
    stop_requested = Signal(int)  # 1|2|3
    mode_change_requested = Signal(str)  # cvt|draw
    servo_requested = Signal(bool)
    manual_mode_toggled = Signal(bool)

    draw_circle_requested = Signal(float, float, float, float)  # cx, cy, r, z
    draw_square_requested = Signal(float, float, float, float, float)  # x1,y1,x2,y2,z
    draw_abort_requested = Signal()
    pen_apply_requested = Signal(float, float)  # down, up
    draw_speed_requested = Signal(int)
    overlap_requested = Signal(float)

    vfd_run_requested = Signal(float, bool)  # freq, reverse
    vfd_set_freq_requested = Signal(float)
    vfd_stop_requested = Signal()
    vfd_reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        root.addWidget(self._build_status_group())
        root.addWidget(self._build_robot_group())
        root.addWidget(self._build_draw_group())
        root.addWidget(self._build_vfd_group())
        root.addStretch(1)

    # ------------------------------------------------------------------ #
    # Сборка групп
    # ------------------------------------------------------------------ #

    def _build_status_group(self) -> QGroupBox:
        group = QGroupBox("Состояние")
        layout = QVBoxLayout(group)
        self._lbl_status = QLabel("—")
        self._lbl_status.setWordWrap(True)
        self._lbl_telemetry = QLabel("X=— Y=— Z=— RZ=—")
        self._lbl_flags = QLabel("free=— серво=— энкодер=— очередь=—")
        row = QHBoxLayout()
        self._btn_refresh = QPushButton("Обновить")
        self._btn_refresh.clicked.connect(self.refresh_requested.emit)
        row.addWidget(self._btn_refresh)
        row.addStretch(1)
        layout.addWidget(self._lbl_status)
        layout.addWidget(self._lbl_telemetry)
        layout.addWidget(self._lbl_flags)
        layout.addLayout(row)
        return group

    def _build_robot_group(self) -> QGroupBox:
        group = QGroupBox("Робот (CVT)")
        grid = QGridLayout(group)

        grid.addWidget(QLabel("X, мм:"), 0, 0)
        self._spin_x = _dspin(-3276.7, 3276.7, 0.0)
        grid.addWidget(self._spin_x, 0, 1)
        grid.addWidget(QLabel("Y, мм:"), 0, 2)
        self._spin_y = _dspin(-3276.7, 3276.7, 0.0)
        grid.addWidget(self._spin_y, 0, 3)
        self._btn_send_job = QPushButton("Послать тест-job")
        self._btn_send_job.clicked.connect(
            lambda: self.send_job_requested.emit(self._spin_x.value(), self._spin_y.value())
        )
        grid.addWidget(self._btn_send_job, 0, 4)

        # Стопы (семантика Lua)
        self._btn_stop1 = QPushButton("Стоп: домой")
        self._btn_stop1.clicked.connect(lambda: self.stop_requested.emit(1))
        self._btn_stop2 = QPushButton("Стоп: домой+выход")
        self._btn_stop2.clicked.connect(lambda: self.stop_requested.emit(2))
        self._btn_stop3 = QPushButton("Стоп: на месте")
        self._btn_stop3.clicked.connect(lambda: self.stop_requested.emit(3))
        grid.addWidget(self._btn_stop1, 1, 0, 1, 2)
        grid.addWidget(self._btn_stop2, 1, 2, 1, 2)
        grid.addWidget(self._btn_stop3, 1, 4)

        grid.addWidget(QLabel("Режим:"), 2, 0)
        self._combo_mode = QComboBox()
        self._combo_mode.addItems(["cvt", "draw"])
        self._combo_mode.currentTextChanged.connect(self.mode_change_requested.emit)
        grid.addWidget(self._combo_mode, 2, 1)
        self._chk_servo = QCheckBox("Серво ON")
        self._chk_servo.setChecked(True)
        self._chk_servo.toggled.connect(self.servo_requested.emit)
        grid.addWidget(self._chk_servo, 2, 2)
        self._chk_manual = QCheckBox("Ручной режим (пауза авто-подачи)")
        self._chk_manual.toggled.connect(self.manual_mode_toggled.emit)
        grid.addWidget(self._chk_manual, 2, 3, 1, 2)
        return group

    def _build_draw_group(self) -> QGroupBox:
        group = QGroupBox("Рисование")
        grid = QGridLayout(group)

        grid.addWidget(QLabel("Круг cx/cy/R/Z:"), 0, 0)
        self._circ_cx = _dspin(-3276.7, 3276.7, 0.0)
        self._circ_cy = _dspin(-3276.7, 3276.7, 0.0)
        self._circ_r = _dspin(0.1, 1000.0, 10.0)
        self._circ_z = _dspin(-500.0, 500.0, 0.0)
        for col, w in enumerate((self._circ_cx, self._circ_cy, self._circ_r, self._circ_z), start=1):
            grid.addWidget(w, 0, col)
        self._btn_circle = QPushButton("Круг")
        self._btn_circle.clicked.connect(
            lambda: self.draw_circle_requested.emit(
                self._circ_cx.value(), self._circ_cy.value(), self._circ_r.value(), self._circ_z.value()
            )
        )
        grid.addWidget(self._btn_circle, 0, 5)

        grid.addWidget(QLabel("Квадрат x1/y1/x2/y2/Z:"), 1, 0)
        self._sq = [_dspin(-3276.7, 3276.7, v) for v in (0.0, 0.0, 50.0, 50.0)]
        self._sq_z = _dspin(-500.0, 500.0, 0.0)
        for col, w in enumerate((*self._sq, self._sq_z), start=1):
            grid.addWidget(w, 1, col)
        self._btn_square = QPushButton("Квадрат")
        self._btn_square.clicked.connect(
            lambda: self.draw_square_requested.emit(
                self._sq[0].value(), self._sq[1].value(), self._sq[2].value(), self._sq[3].value(), self._sq_z.value()
            )
        )
        # колонка 5 занята кнопкой круга в строке 0; квадрат — в строке 1
        grid.addWidget(self._btn_square, 1, 5)

        grid.addWidget(QLabel("Перо down/up:"), 2, 0)
        self._pen_down = _dspin(-500.0, 500.0, 0.0)
        self._pen_up = _dspin(-500.0, 500.0, 10.0)
        grid.addWidget(self._pen_down, 2, 1)
        grid.addWidget(self._pen_up, 2, 2)
        self._btn_pen = QPushButton("Задать перо")
        self._btn_pen.clicked.connect(
            lambda: self.pen_apply_requested.emit(self._pen_down.value(), self._pen_up.value())
        )
        grid.addWidget(self._btn_pen, 2, 3)

        grid.addWidget(QLabel("Скорость, %:"), 3, 0)
        self._spin_dspd = QSpinBox()
        self._spin_dspd.setRange(1, 100)
        self._spin_dspd.setValue(30)
        self._spin_dspd.valueChanged.connect(self.draw_speed_requested.emit)
        grid.addWidget(self._spin_dspd, 3, 1)
        grid.addWidget(QLabel("Overlap, мм:"), 3, 2)
        self._spin_overlap = _dspin(0.1, 50.0, 1.0)
        self._spin_overlap.valueChanged.connect(self.overlap_requested.emit)
        grid.addWidget(self._spin_overlap, 3, 3)

        self._lbl_draw = QLabel("Рисование: idle")
        grid.addWidget(self._lbl_draw, 4, 0, 1, 4)
        self._btn_draw_abort = QPushButton("Стоп рисования")
        self._btn_draw_abort.clicked.connect(self.draw_abort_requested.emit)
        grid.addWidget(self._btn_draw_abort, 4, 5)
        return group

    def _build_vfd_group(self) -> QGroupBox:
        group = QGroupBox("ПЧ (лента конвейера)")
        grid = QGridLayout(group)

        grid.addWidget(QLabel("Частота, Гц:"), 0, 0)
        self._spin_freq = _dspin(0.0, 400.0, 10.0, decimals=2)
        grid.addWidget(self._spin_freq, 0, 1)
        self._btn_vfd_run = QPushButton("Пуск")
        self._btn_vfd_run.clicked.connect(lambda: self.vfd_run_requested.emit(self._spin_freq.value(), False))
        self._btn_vfd_rev = QPushButton("Пуск (реверс)")
        self._btn_vfd_rev.clicked.connect(lambda: self.vfd_run_requested.emit(self._spin_freq.value(), True))
        self._btn_vfd_freq = QPushButton("Сменить частоту")
        self._btn_vfd_freq.clicked.connect(lambda: self.vfd_set_freq_requested.emit(self._spin_freq.value()))
        self._btn_vfd_stop = QPushButton("Стоп")
        self._btn_vfd_stop.clicked.connect(self.vfd_stop_requested.emit)
        self._btn_vfd_reset = QPushButton("Сброс аварии")
        self._btn_vfd_reset.clicked.connect(self.vfd_reset_requested.emit)
        for col, btn in enumerate(
            (self._btn_vfd_run, self._btn_vfd_rev, self._btn_vfd_freq, self._btn_vfd_stop, self._btn_vfd_reset),
            start=2,
        ):
            grid.addWidget(btn, 0, col)

        self._lbl_vfd = QLabel("ПЧ: —")
        self._lbl_vfd.setWordWrap(True)
        grid.addWidget(self._lbl_vfd, 1, 0, 1, 7)
        self._lbl_vfd_hint = QLabel("")
        self._lbl_vfd_hint.setWordWrap(True)
        grid.addWidget(self._lbl_vfd_hint, 2, 0, 1, 7)
        return group

    # ------------------------------------------------------------------ #
    # Сеттеры состояния (controller)
    # ------------------------------------------------------------------ #

    def set_status(self, text: str) -> None:
        """Строка статуса секции."""
        self._lbl_status.setText(text)

    def set_telemetry(self, x: float, y: float, z: float, rz: float) -> None:
        """Поза инструмента."""
        self._lbl_telemetry.setText(f"X={x:.1f}  Y={y:.1f}  Z={z:.1f}  RZ={rz:.1f}")

    def set_flags(self, free: bool, servo: bool, encoder: int, queue_len: int) -> None:
        """Флаги CVT-состояния."""
        self._lbl_flags.setText(
            f"free={'да' if free else 'НЕТ'}  серво={'ON' if servo else 'OFF'}  энкодер={encoder}  очередь={queue_len}"
        )

    def set_mode_switch_enabled(self, enabled: bool) -> None:
        """CVT/DRAW активен только при свободном роботе (Lua применяет режим в idle)."""
        self._combo_mode.setEnabled(enabled)

    def current_mode(self) -> str:
        """Текущий выбранный режим."""
        return self._combo_mode.currentText()

    def set_vfd_enabled(self, enabled: bool, hint: str = "") -> None:
        """VFD-кнопки: дизейбл в DRAW-режиме (Lua не обслуживает VFD_FLAG в DRAW)."""
        for btn in (self._btn_vfd_run, self._btn_vfd_rev, self._btn_vfd_freq, self._btn_vfd_stop, self._btn_vfd_reset):
            btn.setEnabled(enabled)
        self._lbl_vfd_hint.setText(hint)

    def set_vfd_status(self, text: str) -> None:
        """Строка статуса ПЧ."""
        self._lbl_vfd.setText(text)

    def set_draw_status(self, text: str) -> None:
        """Строка прогресса рисования."""
        self._lbl_draw.setText(text)
