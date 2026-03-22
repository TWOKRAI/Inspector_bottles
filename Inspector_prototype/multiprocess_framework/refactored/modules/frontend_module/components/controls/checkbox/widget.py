# -*- coding: utf-8 -*-
"""
CheckboxControl — метка + чекбокс с привязкой к bool-полю регистра.

**Ответственность:** размещение пары виджетов, реакция на ``stateChanged``,
делегирование чтения/записи в ``BaseConfigurableWidget``.

- Раскладка — ``layout_builder.py``; уведомления — ``common/field_sync.py``; конфиг — ``schema/``.
"""
from __future__ import annotations

from typing import Any, Optional, Union

from frontend_module.components.controls.common.field_sync import publish_control_value_to_observers
from frontend_module.components.controls.checkbox.layout_builder import create_checkbox_layout
from frontend_module.components.controls.checkbox.schema import CheckboxConfig
from frontend_module.components.controls.checkbox.styles import (
    CHECKBOX_FIXED_HEIGHT_PX,
    CHECKBOX_FIXED_WIDTH_PX,
)
from frontend_module.components.controls.primitives import create_control_label
from frontend_module.core.base_configurable_widget import BaseConfigurableWidget
from frontend_module.core.qt_imports import QCheckBox, Qt
from frontend_module.core.schema_config import coerce_schema_config


class CheckboxControl(BaseConfigurableWidget):
    """
    Чекбокс с подписью и привязкой к полю регистра.

    Позиция подписи задаётся :class:`~frontend_module.components.controls.checkbox.schema.CheckboxConfig`.

    Пример::

        CheckboxControl(
            config=CheckboxConfig(
                register_name="renderer",
                field_name="show_mask",
                label="Показать маску",
                position="left",
            ),
            registers_manager=rm,
            parent=parent,
        )
    """

    def __init__(
        self,
        config: Optional[Union[CheckboxConfig, dict]] = None,
        registers_manager: Optional[Any] = None,
        parent: Optional[Any] = None,
    ) -> None:
        """Нормализация ``CheckboxConfig`` и вызов базового конструктора."""
        self._label_widget: Optional[Any] = None
        self._checkbox: Optional[Any] = None
        cfg = coerce_schema_config(config, CheckboxConfig)
        self._position = cfg.position

        super().__init__(
            config=cfg,
            registers_manager=registers_manager,
            parent=parent,
        )

    def _load_metadata(self) -> None:
        """
        Первичная сборка UI или обновление состояния при повторном применении метаданных.
        """
        if not self._resolved_meta or not self._registers_manager:
            return

        m = self._resolved_meta
        can_modify = self._can_modify()
        current = bool(self._read_value() or m.default_val)

        if self._checkbox is None:
            self._build_ui(m.label, m.description, current, can_modify)
        else:
            self._checkbox.blockSignals(True)
            try:
                self._checkbox.setChecked(current)
                self._checkbox.setEnabled(can_modify)
            finally:
                self._checkbox.blockSignals(False)

    def _build_ui(
        self, display_text: str, tooltip: str, value: bool, can_modify: bool
    ) -> None:
        """Создать ``QLabel``, ``QCheckBox`` и назначить layout через :func:`create_checkbox_layout`."""
        self._label_widget = create_control_label(
            self,
            display_text,
            alignment=Qt.AlignCenter,
            tooltip=tooltip,
        )

        self._checkbox = QCheckBox()
        self._checkbox.setFixedSize(CHECKBOX_FIXED_WIDTH_PX, CHECKBOX_FIXED_HEIGHT_PX)
        self._checkbox.setChecked(value)
        self._checkbox.setEnabled(can_modify)
        self._checkbox.stateChanged.connect(self._on_state_changed)

        layout = create_checkbox_layout(self._position, self._label_widget, self._checkbox)
        self.setLayout(layout)

    def _update_access_level(self) -> None:
        """Обновить ``enabled`` чекбокса при смене уровня доступа."""
        if self._checkbox:
            self._checkbox.setEnabled(self._can_modify())

    def _on_state_changed(self, state: int) -> None:
        """Запись bool в регистр и уведомление слушателей при успехе."""
        value = state == Qt.Checked
        ok, _ = self._write_value(value)
        if ok:
            self._notify_external(value)

    def _notify_external(self, value: bool) -> None:
        """Делегирование в ``publish_control_value_to_observers`` (``common/field_sync.py``)."""
        publish_control_value_to_observers(
            registers_manager=self._registers_manager,
            register_name=self._register_name,
            field_name=self._field_name,
            value=value,
            parent_widget=self.parent(),
        )

    def _update_value_silent(self, value: Any) -> None:
        """Установить галочку без эмита ``stateChanged``."""
        if self._checkbox is None:
            return
        self._checkbox.blockSignals(True)
        try:
            self._checkbox.setChecked(bool(value))
        finally:
            self._checkbox.blockSignals(False)
