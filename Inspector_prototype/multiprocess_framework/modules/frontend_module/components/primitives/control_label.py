# -*- coding: utf-8 -*-
"""
Фабрика подписи для control-виджетов.

Единый шрифт и перенос строк; не привязана к регистру.
"""
from __future__ import annotations

from typing import Any, Optional

from frontend_module.components.common.typography import label_font
from frontend_module.core.qt_imports import QLabel


def create_control_label(
    parent: Optional[Any],
    text: str,
    *,
    alignment: Any,
    word_wrap: bool = True,
    tooltip: str = "",
) -> QLabel:
    """Собрать ``QLabel`` с типографикой control и опциональным tooltip."""
    lbl = QLabel(text, parent)
    lbl.setFont(label_font())
    lbl.setWordWrap(word_wrap)
    lbl.setAlignment(alignment)
    if tooltip:
        lbl.setToolTip(tooltip)
    return lbl
