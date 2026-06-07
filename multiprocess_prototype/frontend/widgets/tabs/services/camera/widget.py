"""CameraSettingsWidget — подробный UI настроек вебкамеры (Services-фасад).

Пресеты (разрешение/FPS), MJPG-toggle, слайдеры всех физических параметров
(каталог WEBCAM_PARAMS), read-only панель actual (привязка к state store делает
секция через bindings). Без cv2 — все правки уходят сигналами в presenter (IPC).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from Plugins.sources.camera_service.backends.webcam_controls import (
    FPS_PRESETS,
    RESOLUTION_PRESETS,
    WEBCAM_PARAMS,
)


class CameraSettingsWidget(QWidget):
    """Подробный фасад настроек камеры. Все правки — через сигналы (presenter → IPC).

    Signals:
        param_changed(name, value): слайдер/чекбокс параметра отпущен.
        resolution_changed(width, height): выбран пресет разрешения.
        fps_changed(fps): выбран пресет FPS.
        mjpg_changed(on): переключён MJPG.
        save_clicked(): нажата «Сохранить» (persist в рецепт).
    """

    param_changed = Signal(str, object)
    resolution_changed = Signal(int, int)
    fps_changed = Signal(int)
    mjpg_changed = Signal(bool)
    save_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.actual_labels: dict[str, QLabel] = {}
        self._build_ui()

    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Подсказка-статус (live недоступен и т.п.)
        self._status = QLabel("")
        self._status.setProperty("role", "placeholder-italic")
        self._status.setWordWrap(True)
        self._status.hide()
        root.addWidget(self._status)

        # --- Пресеты ---
        presets = QGroupBox("Пресеты")
        pform = QFormLayout(presets)
        self._res_combo = QComboBox()
        for w, h in RESOLUTION_PRESETS:
            self._res_combo.addItem(f"{w}×{h}", (w, h))
        self._res_combo.activated.connect(self._on_resolution)
        pform.addRow("Разрешение:", self._res_combo)

        self._fps_combo = QComboBox()
        for f in FPS_PRESETS:
            self._fps_combo.addItem(f"{f} fps", f)
        self._fps_combo.activated.connect(self._on_fps)
        pform.addRow("FPS:", self._fps_combo)

        self._mjpg_check = QCheckBox("MJPG (снимает потолок ~15fps DirectShow)")
        self._mjpg_check.toggled.connect(self.mjpg_changed.emit)
        pform.addRow("Кодек:", self._mjpg_check)
        root.addWidget(presets)

        # --- Параметры (полный каталог) ---
        params_group = QGroupBox("Параметры камеры")
        pg_layout = QVBoxLayout(params_group)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self._params_form = QFormLayout(inner)
        self._params_form.setSpacing(6)
        for name, spec in WEBCAM_PARAMS.items():
            self._add_param_row(name, spec)
        scroll.setWidget(inner)
        pg_layout.addWidget(scroll)
        root.addWidget(params_group, stretch=1)

        # --- Actual (read-only, привязка делает секция) ---
        actual_group = QGroupBox("Actual (что камера применила)")
        aform = QFormLayout(actual_group)
        for key, caption in (
            ("fps", "FPS:"),
            ("resolution", "Разрешение:"),
            ("exposure", "Экспозиция:"),
            ("gain", "Усиление:"),
            ("fourcc", "Кодек:"),
        ):
            lbl = QLabel("—")
            self.actual_labels[key] = lbl
            aform.addRow(caption, lbl)
        root.addWidget(actual_group)

        # --- Сохранить ---
        self._save_btn = QPushButton("Сохранить в рецепт")
        self._save_btn.clicked.connect(self.save_clicked.emit)
        root.addWidget(self._save_btn)

    def _add_param_row(self, name: str, spec: Any) -> None:
        """Добавить строку параметра: bool → checkbox, число → slider + значение."""
        label = f"{spec.label}" + (f" ({spec.unit})" if spec.unit else "")
        if spec.kind == "bool":
            chk = QCheckBox()
            chk.toggled.connect(lambda on, n=name: self.param_changed.emit(n, bool(on)))
            self._params_form.addRow(label + ":", chk)
            return

        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        slider = QSlider(Qt.Orientation.Horizontal)
        lo = int(spec.min if spec.min is not None else 0)
        hi = int(spec.max if spec.max is not None else 255)
        slider.setRange(lo, hi)
        value_lbl = QLabel(str(lo))
        value_lbl.setMinimumWidth(40)
        value_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        slider.valueChanged.connect(lambda v, lbl=value_lbl: lbl.setText(str(v)))
        # Применяем по отпусканию (не на каждый tick — меньше IPC-спама).
        slider.sliderReleased.connect(lambda n=name, s=slider: self.param_changed.emit(n, s.value()))
        h.addWidget(slider, 1)
        h.addWidget(value_lbl)
        self._params_form.addRow(label + ":", row)

    # ------------------------------------------------------------------ #

    def _on_resolution(self, index: int) -> None:
        data = self._res_combo.itemData(index)
        if data:
            self.resolution_changed.emit(int(data[0]), int(data[1]))

    def _on_fps(self, index: int) -> None:
        data = self._fps_combo.itemData(index)
        if data is not None:
            self.fps_changed.emit(int(data))

    def set_status(self, text: str) -> None:
        """Показать/скрыть строку-подсказку (live недоступен и т.п.)."""
        if text:
            self._status.setText(text)
            self._status.show()
        else:
            self._status.hide()

    def set_controls_enabled(self, enabled: bool) -> None:
        """Включить/выключить контролы (live недоступен → серые)."""
        for w in (self._res_combo, self._fps_combo, self._mjpg_check, self._save_btn):
            w.setEnabled(enabled)
