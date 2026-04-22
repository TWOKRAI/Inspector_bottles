# -*- coding: utf-8 -*-
"""
Утилиты заглушек для вкладок без RegistersManager.

Убирает дублирование текста и стилей placeholder в processing_tab, settings_tab.
"""
from __future__ import annotations

from frontend_module.core.qt_imports import QLabel


def create_registers_placeholder(tab_name: str) -> QLabel:
    """
    Заглушка при отсутствии RegistersManager.

    Args:
        tab_name: название вкладки для текста (напр. «Обработка», «Настройки»).

    Returns:
        QLabel с серым стилем, готовый к добавлению в layout.
    """
    lbl = QLabel(f"RegistersManager требуется для вкладки «{tab_name}».")
    lbl.setStyleSheet("color: gray; padding: 20px;")
    return lbl
