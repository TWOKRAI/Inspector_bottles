# multiprocess_prototype_v3/frontend/widgets/settings_tab/admin_section.py
"""Заглушка секции 'Администрация' (в разработке)."""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.core.qt_imports import QLabel, Qt, QVBoxLayout, QWidget


class AdminSectionWidget(QWidget):
    """Placeholder: раздел администрирования."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        lbl = QLabel("Администрация\n\n(Раздел в разработке — логи, права пользователей)")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)
        layout.addStretch()
