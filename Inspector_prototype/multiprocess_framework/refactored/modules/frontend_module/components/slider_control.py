# -*- coding: utf-8 -*-
"""
SliderControl — слайдер с привязкой к регистру.

Соответствует SliderControlEnhanced из App. Читает min, max, unit, transfer_k, round_k
из метаданных. Поддерживает observer, ui_elements, controls, callback, touch keyboard.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

try:
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtGui import QFont, QDoubleValidator, QIntValidator
    from PyQt5.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QMessageBox, QSlider, QWidget
    _HAS_QT = True
except ImportError:
    _HAS_QT = False

from frontend_module.core.base_configurable_widget import BaseConfigurableWidget


def _first_not_none(*values: Any) -> Any:
    """Первый не-None из значений."""
    for v in values:
        if v is not None:
            return v
    return None


class SliderControl(BaseConfigurableWidget):
    """
    Слайдер с автоматической настройкой из метаданных регистра.

    Использование:
        slider = SliderControl(
            register_name="draw",
            field_name="dp",
            registers_manager=rm,
            parent=parent,
        )
    """

    def __init__(
        self,
        register_name: Optional[str] = None,
        field_name: Optional[str] = None,
        registers_manager: Optional[Any] = None,
        access_level: int = 0,
        parent: Optional[Any] = None,
        label: Optional[str] = None,
        transfer_k: Optional[float] = None,
        round_k: Optional[int] = None,
        ui_elements: Optional[dict] = None,
        controls: Optional[Any] = None,
        callback: Optional[Callable[..., None]] = None,
        touch_keyboard_factory: Optional[Callable[[], Any]] = None,
        **kwargs: Any,
    ) -> None:
        self._label_widget: Optional[Any] = None
        self._value_input: Optional[Any] = None
        self._slider: Optional[Any] = None
        self._value: Any = None
        self._transfer_k: float = 1.0
        self._round_k: int = 0
        self._custom_label = label
        self._transfer_k_override = transfer_k
        self._round_k_override = round_k
        self._block_signals = False
        self._ui_elements = ui_elements or (getattr(parent, "ui_elements", None) if parent else None)
        self._controls = controls if controls is not None else (getattr(parent, "controls", None) if parent else None)
        self._callback = callback or (getattr(parent, "update_controls", None) if parent else None)
        self._touch_keyboard_factory = touch_keyboard_factory

        super().__init__(
            register_name=register_name,
            field_name=field_name,
            registers_manager=registers_manager,
            access_level=access_level,
            parent=parent,
            **kwargs,
        )

    def _transfer_value(self, raw: Any) -> Any:
        """Преобразование значения слайдера в реальное."""
        v = float(raw) * self._transfer_k
        return int(round(v)) if self._round_k == 0 else round(v, self._round_k)

    def _slider_value_from_real(self, real: Any) -> int:
        """Реальное значение в позицию слайдера."""
        v = float(real) / self._transfer_k if self._transfer_k else float(real)
        return int(round(v))

    def _load_metadata(self) -> None:
        if not _HAS_QT or not all([self._registers_manager, self._register_name, self._field_name]):
            return

        meta = self.get_metadata()
        if not meta:
            return

        min_val = _first_not_none(meta.get("min"), 0) or 0
        max_val = _first_not_none(meta.get("max"), 100) or 100
        default_val = meta.get("default", min_val)
        description = meta.get("info") or meta.get("description", self._field_name)
        unit = meta.get("unit", "")

        self._transfer_k = _first_not_none(
            self._transfer_k_override, meta.get("transfer_k"), 1.0
        ) or 1.0
        self._round_k = _first_not_none(
            self._round_k_override,
            meta.get("round_k"),
            1 if isinstance(default_val, float) else 0,
        )
        if self._round_k is None:
            self._round_k = 0

        can_modify = self._can_modify()
        current = self.get_field_value() or default_val
        if self._slider is not None:
            self._value = self._transfer_value(self._slider_value_from_real(current))
        else:
            self._value = float(current) if isinstance(current, (int, float)) else current

        layout = self.layout()
        if layout is None:
            layout = QHBoxLayout(self)
            self.setLayout(layout)

        font = QFont("Arial", 11)
        display_label = self._custom_label or description
        if unit:
            display_label += f" ({unit})"

        if self._label_widget is None:
            self._label_widget = QLabel(display_label)
            self._label_widget.setFont(font)
            self._label_widget.setWordWrap(True)
            self._label_widget.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            layout.addWidget(self._label_widget, 3)
        else:
            self._label_widget.setText(display_label)
        self._label_widget.setToolTip(description)

        if self._value_input is None:
            self._value_input = QLineEdit()
            self._value_input.setFont(QFont("Arial", 12))
            self._value_input.setFixedSize(60, 30)
            self._value_input.setAlignment(Qt.AlignCenter)
            self._value_input.editingFinished.connect(self._on_input_finished)
            if self._touch_keyboard_factory:
                self._value_input.mousePressEvent = self._show_touch_keyboard
            layout.addSpacing(5)
            layout.addWidget(self._value_input)
            layout.addSpacing(20)

        self._value_input.setText(str(self._value))
        self._value_input.setEnabled(can_modify)
        validator = QIntValidator() if self._round_k == 0 else QDoubleValidator()
        if hasattr(validator, "setNotation"):
            validator.setNotation(QDoubleValidator.StandardNotation)
        self._value_input.setValidator(validator)

        if self._slider is None:
            self._slider = QSlider(Qt.Horizontal)
            self._slider.setMinimumHeight(45)
            self._slider.valueChanged.connect(self._on_slider_changed)
            self._slider.wheelEvent = lambda e: None
            self._slider.setStyleSheet("""
                QSlider::handle:horizontal {
                    height: 50px; width: 25px; margin: -15px 0;
                    border: 2px solid #4682B4; border-radius: 7px; background: gray;
                }
            """)
            layout.addWidget(self._slider, 17)
            layout.addSpacing(25)

        self._slider.setMinimum(int(min_val / self._transfer_k) if self._transfer_k != 1 else min_val)
        self._slider.setMaximum(int(max_val / self._transfer_k) if self._transfer_k != 1 else max_val)
        slider_pos = max(
            self._slider.minimum(),
            min(self._slider_value_from_real(current), self._slider.maximum()),
        )
        self._slider.blockSignals(True)
        try:
            self._slider.setValue(slider_pos)
            self._value = self._transfer_value(slider_pos)
        finally:
            self._slider.blockSignals(False)
        self._slider.setEnabled(can_modify)

        if self._ui_elements is not None:
            self._ui_elements[self._field_name] = {
                "element": self._slider,
                "value": self._value,
                "min_access": meta.get("access_level", 0),
                "transfer_k": self._transfer_k,
                "round_k": self._round_k,
            }
        if self._controls is not None:
            if isinstance(self._controls, list):
                for ctrl in self._controls:
                    ctrl[self._field_name] = self._value
            else:
                self._controls[self._field_name] = self._value

    def _update_access_level(self) -> None:
        if self._slider and self._value_input:
            can = self._can_modify()
            self._slider.setEnabled(can)
            self._value_input.setEnabled(can)

    def _on_slider_changed(self, value: int) -> None:
        self._value = self._transfer_value(value)
        if self._value_input:
            self._value_input.setText(str(self._value))
        if not self._block_signals:
            self._block_signals = True
            QTimer.singleShot(100, self._flush_value)

    def _on_input_finished(self) -> None:
        try:
            text = self._value_input.text().replace(",", ".")
            val = float(text)
            ok, err = self.set_field_value(val)
            if not ok:
                if self._value_input:
                    self._value_input.setText(str(self._value))
                if err and _HAS_QT:
                    QMessageBox.warning(self, "Ошибка валидации", err)
                return
            if self._slider:
                pos = max(
                    self._slider.minimum(),
                    min(self._slider_value_from_real(val), self._slider.maximum()),
                )
                self._slider.setValue(pos)
            self._value = self._transfer_value(self._slider.value() if self._slider else val)
            self._notify_external()
        except ValueError:
            if self._value_input:
                self._value_input.setText(str(self._value))

    def _flush_value(self) -> None:
        self._block_signals = False
        meta = self.get_metadata()
        val = self._value
        if isinstance(val, (int, float)) and meta:
            min_v, max_v = meta.get("min"), meta.get("max")
            if min_v is not None and val < min_v:
                val = min_v
            if max_v is not None and val > max_v:
                val = max_v
        self.set_field_value(val)
        self._notify_external()

    def _notify_external(self) -> None:
        """Уведомить observers, ui_elements, controls и parent.send_register_update."""
        if hasattr(self._registers_manager, "notify_field_changed"):
            self._registers_manager.notify_field_changed(
                self._register_name, self._field_name, self._value
            )
        if self._ui_elements is not None and self._field_name in self._ui_elements:
            self._ui_elements[self._field_name]["value"] = self._value
        if self._controls is not None:
            if isinstance(self._controls, list):
                for ctrl in self._controls:
                    ctrl[self._field_name] = self._value
            else:
                self._controls[self._field_name] = self._value
        parent = self.parent() if _HAS_QT else None
        if parent and getattr(parent, "send_register_update", None):
            parent.send_register_update(
                self._register_name, self._field_name, self._value
            )
        elif self._callback is not None:
            if isinstance(self._callback, list):
                for fn in self._callback:
                    fn()
            else:
                self._callback()

    def _update_value_silent(self, value: Any) -> None:
        if not self._slider or not self._value_input:
            return
        pos = max(
            self._slider.minimum(),
            min(self._slider_value_from_real(value), self._slider.maximum()),
        )
        self._block_signals = True
        try:
            self._slider.blockSignals(True)
            self._value_input.blockSignals(True)
            self._slider.setValue(pos)
            self._value = self._transfer_value(pos)
            self._value_input.setText(str(self._value))
        finally:
            self._slider.blockSignals(False)
            self._value_input.blockSignals(False)
            self._block_signals = False

    def _show_touch_keyboard(self, event: Any) -> None:
        """Показать touch-клавиатуру при клике на поле ввода."""
        if self._touch_keyboard_factory and self._value_input:
            kb = self._touch_keyboard_factory()
            kb.input = self._value_input
            kb.enter = self._on_input_finished
            kb.show()
            kb.raise_()
            kb.activateWindow()
        if self._value_input:
            super(QLineEdit, self._value_input).mousePressEvent(event)
