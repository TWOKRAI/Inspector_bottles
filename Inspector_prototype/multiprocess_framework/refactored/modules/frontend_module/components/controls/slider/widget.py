# -*- coding: utf-8 -*-
"""
SliderControl — составной виджет: подпись, числовое поле, горизонтальный слайдер.

**Ответственность этого модуля:** оркестрация жизненного цикла Qt-виджетов и
вызов API базового класса для чтения/записи регистра.

- Пересчёт позиции ↔ значение — ``value_mapping.py``.
- Побочные эффекты (notify, legacy dicts) — ``common/field_sync.py``.
- Конфиг и пример регистра — пакет ``schema/``.
"""
from __future__ import annotations

from typing import Any, Optional, Union

from frontend_module.components.controls.primitives import (
    create_control_label,
    create_numeric_line_edit,
    create_styled_horizontal_slider,
    schedule_slider_value_commit,
)
from frontend_module.components.controls.common.field_sync import publish_control_value_to_observers
from frontend_module.components.controls.slider.legacy_sync import publish_legacy_ui_refs
from frontend_module.components.controls.slider.schema import SliderConfig
from frontend_module.components.controls.slider.styles import (
    LAYOUT_SPACING_AFTER_LABEL_PX,
    LAYOUT_SPACING_AFTER_SLIDER_PX,
    LAYOUT_SPACING_BEFORE_SLIDER_PX,
)
from frontend_module.components.controls.slider.value_mapping import (
    clamp_to_meta_range,
    real_value_to_slider_position,
    slider_position_to_value,
)
from frontend_module.core.base_configurable_widget import BaseConfigurableWidget
from frontend_module.core.qt_imports import (
    QDoubleValidator,
    QHBoxLayout,
    QIntValidator,
    QLineEdit,
    QMessageBox,
    Qt,
)
from frontend_module.core.schema_config import coerce_schema_config


class SliderControl(BaseConfigurableWidget):
    """
    Слайдер с привязкой к числовому полю регистра.

    Конфигурация привязки и UI-опций — :class:`~frontend_module.components.controls.slider.schema.SliderConfig`.
    Границы и подпись по умолчанию приходят из метаданных поля (``ResolvedMeta``).

    Пример::

        SliderControl(
            config=SliderConfig(
                register_name="processor",
                field_name="min_area",
                label="Параметр",
            ),
            registers_manager=rm,
            parent=parent,
        )
    """

    def __init__(
        self,
        config: Optional[Union[SliderConfig, dict]] = None,
        registers_manager: Optional[Any] = None,
        parent: Optional[Any] = None,
    ) -> None:
        """Инициализация: нормализация конфига, унаследованные поля из ``parent`` при необходимости."""
        self._label_widget: Optional[Any] = None
        self._value_input: Optional[Any] = None
        self._slider: Optional[Any] = None
        self._value: Any = None
        self._block_signals = False

        cfg = coerce_schema_config(config, SliderConfig)
        self._ui_elements = cfg.ui_elements
        self._controls = cfg.controls
        self._callback = cfg.callback
        self._touch_keyboard_factory = cfg.touch_keyboard_factory
        if parent and self._ui_elements is None and hasattr(parent, "ui_elements"):
            self._ui_elements = getattr(parent, "ui_elements", None)
        if parent and self._controls is None and hasattr(parent, "controls"):
            self._controls = getattr(parent, "controls", None)
        if parent and self._callback is None and hasattr(parent, "update_controls"):
            self._callback = getattr(parent, "update_controls", None)

        super().__init__(
            config=cfg,
            registers_manager=registers_manager,
            parent=parent,
        )

    def _transfer_value(self, raw: Any) -> Any:
        """Обёртка над ``slider_position_to_value`` для текущего ``_resolved_meta``."""
        return slider_position_to_value(raw, self._resolved_meta)

    def _slider_value_from_real(self, real: Any) -> int:
        """Обёртка над ``real_value_to_slider_position``."""
        return real_value_to_slider_position(real, self._resolved_meta)

    def _ensure_horizontal_layout(self) -> Any:
        """Гарантировать у корня ``QHBoxLayout`` (создать при первом вызове)."""
        layout = self.layout()
        if layout is None:
            layout = QHBoxLayout(self)
            self.setLayout(layout)
        return layout

    def _sync_parameter_label(self, layout: Any, display_label: str, description: str) -> None:
        """Создать или обновить подпись параметра (текст + tooltip)."""
        if self._label_widget is None:
            self._label_widget = create_control_label(
                self,
                display_label,
                alignment=Qt.AlignLeft | Qt.AlignVCenter,
                tooltip=description,
            )
            layout.addWidget(self._label_widget, 3)
        else:
            self._label_widget.setText(display_label)
            self._label_widget.setToolTip(description)

    def _ensure_numeric_input(self, layout: Any, can_modify: bool) -> None:
        """Создать поле ввода числа при первом проходе; обновить текст и enabled."""
        if self._value_input is None:
            self._value_input = create_numeric_line_edit(
                self, on_editing_finished=self._on_input_finished
            )
            if self._touch_keyboard_factory:
                self._value_input.mousePressEvent = self._show_touch_keyboard
            layout.addSpacing(LAYOUT_SPACING_AFTER_LABEL_PX)
            layout.addWidget(self._value_input)
            layout.addSpacing(LAYOUT_SPACING_BEFORE_SLIDER_PX)

        self._value_input.setText(str(self._value))
        self._value_input.setEnabled(can_modify)

    def _ensure_styled_slider(self, layout: Any) -> None:
        """Создать стилизованный ``QSlider`` и подключить ``valueChanged``."""
        if self._slider is None:
            self._slider = create_styled_horizontal_slider(self)
            self._slider.valueChanged.connect(self._on_slider_changed)
            layout.addWidget(self._slider, 17)
            layout.addSpacing(LAYOUT_SPACING_AFTER_SLIDER_PX)

    def _apply_input_validator(self) -> None:
        """``QIntValidator`` или ``QDoubleValidator`` в зависимости от ``round_k``."""
        m = self._resolved_meta
        if not m or not self._value_input:
            return
        validator = QIntValidator() if m.round_k == 0 else QDoubleValidator()
        if hasattr(validator, "setNotation"):
            validator.setNotation(QDoubleValidator.StandardNotation)
        self._value_input.setValidator(validator)

    def _apply_slider_range_and_position(self, current: Any) -> None:
        """Выставить min/max трека и позицию без эмита сигналов слайдера."""
        m = self._resolved_meta
        if not m or not self._slider:
            return
        min_pos = int(m.min_val / m.transfer_k) if m.transfer_k != 1 else int(m.min_val)
        max_pos = int(m.max_val / m.transfer_k) if m.transfer_k != 1 else int(m.max_val)
        self._slider.setMinimum(min_pos)
        self._slider.setMaximum(max_pos)
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

    def _load_metadata(self) -> None:
        """
        Построить или обновить UI по ``_resolved_meta`` (вызывается из ``BaseConfigurableWidget``).

        Читает текущее значение регистра, синхронизирует подпись, поле, слайдер.
        """
        if not self._resolved_meta or not self._registers_manager:
            return

        m = self._resolved_meta
        can_modify = self._can_modify()
        current = self._read_value() or m.default_val
        if self._slider is not None:
            self._value = self._transfer_value(self._slider_value_from_real(current))
        else:
            self._value = float(current) if isinstance(current, (int, float)) else current

        layout = self._ensure_horizontal_layout()

        display_label = m.label
        if m.unit:
            display_label += f" ({m.unit})"
        self._sync_parameter_label(layout, display_label, m.description)

        self._ensure_numeric_input(layout, can_modify)
        self._apply_input_validator()

        self._ensure_styled_slider(layout)
        self._apply_slider_range_and_position(current)
        publish_legacy_ui_refs(
            field_name=self._field_name,
            value=self._value,
            slider_element=self._slider,
            can_modify=can_modify,
            ui_elements=self._ui_elements,
            controls=self._controls,
            resolved_meta=self._resolved_meta,
        )

    def _update_access_level(self) -> None:
        """Пере-применить ``enabled`` на слайдере и поле ввода при смене прав."""
        if self._slider and self._value_input:
            can = self._can_modify()
            self._slider.setEnabled(can)
            self._value_input.setEnabled(can)

    def _on_slider_changed(self, value: int) -> None:
        """
        Живое обновление: текст в line edit сразу; запись в регистр — отложенно.

        См. ``schedule_slider_value_commit`` в ``primitives/value_bridge.py``.
        """
        self._value = self._transfer_value(value)
        if self._value_input:
            self._value_input.setText(str(self._value))
        if not self._block_signals:
            self._block_signals = True
            schedule_slider_value_commit(self, self._flush_value)

    def _on_input_finished(self) -> None:
        """Фиксация по завершении редактирования поля: валидация, запись, синхронизация трека."""
        try:
            text = self._value_input.text().replace(",", ".")
            val = float(text)
            ok, err = self._write_value(val)
            if not ok:
                if self._value_input:
                    self._value_input.setText(str(self._value))
                if err:
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
        """Завершение отложенной записи после движения слайдера (кламп + ``set_field_value``)."""
        self._block_signals = False
        val = self._value
        if self._resolved_meta and isinstance(val, (int, float)):
            val = clamp_to_meta_range(val, self._resolved_meta)
        self._write_value(val)
        self._notify_external()

    def _notify_external(self) -> None:
        """Делегирование в ``publish_control_value_to_observers`` (``common/field_sync.py``)."""
        publish_control_value_to_observers(
            registers_manager=self._registers_manager,
            register_name=self._register_name,
            field_name=self._field_name,
            value=self._value,
            parent_widget=self.parent(),
            ui_elements=self._ui_elements,
            controls=self._controls,
            callback=self._callback,
        )

    def _update_value_silent(self, value: Any) -> None:
        """Обновить слайдер и поле без эмита сигналов (подписка на регистр)."""
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
        """Показать экранную клавиатуру при нажатии на поле (если задана фабрика)."""
        if self._touch_keyboard_factory and self._value_input:
            kb = self._touch_keyboard_factory()
            kb.input = self._value_input
            kb.enter = self._on_input_finished
            kb.show()
            kb.raise_()
            kb.activateWindow()
        if self._value_input:
            super(QLineEdit, self._value_input).mousePressEvent(event)
