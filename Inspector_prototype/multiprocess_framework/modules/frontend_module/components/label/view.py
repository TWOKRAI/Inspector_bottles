# -*- coding: utf-8 -*-
"""
LabelView — отдельный компонент подписи (QLabel).

Может использоваться самостоятельно или внутри группы.
"""
from __future__ import annotations

from typing import Optional

from multiprocess_framework.modules.frontend_module.core.qt_imports import QHBoxLayout, QLabel, QWidget


class LabelView(QWidget):
    """QLabel с настраиваемым текстом и tooltip. Отдельный компонент для групп."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._label = QLabel()
        QHBoxLayout(self).addWidget(self._label)

    def setup(self, text: str, tooltip: str = "") -> None:
        """Установить текст и подсказку."""
        self._label.setText(text)
        self._label.setToolTip(tooltip)

    def set_enabled(self, enabled: bool) -> None:
        """Включить/выключить (для визуальной согласованности с контролом)."""
        self._label.setEnabled(enabled)
