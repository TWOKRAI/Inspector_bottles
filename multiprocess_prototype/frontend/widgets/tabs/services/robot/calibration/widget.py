# -*- coding: utf-8 -*-
"""CalibrationWizardWidget — панель визарда калибровки камера↔робот.

Виджет «тупой» (View): сигналы наружу на каждый шаг + сеттеры состояния.
Логика (команды cal_*, подписка на прогресс) — в CalibrationController/Presenter.

Порядок шагов: Начать сессию → Снять кадр (5 точек) → Навести робота на точки 1..5
→ Прогон ленты + Снять масштаб (репер) → Вычислить → Сохранить. UX без красоты (MVP).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
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

_NUM_POINTS = 5


class CalibrationWizardWidget(QWidget):
    """Командная панель калибровки: кнопки шагов + статус/прогресс."""

    # --- сигналы наружу ---
    begin_requested = Signal(str, str)  # camera_id, vfd_id
    capture_requested = Signal()
    set_point_requested = Signal(int)  # index 0..4
    belt_run_requested = Signal(float)  # freq_hz
    belt_stop_requested = Signal()
    encoder_scale_requested = Signal(int)  # ref_index 0..4
    compute_requested = Signal()
    save_requested = Signal()
    reset_requested = Signal()
    point_px_edited = Signal(int, float, float)  # index, px_x, px_y — ручная правка пикселей
    point_robot_edited = Signal(int, float, float)  # index, robot_x, robot_y — ручная правка мм робота

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        root.addWidget(self._build_session_group())
        root.addWidget(self._build_points_group())
        root.addWidget(self._build_belt_group())
        root.addWidget(self._build_result_group())
        root.addWidget(self._build_status_group())
        root.addStretch(1)

    # ------------------------------------------------------------------ #
    # Группы
    # ------------------------------------------------------------------ #

    def _build_session_group(self) -> QGroupBox:
        group = QGroupBox("1. Камера / ПЧ + статус")
        grid = QGridLayout(group)
        grid.addWidget(QLabel("Камера:"), 0, 0)
        self._edit_camera = QComboBox()
        self._edit_camera.setEditable(True)
        self._edit_camera.addItem("cam0")
        grid.addWidget(self._edit_camera, 0, 1)
        grid.addWidget(QLabel("ПЧ (VFD):"), 0, 2)
        self._edit_vfd = QComboBox()
        self._edit_vfd.setEditable(True)
        self._edit_vfd.addItem("vfd_belt")
        grid.addWidget(self._edit_vfd, 0, 3)
        # Выбор камеры/ПЧ из списка → перезапуск сессии (заменяет кнопку «Начать сессию»).
        self._edit_camera.activated.connect(lambda _i: self._emit_begin())
        self._edit_vfd.activated.connect(lambda _i: self._emit_begin())

        self._lbl_found = QLabel("Найдено: — (live: 0/5)")
        grid.addWidget(self._lbl_found, 1, 0, 1, 4)
        # Живая позиция робота (push devices.state.<id>.status) — для контроля перед записью.
        self._lbl_robot_live = QLabel("Робот сейчас: —")
        grid.addWidget(self._lbl_robot_live, 2, 0, 1, 4)
        return group

    def _emit_begin(self) -> None:
        """Старт/перезапуск сессии калибровки для выбранной камеры/ПЧ."""
        self.begin_requested.emit(self.camera_id, self.vfd_id)

    def set_camera_options(self, ids: list[str]) -> None:
        """Заполнить список камер (сохранив текущее значение)."""
        self._set_combo_options(self._edit_camera, ids)

    def set_vfd_options(self, ids: list[str]) -> None:
        """Заполнить список ПЧ (сохранив текущее значение)."""
        self._set_combo_options(self._edit_vfd, ids)

    @staticmethod
    def _set_combo_options(combo: QComboBox, ids: list[str]) -> None:
        cur = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        for i in ids:
            combo.addItem(str(i))
        if cur and combo.findText(cur) < 0:
            combo.addItem(cur)
        combo.setCurrentText(cur or (ids[0] if ids else ""))
        combo.blockSignals(False)

    def set_robot_live(self, x: float, y: float, enc: int | None) -> None:
        """Обновить метку «Робот сейчас» (live push-телеметрия)."""
        self._lbl_robot_live.setText(f"Робот сейчас: X={x:.1f}  Y={y:.1f}  энкодер={enc if enc is not None else '—'}")

    def _build_points_group(self) -> QGroupBox:
        group = QGroupBox("2. Точки: кнопка пишет координаты робота · px и мм видны и правятся вручную")
        grid = QGridLayout(group)
        grid.setSpacing(4)
        # Заголовки колонок
        for col, title in enumerate(("Точка", "px X", "px Y", "робот X, мм", "робот Y, мм")):
            grid.addWidget(QLabel(title), 0, col)

        self._point_buttons: list[QPushButton] = []
        self._px_x: list[QDoubleSpinBox] = []
        self._px_y: list[QDoubleSpinBox] = []
        self._rb_x: list[QDoubleSpinBox] = []
        self._rb_y: list[QDoubleSpinBox] = []
        for i in range(_NUM_POINTS):
            r = i + 1
            btn = QPushButton(f"Точка {i + 1}")
            btn.setToolTip("Записать координаты робота для этой точки (текущая телеметрия)")
            btn.clicked.connect(lambda _checked=False, idx=i: self.set_point_requested.emit(idx))
            grid.addWidget(btn, r, 0)
            self._point_buttons.append(btn)

            pxx = self._make_coord_spin(0, 8000, 0, " px")
            pxy = self._make_coord_spin(0, 8000, 0, " px")
            rbx = self._make_coord_spin(-100000.0, 100000.0, 2, "")
            rby = self._make_coord_spin(-100000.0, 100000.0, 2, "")
            grid.addWidget(pxx, r, 1)
            grid.addWidget(pxy, r, 2)
            grid.addWidget(rbx, r, 3)
            grid.addWidget(rby, r, 4)
            # editingFinished (не valueChanged): программный fill идёт с blockSignals,
            # пользовательская правка ловится только при завершении ввода/потере фокуса.
            pxx.editingFinished.connect(lambda idx=i: self._emit_px(idx))
            pxy.editingFinished.connect(lambda idx=i: self._emit_px(idx))
            rbx.editingFinished.connect(lambda idx=i: self._emit_robot(idx))
            rby.editingFinished.connect(lambda idx=i: self._emit_robot(idx))
            self._px_x.append(pxx)
            self._px_y.append(pxy)
            self._rb_x.append(rbx)
            self._rb_y.append(rby)

        self._lbl_points = QLabel("Собрано: 0/5")
        grid.addWidget(self._lbl_points, _NUM_POINTS + 1, 0, 1, 5)
        return group

    @staticmethod
    def _make_coord_spin(lo: float, hi: float, decimals: int, suffix: str) -> QDoubleSpinBox:
        """Компактный QDoubleSpinBox для координаты (без стрелок-кнопок)."""
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(decimals)
        if suffix:
            sp.setSuffix(suffix)
        sp.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        return sp

    def _emit_px(self, i: int) -> None:
        self.point_px_edited.emit(i, float(self._px_x[i].value()), float(self._px_y[i].value()))

    def _emit_robot(self, i: int) -> None:
        self.point_robot_edited.emit(i, float(self._rb_x[i].value()), float(self._rb_y[i].value()))

    def _set_spin_pair(self, sx: QDoubleSpinBox, sy: QDoubleSpinBox, val) -> None:
        """Заполнить пару полей из [x,y]; None — не трогать; не перебивать активную правку."""
        if val is None or len(val) < 2:
            return
        for sp, v in ((sx, val[0]), (sy, val[1])):
            if sp.hasFocus():  # пользователь сейчас правит — не затирать
                continue
            sp.blockSignals(True)
            sp.setValue(float(v))
            sp.blockSignals(False)

    def _build_belt_group(self) -> QGroupBox:
        group = QGroupBox("3. Масштаб ленты (прогон + 1 повторное касание)")
        grid = QGridLayout(group)
        grid.addWidget(QLabel("Частота, Гц:"), 0, 0)
        self._spin_freq = QDoubleSpinBox()
        self._spin_freq.setRange(0.0, 50.0)
        self._spin_freq.setDecimals(2)
        self._spin_freq.setValue(10.0)
        grid.addWidget(self._spin_freq, 0, 1)
        self._btn_belt_run = QPushButton("Лента: Пуск")
        self._btn_belt_run.clicked.connect(lambda: self.belt_run_requested.emit(self._spin_freq.value()))
        grid.addWidget(self._btn_belt_run, 0, 2)
        self._btn_belt_stop = QPushButton("Лента: Стоп")
        self._btn_belt_stop.clicked.connect(self.belt_stop_requested.emit)
        grid.addWidget(self._btn_belt_stop, 0, 3)

        grid.addWidget(QLabel("Репер — точка №:"), 1, 0)
        self._spin_ref = QSpinBox()
        self._spin_ref.setRange(1, _NUM_POINTS)
        self._spin_ref.setValue(1)
        grid.addWidget(self._spin_ref, 1, 1)
        self._btn_scale = QPushButton("Снять масштаб (повторное касание)")
        self._btn_scale.clicked.connect(lambda: self.encoder_scale_requested.emit(self._spin_ref.value() - 1))
        grid.addWidget(self._btn_scale, 1, 2, 1, 2)

        self._lbl_scale = QLabel("Масштаб ленты: —")
        grid.addWidget(self._lbl_scale, 2, 0, 1, 4)
        return group

    def _build_result_group(self) -> QGroupBox:
        group = QGroupBox("4. Вычислить и сохранить")
        layout = QVBoxLayout(group)
        row = QHBoxLayout()
        self._btn_compute = QPushButton("Вычислить")
        self._btn_compute.clicked.connect(self.compute_requested.emit)
        row.addWidget(self._btn_compute)
        self._btn_save = QPushButton("Сохранить")
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self.save_requested.emit)
        row.addWidget(self._btn_save)
        self._btn_reset = QPushButton("Сброс")
        self._btn_reset.clicked.connect(self.reset_requested.emit)
        row.addWidget(self._btn_reset)
        row.addStretch(1)
        layout.addLayout(row)
        self._lbl_reproj = QLabel("Reproj: —")
        self._lbl_reproj.setWordWrap(True)
        layout.addWidget(self._lbl_reproj)
        self._lbl_saved = QLabel("")
        self._lbl_saved.setWordWrap(True)
        layout.addWidget(self._lbl_saved)
        return group

    def _build_status_group(self) -> QGroupBox:
        group = QGroupBox("Статус")
        layout = QVBoxLayout(group)
        self._lbl_status = QLabel("Калибровка: выберите робота и нажмите «Начать сессию».")
        self._lbl_status.setWordWrap(True)
        layout.addWidget(self._lbl_status)
        self._lbl_error = QLabel("")
        self._lbl_error.setWordWrap(True)
        self._lbl_error.setStyleSheet("color: #c0392b;")
        layout.addWidget(self._lbl_error)
        return group

    # ------------------------------------------------------------------ #
    # Сеттеры (вызывает контроллер)
    # ------------------------------------------------------------------ #

    @property
    def camera_id(self) -> str:
        return self._edit_camera.currentText().strip()

    @property
    def vfd_id(self) -> str:
        return self._edit_vfd.currentText().strip()

    def set_status(self, text: str) -> None:
        self._lbl_status.setText(text)

    def set_progress(self, snap: dict[str, Any]) -> None:
        """Обновить виджет по snapshot прогресса из state-дерева."""
        if not isinstance(snap, dict):
            return
        expected = snap.get("expected_points", _NUM_POINTS)
        live = snap.get("live_found", 0)
        found = "снято" if snap.get("captured") else "—"
        self._lbl_found.setText(f"Найдено: {found} (live: {live}/{expected})")
        self._lbl_points.setText(f"Собрано: {snap.get('points_collected', 0)}/{expected}")

        # Покоординатно: заполнить поля px / робот из снапшота (правка вручную не затирается).
        # px: после захвата — зафиксированные (snap["px"]); ДО захвата — live (real-time).
        captured = bool(snap.get("captured"))
        px = snap.get("px") or []
        live_px = snap.get("live_px") or []
        mm = snap.get("mm") or []
        for i in range(_NUM_POINTS):
            if captured:
                px_val = px[i] if i < len(px) else None
            else:
                px_val = live_px[i] if i < len(live_px) else None
            self._set_spin_pair(self._px_x[i], self._px_y[i], px_val)
            self._set_spin_pair(self._rb_x[i], self._rb_y[i], mm[i] if i < len(mm) else None)

        if snap.get("scale_done"):
            mpc = snap.get("mm_per_count")
            belt = snap.get("belt_dir") or [0.0, 0.0]
            self._lbl_scale.setText(f"Масштаб ленты: {mpc:.5f} мм/count, направление ({belt[0]:.3f}, {belt[1]:.3f})")
        else:
            self._lbl_scale.setText("Масштаб ленты: —")

        reproj = snap.get("reproj")
        passed = bool(snap.get("passed"))
        if isinstance(reproj, dict):
            verdict = "OK ✓" if passed else "ПОРОГ ПРЕВЫШЕН ✗"
            self._lbl_reproj.setText(
                f"Reproj: центр={reproj.get('center')}мм mean={reproj.get('mean')} "
                f"max={reproj.get('max')} (порог {snap.get('reproj_threshold_mm')}) → {verdict}"
            )
        else:
            self._lbl_reproj.setText("Reproj: —")
        self._btn_save.setEnabled(passed)

        saved = snap.get("saved_path")
        self._lbl_saved.setText(f"Сохранено: {saved}" if saved else "")

        msg = snap.get("message") or ""
        if msg:
            self._lbl_status.setText(msg)
        self._lbl_error.setText(snap.get("error") or "")

    def set_controls_enabled(self, enabled: bool, hint: str = "") -> None:
        for btn in (
            self._btn_belt_run,
            self._btn_belt_stop,
            self._btn_scale,
            self._btn_compute,
            self._btn_reset,
            *self._point_buttons,
        ):
            btn.setEnabled(enabled)
        if not enabled:
            self._btn_save.setEnabled(False)
        if hint:
            self._lbl_status.setText(hint)
