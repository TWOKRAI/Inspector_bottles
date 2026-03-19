# -*- coding: utf-8 -*-
"""
AdminButtonWidget — кнопка админ-панели.

Конфиг: AdminButtonConfig (label, visible). Эмитит clicked при нажатии.
Привязка при компоновке: widget.clicked.connect(open_admin).
FieldMeta — для консистентности с регистрами, tooltips, access_level.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional, Union

from data_schema_module import FieldMeta, SchemaBase, register_schema
from frontend_module.core.qt_imports import QHBoxLayout, QWidget, pyqtSignal

from ..base.button_style import create_header_button


@register_schema("AdminButtonConfig")
class AdminButtonConfig(SchemaBase):
    """Конфигурация кнопки админ-панели."""

    label: Annotated[
        str,
        FieldMeta("Подпись кнопки", info="Текст на кнопке Admin."),
    ] = "Admin"
    visible: Annotated[
        bool,
        FieldMeta("Показывать", info="Отображать кнопку админ-панели."),
    ] = True


class AdminButtonWidget(QWidget):
    """Кнопка Admin. Эмитит clicked при нажатии."""

    clicked = pyqtSignal()

    def __init__(
        self,
        config: Union[AdminButtonConfig, Dict[str, Any], None] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        cfg = AdminButtonConfig(**(config or {})) if isinstance(config, dict) else (config or AdminButtonConfig())
        data = cfg.model_dump()
        self._label = data.get("label", "Admin")
        self._visible = data.get("visible", True)
        self._button = create_header_button(label=self._label, on_click=lambda: self.clicked.emit())
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._button)
        self.setVisible(self._visible)
