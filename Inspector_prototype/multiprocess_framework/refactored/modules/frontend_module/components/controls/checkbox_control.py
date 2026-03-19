# -*- coding: utf-8 -*-
"""
CheckboxControl — чекбокс с привязкой к регистру.

Читает описание из метаданных. Поддерживает observer.
"""
from __future__ import annotations

from typing import Any, Optional

from frontend_module.core.base_configurable_widget import BaseConfigurableWidget
from frontend_module.core.qt_imports import QCheckBox, QFont, QHBoxLayout, QLabel, QVBoxLayout, QWidget, Qt


class CheckboxControl(BaseConfigurableWidget):
    """
    Чекбокс с автоматической конфигурацией из метаданных регистра.

    Использование:
        cb = CheckboxControl(
            register_name="draw",
            field_name="circles",
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
        position: str = "left",
        **kwargs: Any,
    ) -> None:
        self._label_widget: Optional[Any] = None
        self._checkbox: Optional[Any] = None
        self._custom_label = label
        self._position = position

        super().__init__(
            register_name=register_name,
            field_name=field_name,
            registers_manager=registers_manager,
            access_level=access_level,
            parent=parent,
            **kwargs,
        )

    def _load_metadata(self) -> None:
        if not all([self._registers_manager, self._register_name, self._field_name]):
            return

        meta = self.get_metadata()
        if not meta:
            return

        description = meta.get("info") or meta.get("description", self._field_name)
        can_modify = self._can_modify()
        current = bool(self.get_field_value() or meta.get("default", False))

        if self._checkbox is None:
            self._build_ui(description, current, can_modify)
        else:
            self._checkbox.blockSignals(True)
            try:
                self._checkbox.setChecked(current)
                self._checkbox.setEnabled(can_modify)
            finally:
                self._checkbox.blockSignals(False)

    def _build_ui(self, description: str, value: bool, can_modify: bool) -> None:
        font = QFont("Arial", 11)
        display_text = self._custom_label or description

        self._label_widget = QLabel(display_text)
        self._label_widget.setFont(font)
        self._label_widget.setWordWrap(True)
        self._label_widget.setAlignment(Qt.AlignCenter)
        self._label_widget.setToolTip(description)

        self._checkbox = QCheckBox()
        self._checkbox.setFixedSize(44, 44)
        self._checkbox.setChecked(value)
        self._checkbox.setEnabled(can_modify)
        self._checkbox.stateChanged.connect(self._on_state_changed)

        if self._position in ("top", "bottom"):
            layout = QVBoxLayout(self)
            items = (
                [self._label_widget, self._checkbox]
                if self._position == "top"
                else [self._checkbox, self._label_widget]
            )
        else:
            layout = QHBoxLayout(self)
            items = (
                [self._label_widget, self._checkbox]
                if self._position == "left"
                else [self._checkbox, self._label_widget]
            )

        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        for item in items:
            layout.addWidget(item)

    def _update_access_level(self) -> None:
        if self._checkbox:
            self._checkbox.setEnabled(self._can_modify())

    def _on_state_changed(self, state: int) -> None:
        value = state == Qt.Checked
        ok, _ = self.set_field_value(value)
        if ok:
            self._notify_external(value)

    def _notify_external(self, value: bool) -> None:
        if hasattr(self._registers_manager, "notify_field_changed"):
            self._registers_manager.notify_field_changed(
                self._register_name, self._field_name, value
            )
        parent = self.parent()
        if parent and getattr(parent, "send_register_update", None):
            parent.send_register_update(self._register_name, self._field_name, value)

    def _update_value_silent(self, value: Any) -> None:
        if self._checkbox is None:
            return
        self._checkbox.blockSignals(True)
        try:
            self._checkbox.setChecked(bool(value))
        finally:
            self._checkbox.blockSignals(False)
