# -*- coding: utf-8 -*-
"""
HeaderButtonsWidget — список кнопок из конфига.

Конфиг: HeaderButtonsConfig (List[ButtonItem]). При клике эмитит button_clicked(id).
Привязка при компоновке: widget.button_clicked.connect(show_window).
FieldMeta — для консистентности с регистрами, tooltips, access_level.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional, Union

from data_schema_module import FieldMeta, SchemaBase, register_schema
from frontend_module.core.qt_imports import QHBoxLayout, QWidget, pyqtSignal

from ..base.button_style import create_header_button


@register_schema("HeaderButtonItem")
class HeaderButtonItem(SchemaBase):
    """Элемент кнопки в шапке."""

    id: Annotated[
        str,
        FieldMeta("ID окна", info="Ключ для show_window(id) при компоновке."),
    ] = "main"
    label: Annotated[
        str,
        FieldMeta("Подпись кнопки", info="Текст на кнопке."),
    ] = "Домой"


@register_schema("HeaderButtonsConfig")
class HeaderButtonsConfig(SchemaBase):
    """Конфигурация списка кнопок в шапке."""

    items: List[HeaderButtonItem] = []


def _to_items(config: Union[HeaderButtonsConfig, List[Dict[str, Any]], None]) -> List[Dict[str, Any]]:
    """Преобразовать конфиг в список dict для итерации."""
    if config is None:
        return []
    if isinstance(config, list):
        return config
    if isinstance(config, HeaderButtonsConfig):
        return [item.model_dump() if hasattr(item, "model_dump") else item for item in config.items]
    return []


class HeaderButtonsWidget(QWidget):
    """
    Список кнопок из конфига. Эмитит button_clicked(id) при клике.

    Конфиг: [{"id": "main", "label": "Домой"}, ...] или HeaderButtonsConfig.
    """

    button_clicked = pyqtSignal(str)

    def __init__(
        self,
        config: Union[HeaderButtonsConfig, List[Dict[str, Any]], None] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._config = _to_items(config)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addSpacing(50)
        for item in self._config:
            btn_id = item.get("id", "main")
            label = item.get("label", btn_id)

            def make_handler(wid: str):
                def _on_click():
                    self.button_clicked.emit(wid)
                return _on_click

            btn = create_header_button(label=label, on_click=make_handler(btn_id))
            layout.addWidget(btn)
            layout.addSpacing(30)
        layout.addStretch()
