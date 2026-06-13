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
        group = QGroupBox("1. Сессия и кадр эталона")
        grid = QGridLayout(group)
        grid.addWidget(QLabel("Camera ID:"), 0, 0)
        self._edit_camera = QLineEdit("cam0")
        grid.addWidget(self._edit_camera, 0, 1)
        grid.addWidget(QLabel("VFD ID:"), 0, 2)
        self._edit_vfd = QLineEdit("vfd_belt")
        grid.addWidget(self._edit_vfd, 0, 3)

        self._btn_begin = QPushButton("Начать сессию")
        self._btn_begin.clicked.connect(
            lambda: self.begin_requested.emit(self._edit_camera.text().strip(), self._edit_vfd.text().strip())
        )
        grid.addWidget(self._btn_begin, 1, 0, 1, 2)

        self._btn_capture = QPushButton("Снять кадр (5 точек)")
        self._btn_capture.clicked.connect(self.capture_requested.emit)
        grid.addWidget(self._btn_capture, 1, 2, 1, 2)

        self._lbl_found = QLabel("Найдено: — (live: 0/5)")
        grid.addWidget(self._lbl_found, 2, 0, 1, 4)
        return group

    def _build_points_group(self) -> QGroupBox:
        group = QGroupBox("2. Навести робота на точки (по разу)")
        layout = QVBoxLayout(group)
        row = QHBoxLayout()
        self._point_buttons: list[QPushButton] = []
        for i in range(_NUM_POINTS):
            btn = QPushButton(f"Точка {i + 1}")
            btn.clicked.connect(lambda _checked=False, idx=i: self.set_point_requested.emit(idx))
            row.addWidget(btn)
            self._point_buttons.append(btn)
        layout.addLayout(row)
        self._lbl_points = QLabel("Собрано: 0/5")
        layout.addWidget(self._lbl_points)
        return group

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
        return self._edit_camera.text().strip()

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
            self._btn_begin,
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
