# -*- coding: utf-8 -*-
"""RobotControlWidget — поля ручного управления роботом Delta.

Виджет — «тупой» (View): только сигналы наружу + сеттеры состояния. Вся
логика (IPC к процессу devices) — в RobotPresenter, проводка — в
RobotWidgetController.

Фаза 4 device-hub: группа ПЧ убрана (отдельная вкладка «ПЧ»); добавлен
placeholder для DeviceComboController (kind=robot).

UX-ограничения протокола (выставляются контроллером через сеттеры):
- переключатель CVT/DRAW активен только при free=1.
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
    QLineEdit,
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
    """Панели: телеметрия, робот (CVT), рисование."""

    # --- сигналы наружу (controller подключается) ---
    refresh_requested = Signal()
    send_job_requested = Signal(float, float)  # x, y
    stop_requested = Signal(int)  # 1|2|3
    mode_change_requested = Signal(str)  # cvt|draw|manual
    servo_requested = Signal(bool)
    manual_mode_toggled = Signal(bool)
    jog_requested = Signal(float, float, int, bool)  # dx_mm, dy_mm, spd_pct, absolute
    jog_abort_requested = Signal()

    draw_circle_requested = Signal(float, float, float, float)  # cx, cy, r, z
    draw_square_requested = Signal(float, float, float, float, float)  # x1,y1,x2,y2,z
    draw_abort_requested = Signal()
    pen_apply_requested = Signal(float, float)  # down, up
    draw_speed_requested = Signal(int)
    overlap_requested = Signal(float)

    # Рецепт webcam_sketch: заморозка камеры / возобновление / отправка точек роботу
    camera_freeze_requested = Signal(str)  # camera process_name
    camera_resume_requested = Signal(str)  # camera process_name
    send_to_robot_requested = Signal(str)  # points process_name

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Placeholder для DeviceComboController — вставляется секцией
        self._combo_placeholder = QVBoxLayout()
        root.addLayout(self._combo_placeholder)

        root.addWidget(self._build_status_group())
        root.addWidget(self._build_robot_group())
        root.addWidget(self._build_jog_group())
        root.addWidget(self._build_draw_group())
        root.addWidget(self._build_sketch_group())
        root.addStretch(1)

    def add_combo_widget(self, widget: QWidget) -> None:
        """Вставить виджет DeviceComboController в placeholder."""
        self._combo_placeholder.addWidget(widget)

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
        self._combo_mode.addItems(["cvt", "draw", "manual"])
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

    def _build_jog_group(self) -> QGroupBox:
        """Ручной ход (jog): смещение dX/dY на расстояние + скорость (режим manual)."""
        group = QGroupBox("Ручной ход (jog · режим manual)")
        grid = QGridLayout(group)
        grid.addWidget(QLabel("dX, мм:"), 0, 0)
        self._jog_dx = _dspin(-200.0, 200.0, 0.0)
        grid.addWidget(self._jog_dx, 0, 1)
        grid.addWidget(QLabel("dY, мм:"), 0, 2)
        self._jog_dy = _dspin(-200.0, 200.0, 0.0)
        grid.addWidget(self._jog_dy, 0, 3)
        grid.addWidget(QLabel("Скорость, %:"), 0, 4)
        self._jog_spd = QSpinBox()
        self._jog_spd.setRange(1, 100)
        self._jog_spd.setValue(30)
        grid.addWidget(self._jog_spd, 0, 5)

        self._jog_abs = QCheckBox("Абсолют (ехать в координату X/Y)")
        grid.addWidget(self._jog_abs, 1, 0, 1, 3)
        self._btn_jog = QPushButton("Ехать")
        self._btn_jog.setToolTip("Один линейный ход на dX/dY (≤200 мм) при заданной скорости")
        self._btn_jog.clicked.connect(
            lambda: self.jog_requested.emit(
                self._jog_dx.value(), self._jog_dy.value(), self._jog_spd.value(), self._jog_abs.isChecked()
            )
        )
        grid.addWidget(self._btn_jog, 1, 3, 1, 2)
        self._btn_jog_stop = QPushButton("Стоп")
        self._btn_jog_stop.clicked.connect(self.jog_abort_requested.emit)
        grid.addWidget(self._btn_jog_stop, 1, 5)

        hint = QLabel("Сначала режим «manual» (или кнопка «Ехать» включит его), затем jog. Z/RZ не меняются.")
        hint.setWordWrap(True)
        grid.addWidget(hint, 2, 0, 1, 6)
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

    def _build_sketch_group(self) -> QGroupBox:
        """Портрет (рецепт webcam_sketch): заморозка кадра, тюнинг, отправка роботу."""
        group = QGroupBox("Портрет (рецепт webcam_sketch)")
        grid = QGridLayout(group)

        # Камера: заморозка / возобновление
        grid.addWidget(QLabel("Процесс камеры:"), 0, 0)
        self._cam_proc = QLineEdit("camera_0")
        self._cam_proc.setToolTip("Имя процесса камеры в рецепте (по умолчанию «camera_0»)")
        grid.addWidget(self._cam_proc, 0, 1)
        self._btn_freeze = QPushButton("Стоп камеры (заморозить)")
        self._btn_freeze.setToolTip("Заморозить кадр — обработка идёт по статике для тюнинга")
        self._btn_freeze.clicked.connect(
            lambda: self.camera_freeze_requested.emit(self._cam_proc.text().strip() or "camera_0")
        )
        grid.addWidget(self._btn_freeze, 0, 2)
        self._btn_resume = QPushButton("Возобновить камеру")
        self._btn_resume.clicked.connect(
            lambda: self.camera_resume_requested.emit(self._cam_proc.text().strip() or "camera_0")
        )
        grid.addWidget(self._btn_resume, 0, 3)

        # Точки: отправка роботу
        grid.addWidget(QLabel("Процесс точек:"), 1, 0)
        self._points_proc = QLineEdit("points")
        self._points_proc.setToolTip("Имя процесса с robot_draw (по умолчанию «points»)")
        grid.addWidget(self._points_proc, 1, 1)
        self._btn_send = QPushButton("Отправить роботу")
        self._btn_send.setToolTip("Отправить текущую карту точек роботу одной пачкой")
        self._btn_send.clicked.connect(
            lambda: self.send_to_robot_requested.emit(self._points_proc.text().strip() or "points")
        )
        grid.addWidget(self._btn_send, 1, 2, 1, 2)

        hint = QLabel(
            "1) Заморозь кадр → 2) подстрой параметры обработки/прореживания во вкладке "
            "Pipeline → 3) «Отправить роботу». Робот рисует пачку точек и останавливается."
        )
        hint.setWordWrap(True)
        grid.addWidget(hint, 2, 0, 1, 4)
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

    def set_draw_status(self, text: str) -> None:
        """Строка прогресса рисования."""
        self._lbl_draw.setText(text)
