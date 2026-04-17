"""ProcessingTabWidget — color detection, area, display options."""

from __future__ import annotations

from typing import Any, Dict, Optional

from frontend_module.core.qt_imports import (
    QCheckBox, QGroupBox, QHBoxLayout, QLabel,
    QSlider, QSpinBox, Qt, QVBoxLayout, QWidget,
)


class ProcessingTabWidget(QWidget):
    """Processing parameters: color detection (BGR), area, display options."""

    def __init__(
        self,
        registers_manager: Any = None,
        ui: Optional[Dict[str, Any]] = None,
        touch_keyboard: Any = None,
        parent: QWidget = None,
    ):
        super().__init__(parent)
        self._rm = registers_manager
        self._color_lower = [0, 0, 150]
        self._color_upper = [100, 100, 255]
        self._init_ui()
        self._load_from_registers()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # --- Color detection ---
        color_group = QGroupBox("Цветовая детекция (BGR)")
        color_layout = QVBoxLayout(color_group)

        color_layout.addWidget(QLabel("Нижняя граница:"))
        self._sliders_lower = {}
        for i, ch in enumerate(["B", "G", "R"]):
            row = QHBoxLayout()
            lbl = QLabel(f"{ch}:")
            lbl.setFixedWidth(20)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 255)
            slider.setValue(self._color_lower[i])
            val_lbl = QLabel(str(self._color_lower[i]))
            val_lbl.setFixedWidth(35)
            slider.valueChanged.connect(lambda v, l=val_lbl, idx=i: self._on_lower_changed(v, l, idx))
            row.addWidget(lbl)
            row.addWidget(slider)
            row.addWidget(val_lbl)
            color_layout.addLayout(row)
            self._sliders_lower[ch] = (slider, val_lbl)

        color_layout.addWidget(QLabel("Верхняя граница:"))
        self._sliders_upper = {}
        for i, ch in enumerate(["B", "G", "R"]):
            row = QHBoxLayout()
            lbl = QLabel(f"{ch}:")
            lbl.setFixedWidth(20)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 255)
            slider.setValue(self._color_upper[i])
            val_lbl = QLabel(str(self._color_upper[i]))
            val_lbl.setFixedWidth(35)
            slider.valueChanged.connect(lambda v, l=val_lbl, idx=i: self._on_upper_changed(v, l, idx))
            row.addWidget(lbl)
            row.addWidget(slider)
            row.addWidget(val_lbl)
            color_layout.addLayout(row)
            self._sliders_upper[ch] = (slider, val_lbl)

        layout.addWidget(color_group)

        # --- Area ---
        area_group = QGroupBox("Площадь пятна")
        area_layout = QHBoxLayout(area_group)
        area_layout.addWidget(QLabel("Мин:"))
        self._min_area_spin = QSpinBox()
        self._min_area_spin.setRange(10, 5000)
        self._min_area_spin.setValue(500)
        self._min_area_spin.valueChanged.connect(self._on_min_area_changed)
        area_layout.addWidget(self._min_area_spin)
        area_layout.addWidget(QLabel("Макс:"))
        self._max_area_spin = QSpinBox()
        self._max_area_spin.setRange(0, 50000)
        self._max_area_spin.setValue(50000)
        self._max_area_spin.valueChanged.connect(self._on_max_area_changed)
        area_layout.addWidget(self._max_area_spin)
        area_layout.addStretch()
        layout.addWidget(area_group)

        # --- Display options ---
        display_group = QGroupBox("Отображение")
        display_layout = QVBoxLayout(display_group)
        self._checkboxes = {}
        for field_name, label, default in [
            ("show_original", "Оригинал", True),
            ("show_mask", "Маска", True),
            ("draw_contours", "Контуры", True),
            ("draw_bboxes", "BBox", True),
            ("save_frames", "Сохранять кадры", False),
        ]:
            cb = QCheckBox(label)
            cb.setChecked(default)
            cb.toggled.connect(lambda checked, fn=field_name: self._on_display_toggled(fn, checked))
            display_layout.addWidget(cb)
            self._checkboxes[field_name] = cb
        layout.addWidget(display_group)
        layout.addStretch()

    def _load_from_registers(self):
        if not self._rm:
            return
        try:
            for values, sliders_dict in [
                (self._rm.get_field_value("processor", "color_lower"), self._sliders_lower),
                (self._rm.get_field_value("processor", "color_upper"), self._sliders_upper),
            ]:
                if values and len(values) == 3:
                    target = self._color_lower if sliders_dict is self._sliders_lower else self._color_upper
                    for i, ch in enumerate(["B", "G", "R"]):
                        target[i] = values[i]
                        s, l = sliders_dict[ch]
                        s.blockSignals(True)
                        s.setValue(values[i])
                        l.setText(str(values[i]))
                        s.blockSignals(False)

            for spin, field in [(self._min_area_spin, "min_area"), (self._max_area_spin, "max_area")]:
                val = self._rm.get_field_value("processor", field)
                if val is not None:
                    spin.blockSignals(True)
                    spin.setValue(val)
                    spin.blockSignals(False)

            for field_name, cb in self._checkboxes.items():
                val = self._rm.get_field_value("renderer", field_name)
                if val is not None:
                    cb.blockSignals(True)
                    cb.setChecked(bool(val))
                    cb.blockSignals(False)
        except Exception:
            pass

    # --- Handlers ---

    def _on_lower_changed(self, value: int, label, index: int):
        label.setText(str(value))
        self._color_lower[index] = value
        if self._rm:
            try:
                self._rm.set_field_value("processor", "color_lower", list(self._color_lower))
            except Exception:
                pass

    def _on_upper_changed(self, value: int, label, index: int):
        label.setText(str(value))
        self._color_upper[index] = value
        if self._rm:
            try:
                self._rm.set_field_value("processor", "color_upper", list(self._color_upper))
            except Exception:
                pass

    def _on_min_area_changed(self, value: int):
        if self._rm:
            try:
                self._rm.set_field_value("processor", "min_area", value)
            except Exception:
                pass

    def _on_max_area_changed(self, value: int):
        if self._rm:
            try:
                self._rm.set_field_value("processor", "max_area", value)
            except Exception:
                pass

    def _on_display_toggled(self, field_name: str, checked: bool):
        if self._rm:
            try:
                self._rm.set_field_value("renderer", field_name, checked)
            except Exception:
                pass
