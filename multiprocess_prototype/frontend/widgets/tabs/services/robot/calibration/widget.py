# -*- coding: utf-8 -*-
"""CalibrationWizardWidget — панель визарда калибровки камера↔робот.

Виджет «тупой» (View): сигналы наружу на каждый шаг + сеттеры состояния.
Логика (команды cal_*, подписка на прогресс) — в CalibrationController/Presenter.

Три явных шага (по запросу владельца):
  • Шаг 1 — Пиксели: одна кнопка «Зафиксировать» снимает кадр → px 5 точек + энкодер E0.
  • Шаг 2 — Робот: на каждую точку своя кнопка, пишет координаты робота X/Y + энкодер E1.
  • Шаг 3 — Лента: выбор репера, прогон ленты, «Считать E2» → новые координаты робота
    репера (пиксели те же, из Шага 1) + энкодер E2 → масштаб ленты.
UX без красоты (MVP).
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
    """Командная панель калибровки: 3 шага (пиксели · робот · лента) + результат/статус."""

    # --- сигналы наружу ---
    begin_requested = Signal(str, str)  # camera_id, vfd_id
    capture_requested = Signal()  # Шаг 1: «Зафиксировать» (снимок px + E0)
    set_point_requested = Signal(int)  # Шаг 2: «Точка N» (робот X/Y + E1), index 0..4
    belt_run_requested = Signal(float)  # freq_hz
    belt_stop_requested = Signal()
    encoder_scale_requested = Signal(int)  # Шаг 3: репер 0..4 → новый робот + E2
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
        root.addWidget(self._build_step1_group())
        root.addWidget(self._build_step2_group())
        root.addWidget(self._build_step3_group())
        root.addWidget(self._build_result_group())
        root.addWidget(self._build_status_group())
        root.addStretch(1)

    # ------------------------------------------------------------------ #
    # Сессия (Камера / ПЧ + live)
    # ------------------------------------------------------------------ #

    def _build_session_group(self) -> QGroupBox:
        group = QGroupBox("Камера / ПЧ + статус")
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

        # Живая позиция робота (push devices.state.<id>.status) — для контроля перед записью.
        self._lbl_robot_live = QLabel("Робот сейчас: —")
        grid.addWidget(self._lbl_robot_live, 1, 0, 1, 4)
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

    # ------------------------------------------------------------------ #
    # Шаг 1 — Пиксели (снимок камеры)
    # ------------------------------------------------------------------ #

    def _build_step1_group(self) -> QGroupBox:
        group = QGroupBox("Шаг 1 — Пиксели: «Зафиксировать» снимает кадр (px 5 точек + энкодер E0)")
        grid = QGridLayout(group)
        grid.setSpacing(4)
        for col, title in enumerate(("Точка", "px X", "px Y")):
            grid.addWidget(QLabel(title), 0, col)

        self._px_x: list[QDoubleSpinBox] = []
        self._px_y: list[QDoubleSpinBox] = []
        for i in range(_NUM_POINTS):
            r = i + 1
            grid.addWidget(QLabel(f"Точка {i + 1}"), r, 0)
            pxx = self._make_coord_spin(0, 8000, 0, " px")
            pxy = self._make_coord_spin(0, 8000, 0, " px")
            grid.addWidget(pxx, r, 1)
            grid.addWidget(pxy, r, 2)
            # editingFinished (не valueChanged): программный fill идёт с blockSignals,
            # пользовательская правка ловится только при завершении ввода/потере фокуса.
            pxx.editingFinished.connect(lambda idx=i: self._emit_px(idx))
            pxy.editingFinished.connect(lambda idx=i: self._emit_px(idx))
            self._px_x.append(pxx)
            self._px_y.append(pxy)

        self._btn_capture = QPushButton("Зафиксировать (снимок 5 точек)")
        self._btn_capture.setToolTip("Снять кадр: записать пиксели 5 найденных точек и энкодер E0")
        self._btn_capture.clicked.connect(self.capture_requested.emit)
        grid.addWidget(self._btn_capture, _NUM_POINTS + 1, 0, 1, 3)

        self._lbl_found = QLabel("Найдено: — (live: 0/5)")
        grid.addWidget(self._lbl_found, _NUM_POINTS + 2, 0, 1, 3)
        self._lbl_e0 = QLabel("Энкодер E0 (снимок): —")
        grid.addWidget(self._lbl_e0, _NUM_POINTS + 3, 0, 1, 3)
        return group

    # ------------------------------------------------------------------ #
    # Шаг 2 — Координаты робота
    # ------------------------------------------------------------------ #

    def _build_step2_group(self) -> QGroupBox:
        group = QGroupBox("Шаг 2 — Робот: «Точка N» пишет робота X/Y (px — зафиксированные из Шага 1; E1 один на всех)")
        grid = QGridLayout(group)
        grid.setSpacing(4)
        for col, title in enumerate(("Точка", "px X (фикс.)", "px Y (фикс.)", "робот X, мм", "робот Y, мм")):
            grid.addWidget(QLabel(title), 0, col)

        self._point_buttons: list[QPushButton] = []
        self._px2_x: list[QDoubleSpinBox] = []  # зафиксированные пиксели (read-only зеркало Шага 1)
        self._px2_y: list[QDoubleSpinBox] = []
        self._rb_x: list[QDoubleSpinBox] = []
        self._rb_y: list[QDoubleSpinBox] = []
        for i in range(_NUM_POINTS):
            r = i + 1
            btn = QPushButton(f"Точка {i + 1}")
            btn.setToolTip("Записать координаты робота для этой точки (текущая телеметрия)")
            btn.clicked.connect(lambda _checked=False, idx=i: self.set_point_requested.emit(idx))
            grid.addWidget(btn, r, 0)
            self._point_buttons.append(btn)

            px2x = self._make_coord_spin(0, 8000, 0, " px", readonly=True)
            px2y = self._make_coord_spin(0, 8000, 0, " px", readonly=True)
            grid.addWidget(px2x, r, 1)
            grid.addWidget(px2y, r, 2)
            self._px2_x.append(px2x)
            self._px2_y.append(px2y)

            rbx = self._make_coord_spin(-100000.0, 100000.0, 2, "")
            rby = self._make_coord_spin(-100000.0, 100000.0, 2, "")
            grid.addWidget(rbx, r, 3)
            grid.addWidget(rby, r, 4)
            rbx.editingFinished.connect(lambda idx=i: self._emit_robot(idx))
            rby.editingFinished.connect(lambda idx=i: self._emit_robot(idx))
            self._rb_x.append(rbx)
            self._rb_y.append(rby)

        self._lbl_e1 = QLabel("Энкодер E1 (робот): —")
        grid.addWidget(self._lbl_e1, _NUM_POINTS + 1, 0, 1, 5)
        self._lbl_points = QLabel("Собрано: 0/5")
        grid.addWidget(self._lbl_points, _NUM_POINTS + 2, 0, 1, 5)
        return group

    # ------------------------------------------------------------------ #
    # Шаг 3 — Масштаб ленты (репер после прогона)
    # ------------------------------------------------------------------ #

    def _build_step3_group(self) -> QGroupBox:
        group = QGroupBox("Шаг 3 — Лента: прогон + повторное касание репера (px те же, новый робот + E2)")
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
        self._spin_ref.setValue(_NUM_POINTS)  # по умолчанию центр (точка 5)
        grid.addWidget(self._spin_ref, 1, 1)
        self._btn_scale = QPushButton("Считать E2 (после ленты) + расчёт")
        self._btn_scale.setToolTip(
            "После прогона ленты заново коснись репера: пишет новые координаты робота + E2, "
            "считает масштаб ленты и дистанцию камера→робот (пиксели берутся из Шага 1)"
        )
        self._btn_scale.clicked.connect(lambda: self.encoder_scale_requested.emit(self._spin_ref.value() - 1))
        grid.addWidget(self._btn_scale, 1, 2, 1, 2)

        # Показ результата повторного касания репера: те же px (Шаг 1) + новый робот + E2.
        self._lbl_step3_px = QLabel("Репер px (из Шага 1): —")
        grid.addWidget(self._lbl_step3_px, 2, 0, 1, 4)
        self._lbl_step3_robot = QLabel("Новые координаты робота: —")
        grid.addWidget(self._lbl_step3_robot, 3, 0, 1, 4)
        self._lbl_e2 = QLabel("Энкодер E2 (после ленты): —")
        grid.addWidget(self._lbl_e2, 4, 0, 1, 4)
        self._lbl_scale = QLabel("Масштаб ленты: —")
        self._lbl_scale.setWordWrap(True)
        grid.addWidget(self._lbl_scale, 5, 0, 1, 4)
        return group

    # ------------------------------------------------------------------ #
    # Общие хелперы полей
    # ------------------------------------------------------------------ #

    @staticmethod
    def _make_coord_spin(lo: float, hi: float, decimals: int, suffix: str, readonly: bool = False) -> QDoubleSpinBox:
        """Компактный QDoubleSpinBox для координаты (без стрелок-кнопок).

        readonly=True — поле только для показа (зафиксированные значения, не правятся).
        """
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(decimals)
        if suffix:
            sp.setSuffix(suffix)
        sp.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        if readonly:
            sp.setReadOnly(True)
            sp.setFocusPolicy(sp.focusPolicy().NoFocus)
            sp.setStyleSheet("QDoubleSpinBox { background: #f0f0f0; color: #444; }")
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

    @staticmethod
    def _fmt_xy(val, dec: int = 0) -> str:
        """Форматировать пару [x,y] для метки (или «—» если нет)."""
        if not val or len(val) < 2:
            return "—"
        return f"X={float(val[0]):.{dec}f}  Y={float(val[1]):.{dec}f}"

    def _build_result_group(self) -> QGroupBox:
        group = QGroupBox("Вычислить и сохранить")
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

        # Покоординатно: заполнить поля px (Шаг 1) / робот (Шаг 2) из снапшота.
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
            # Шаг 2: зафиксированные пиксели (только после захвата) — read-only зеркало Шага 1.
            fixed_px = px[i] if (captured and i < len(px)) else None
            self._set_spin_pair(self._px2_x[i], self._px2_y[i], fixed_px)

        # Три замера энкодера по шагам: E0 (снимок) · E1 (робот) · E2 (после ленты).
        def _e(v) -> str:
            return "—" if v is None else str(int(v))

        self._lbl_e0.setText(f"Энкодер E0 (снимок): {_e(snap.get('e0'))}")
        self._lbl_e1.setText(f"Энкодер E1 (робот): {_e(snap.get('e1'))}")
        self._lbl_e2.setText(f"Энкодер E2 (после ленты): {_e(snap.get('e2'))}")

        # Шаг 3: репер (из snapshot или текущего выбора) — те же px + новые координаты робота.
        belt_ref = snap.get("belt_ref")
        ref_idx = belt_ref if belt_ref is not None else (self._spin_ref.value() - 1)
        ref_px = px[ref_idx] if 0 <= ref_idx < len(px) else None
        self._lbl_step3_px.setText(f"Репер (точка {ref_idx + 1}) px из Шага 1: {self._fmt_xy(ref_px)}")
        self._lbl_step3_robot.setText(f"Новые координаты робота: {self._fmt_xy(snap.get('belt_mm2'), dec=1)}")

        if snap.get("scale_done"):
            mpc = snap.get("mm_per_count")
            belt = snap.get("belt_dir") or [0.0, 0.0]
            dist = snap.get("camera_to_robot_mm")
            dist_txt = f", камера→робот {dist:.1f} мм" if dist is not None else ""
            self._lbl_scale.setText(
                f"Масштаб ленты: {mpc:.5f} мм/count, направление ({belt[0]:.3f}, {belt[1]:.3f}){dist_txt}"
            )
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
            self._btn_capture,
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
