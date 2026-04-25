# multiprocess_prototype_v3/frontend/widgets/settings_tab/system_section.py
"""Заглушка секции 'Настройки системы' (в разработке)."""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.core.qt_imports import QLabel, Qt, QVBoxLayout, QWidget


class SystemSectionWidget(QWidget):
    """Placeholder: раздел системных настроек."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        lbl = QLabel("Настройки системы\n\n(Раздел в разработке)")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)
        layout.addStretch()
